"""The venue: what actually submits an order, and how we find out what it did.

THE TESTS THAT MATTER HERE ARE THE ONES ABOUT ORDER AND ABSENCE, for the same
reason as the kill switch: a venue that submits when it should refuse, or that
records after it sends instead of before, fails silently and expensively. One
that refuses when it should permit is merely annoying and is noticed at once.

Five properties carry the weight, and each is a named test rather than a line in
a docstring, because every one of them is a thing that was true when it was
written and can quietly stop being true:

  intent before transmission    test_the_intent_is_on_disk_before_the_transport_
                                is_touched - checked from INSIDE the transmit,
                                so it is the ordering itself and not a re-read
                                afterwards that would pass either way
  fail closed                   test_a_journal_that_cannot_be_written_stops_the_
                                submission - the transport is never called
  idempotency                   test_the_same_key_twice_does_not_create_a_second_
                                order
  no retry after unknown        test_an_unknown_outcome_exposes_no_retry_path -
                                asserts the public SURFACE, not the behaviour
  the broker is authoritative   test_the_venue_refuses_with_the_callers_check_
                                stubbed_to_allow

NO NETWORK REACHES ALPACA. The adapter is driven against a stub HTTP server on
loopback; the rest is an in-process fake. Every symbol and id here is obviously
not real, because this repository is public.
"""

import http.server
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import killswitch
    import venue
except ImportError as exc:
    venue = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


# Obviously fake, on purpose: this repo is public and a fixture that looked like
# a real holding is a financial artifact in the tree.
TICKET = {"symbol": "ZZFAKE", "side": "buy", "type": "limit",
          "quantity": 5, "limit_price": 12.5}
OTHER_TICKET = {"symbol": "QQFAKE", "side": "sell", "type": "limit",
                "quantity": 7, "limit_price": 3.25}
CONFIG = {"max_notional": 25000, "max_orders_per_day": 3}

STUB_KEY = "NOT-A-REAL-KEY-ID"
STUB_SECRET = "NOT-A-REAL-SECRET"

# Anything that would let an unknown outcome be sent a second time. The point is
# that none of these NAMES exists, not that they are guarded.
RETRY_NAMES = re.compile(
    r"retry|resubmit|re_submit|resend|re_send|reattempt|requeue|try_again|redo",
    re.IGNORECASE)


class _NeedsVenue(unittest.TestCase):
    def setUp(self):
        if venue is None:
            self.fail(f"agentmux-broker/venue.py is missing: {IMPORT_ERROR}")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # The broker root for this test: a temporary directory, never the
        # operator's real one. writejournal.default_path() honours AGENTMUX_HOME
        # for exactly this reason and every path here is explicit anyway.
        self.root = Path(self.temp.name) / "broker"
        self.root.mkdir(parents=True)

    def sim(self, **kw):
        kw.setdefault("root", self.root)
        kw.setdefault("guardrails_config", CONFIG)
        return venue.PaperSimVenue(**kw)

    def disarm(self, config=CONFIG):
        return killswitch.disarm(killswitch.DISARM_PHRASE, actor="tester",
                                 config=config, root=self.root)

    def armed(self):
        return killswitch.state(self.root, config=CONFIG)["armed"]

    def journal_rows(self):
        path = self.root / venue.JOURNAL_NAME
        if not path.is_file():
            return []
        return [json.loads(line) for line
                in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def ledger(self, key):
        path = venue._ledger_path(self.root, key)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


class InterfaceTests(_NeedsVenue):
    def test_the_interface_cannot_be_used_without_a_transport(self):
        # ExecutionVenue is the contract, not a venue. A subclass that supplies
        # neither _transmit nor _fetch is not instantiable, so there is no way
        # to have a venue-shaped object that silently does nothing.
        with self.assertRaises(TypeError):
            venue.ExecutionVenue(root=self.root)

        class Half(venue.ExecutionVenue):
            def _transmit(self, ticket, idempotency_key):
                return {}
        with self.assertRaises(TypeError):
            Half(root=self.root)

    def test_a_capability_this_venue_lacks_raises_rather_than_faking_it(self):
        """A missing capability must LOOK missing.

        The failure this prevents is a read-back that 'passed' because an empty
        list came back from a venue that cannot list anything.
        """
        sim = self.sim(can_list_recent=False, can_cancel=False)
        self.assertFalse(sim.supports("recent"))
        self.assertFalse(sim.supports("cancel"))
        for call in (lambda: sim.recent(), lambda: sim.cancel("SIM-0001")):
            with self.assertRaises(venue.NotSupported):
                call()
        # And the base class's optional methods are NotSupported by default, so
        # an adapter that forgets one does not inherit a fake answer.
        full = self.sim()
        self.assertEqual(venue.ExecutionVenue.capabilities(full)["recent"], False)
        with self.assertRaises(venue.NotSupported):
            venue.ExecutionVenue._fetch_recent(full, 0)
        with self.assertRaises(venue.NotSupported):
            venue.ExecutionVenue._cancel(full, "SIM-0001")

    def test_describe_names_the_venue_its_mode_and_every_capability(self):
        described = self.sim().describe()
        self.assertEqual(described["venue"], "paper-sim")
        self.assertEqual(described["mode"], "paper")
        self.assertEqual(set(described["capabilities"]), set(venue.CAPABILITIES))
        self.assertIn(venue.JOURNAL_NAME, described["journal"])

    def test_submit_takes_no_override_argument(self):
        """Same signature check as test_broker_side_check_is_authoritative.

        There is no argument a caller could pass that should outrank what is on
        the disk, so the absence is asserted on the SIGNATURE rather than left
        to whoever adds the next parameter.
        """
        import inspect
        params = set(inspect.signature(venue.ExecutionVenue.submit).parameters)
        self.assertEqual(params, {"self", "ticket", "idempotency_key"})
        for override in ("force", "override", "approved", "api_says_ok",
                         "skip_killswitch", "confirmed"):
            self.assertNotIn(override, params)


class OrderingTests(_NeedsVenue):
    def test_the_intent_is_on_disk_before_the_transport_is_touched(self):
        """The whole posture of the module, checked from inside the transmit.

        Reading the journal after the fact would pass whether the write happened
        before or after the send. This reads it AT the moment of transmission.
        """
        sim = self.sim()
        self.disarm()
        real, seen = sim._transmit, []

        def checked(ticket, key):
            seen.append(self.journal_rows())
            return real(ticket, key)

        with patch.object(sim, "_transmit", side_effect=checked):
            sim.submit(dict(TICKET), "key-ordering")
        self.assertEqual(len(seen), 1)
        self.assertEqual([row["outcome"] for row in seen[0]], ["intent"])
        self.assertEqual(seen[0][0]["symbol"], "ZZFAKE")
        self.assertEqual(seen[0][0]["quantity"], 5)
        self.assertEqual(seen[0][0]["idempotency_key"], "key-ordering")

    def test_a_journal_that_cannot_be_written_stops_the_submission(self):
        """Fail closed: the error reaches the caller and nothing is sent.

        A journal that swallowed this would leave orders going out with no
        record of the intent, which is worse than no journal at all because it
        looks like one.
        """
        sim = self.sim()
        self.disarm()
        with patch.object(sim.journal, "append", side_effect=OSError("disk full")), \
                patch.object(sim, "_transmit") as transmit:
            with self.assertRaises(OSError):
                sim.submit(dict(TICKET), "key-nojournal")
            transmit.assert_not_called()
        self.assertIsNone(self.ledger("key-nojournal"))

    def test_the_idempotency_key_is_durable_before_the_transport_is_touched(self):
        """Same ordering, for the other record that has to survive a crash.

        A key burned after the send leaves a window where a process that died
        mid-submit comes back not knowing it had sent anything.
        """
        sim = self.sim()
        self.disarm()
        real, seen = sim._transmit, []

        def checked(ticket, key):
            seen.append(self.ledger(key))
            return real(ticket, key)

        with patch.object(sim, "_transmit", side_effect=checked):
            sim.submit(dict(TICKET), "key-durable")
        self.assertEqual(seen[0]["status"], "transmitting")
        self.assertEqual(seen[0]["ticket"], venue._ticket_digest(TICKET))
        self.assertIsNone(seen[0]["outcome"])

    def test_a_malformed_ticket_reaches_neither_the_journal_nor_the_transport(self):
        # A thing that is not an order leaves no trace of an order.
        sim = self.sim()
        self.disarm()
        with patch.object(sim, "_transmit") as transmit:
            for bad in (dict(TICKET, quantity=0), dict(TICKET, symbol="not a ticker"),
                        dict(TICKET, side="hold"), {}, "ZZFAKE"):
                with self.subTest(ticket=bad), self.assertRaises(ValueError):
                    sim.submit(bad, "key-malformed")
            for bad_key in ("", "   ", None, 7):
                with self.subTest(key=bad_key), self.assertRaises(ValueError):
                    sim.submit(dict(TICKET), bad_key)
            transmit.assert_not_called()
        self.assertEqual(self.journal_rows(), [])

    def test_a_success_writes_an_intent_and_exactly_one_terminal_row(self):
        sim = self.sim()
        self.disarm()
        result = sim.submit(dict(TICKET), "key-pair")
        rows = self.journal_rows()
        self.assertEqual([row["outcome"] for row in rows], ["intent", "success"])
        self.assertEqual(len({row["id"] for row in rows}), 1)
        self.assertEqual({row["transport"] for row in rows}, {"paper-sim"})
        self.assertEqual(rows[1]["venue_order_id"], result.venue_order_id)
        self.assertEqual(result.outcome, "success")
        self.assertFalse(result.already_submitted)


class KillSwitchTests(_NeedsVenue):
    def test_the_venue_refuses_with_the_callers_check_stubbed_to_allow(self):
        """The API says allow. The venue must still refuse.

        The shape of test_broker_side_check_is_authoritative, one layer out: the
        caller's check is stubbed to ALLOW and the submission still does not
        happen, because the venue re-reads the disk itself immediately before
        the click and takes no answer from anyone else.
        """
        sim = self.sim()
        with patch.object(venue.killswitch, "allowed", return_value=True) as caller, \
                patch.object(sim, "_transmit") as transmit:
            self.assertTrue(venue.killswitch.allowed(self.root, config=CONFIG))
            with self.assertRaises(killswitch.Armed):
                sim.submit(dict(TICKET), "key-armed")
            transmit.assert_not_called()
            self.assertTrue(caller.called)
        # The refusal is recorded, so the operator can see it was tried.
        rows = self.journal_rows()
        self.assertEqual([row["outcome"] for row in rows], ["intent", "rejected"])
        self.assertIn("kill switch is armed", rows[1]["detail"])

    def test_the_switch_is_re_read_from_disk_for_every_submission(self):
        # Never cached on the venue: a disarm removed between two submissions
        # has to be seen by the second one.
        sim = self.sim()
        self.disarm()
        sim.submit(dict(TICKET), "key-first")
        (self.root / killswitch.DISARM_NAME).unlink()
        with self.assertRaises(killswitch.Armed):
            sim.submit(dict(TICKET), "key-second")
        self.assertEqual(len(sim.transmissions), 1)

    def test_an_armed_switch_does_not_burn_the_idempotency_key(self):
        """Nothing was sent, so the authorisation is still good.

        The opposite would be a trap: an operator who disarms and resubmits the
        same ticket would be told it had already gone.
        """
        sim = self.sim()
        with self.assertRaises(killswitch.Armed):
            sim.submit(dict(TICKET), "key-unburned")
        self.assertIsNone(self.ledger("key-unburned"))
        self.disarm()
        result = sim.submit(dict(TICKET), "key-unburned")
        self.assertEqual(result.outcome, "success")
        self.assertEqual(len(sim.transmissions), 1)

    def test_changing_the_guardrails_re_arms_and_the_venue_refuses(self):
        # The disarm was granted under one set of rules; a venue configured with
        # different ones is not operating under the rules the operator saw.
        self.disarm(config=CONFIG)
        loosened = self.sim(guardrails_config=dict(CONFIG, max_notional=250000))
        with patch.object(loosened, "_transmit") as transmit:
            with self.assertRaises(killswitch.Armed):
                loosened.submit(dict(TICKET), "key-loosened")
            transmit.assert_not_called()


class IdempotencyTests(_NeedsVenue):
    def test_the_same_key_twice_does_not_create_a_second_order(self):
        sim = self.sim()
        self.disarm()
        first = sim.submit(dict(TICKET), "key-once")
        second = sim.submit(dict(TICKET), "key-once")
        self.assertEqual(len(sim.transmissions), 1)
        self.assertEqual(first.venue_order_id, second.venue_order_id)
        self.assertFalse(first.already_submitted)
        # A fact about this call, not an affordance: the order was already sent.
        self.assertTrue(second.already_submitted)
        self.assertEqual([row["outcome"] for row in self.journal_rows()],
                         ["intent", "success"])

    def test_a_key_reused_for_a_different_ticket_is_refused(self):
        # A key authorises ONE order. A second order wearing the first one's
        # permission is refused rather than resolved for the caller.
        sim = self.sim()
        self.disarm()
        sim.submit(dict(TICKET), "key-reused")
        with self.assertRaises(venue.IdempotencyConflict):
            sim.submit(dict(OTHER_TICKET), "key-reused")
        self.assertEqual(len(sim.transmissions), 1)

    def test_a_replayed_unknown_raises_rather_than_sending_again(self):
        """The case the whole mechanism exists for.

        The first attempt does not know whether an order exists. Sending again
        is how one unknown order becomes two.
        """
        sim = self.sim(transmit_error=venue.UnknownOutcome("the reply never came"))
        self.disarm()
        with self.assertRaises(venue.UnknownOutcome):
            sim.submit(dict(TICKET), "key-unknown")
        sim.transmit_error = None
        self.disarm()  # the first attempt re-armed it
        with self.assertRaises(venue.UnknownOutcome) as caught:
            sim.submit(dict(TICKET), "key-unknown")
        self.assertIn("look at the account", str(caught.exception))
        self.assertEqual(sim.transmissions, [])

    def test_a_replayed_rejection_raises_rather_than_sending_again(self):
        sim = self.sim(transmit_error=venue.Rejected("the venue said no"))
        self.disarm()
        with self.assertRaises(venue.Rejected):
            sim.submit(dict(TICKET), "key-rejected")
        # A clean refusal is not a reason to stop trading, so the switch stays
        # as it was - unlike an unknown.
        self.assertFalse(self.armed())
        sim.transmit_error = None
        with self.assertRaises(venue.Rejected):
            sim.submit(dict(TICKET), "key-rejected")
        self.assertEqual(sim.transmissions, [])

    def test_a_ledger_entry_that_cannot_be_read_is_unknown_not_absent(self):
        # Treating an unreadable record as "no record" would send again, which
        # is the one thing the ledger exists to prevent.
        sim = self.sim()
        self.disarm()
        path = venue._ledger_path(self.root, "key-corrupt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")
        with patch.object(sim, "_transmit") as transmit:
            with self.assertRaises(venue.UnknownOutcome):
                sim.submit(dict(TICKET), "key-corrupt")
            transmit.assert_not_called()


class UnknownOutcomeTests(_NeedsVenue):
    def test_a_transport_failure_is_unknown_and_arms_the_switch(self):
        sim = self.sim(transmit_error=TimeoutError("no answer"))
        self.disarm()
        self.assertFalse(self.armed())
        with self.assertRaises(venue.UnknownOutcome):
            sim.submit(dict(TICKET), "key-timeout")
        self.assertTrue(self.armed())
        rows = self.journal_rows()
        self.assertEqual([row["outcome"] for row in rows], ["intent", "unknown"])
        self.assertEqual(self.ledger("key-timeout")["outcome"], "unknown")

    def test_an_unknown_outcome_exposes_no_retry_path(self):
        """Not a disabled retry. No method, anywhere, under any name.

        Asserted against the SURFACE rather than the behaviour, because a
        behaviour test passes right up until someone adds the convenience
        method, and the convenience method is the whole hazard.
        """
        sim = self.sim(transmit_error=venue.UnknownOutcome("the reply never came"))
        self.disarm()
        with self.assertRaises(venue.UnknownOutcome) as caught:
            sim.submit(dict(TICKET), "key-noretry")

        surfaces = [venue, venue.ExecutionVenue, venue.PaperSimVenue,
                    venue.AlpacaPaperVenue, venue.Submission, sim,
                    caught.exception]
        for surface in surfaces:
            for name in dir(surface):
                if name.startswith("_"):
                    continue
                self.assertIsNone(
                    RETRY_NAMES.search(name),
                    f"{surface!r} exposes {name!r}; an unknown outcome is "
                    "investigated at the account, never sent again")
        # Private helpers too: a retry reachable from inside is still a retry.
        source = Path(venue.__file__).read_text(encoding="utf-8")
        self.assertEqual(
            [], re.findall(r"def\s+\w*(?:retry|resubmit|resend|reattempt|"
                           r"requeue|redo)\w*", source, re.IGNORECASE))


class ReadBackTests(_NeedsVenue):
    def test_a_matched_read_back_is_recorded_as_success_by_order_id(self):
        sim = self.sim()
        self.disarm()
        result = sim.submit(dict(TICKET), "key-match")
        self.assertEqual(result.matched_by, "order_id")
        self.assertEqual(result.outcome, "success")
        self.assertFalse(self.armed())
        echoed = sim.read_back(result)
        self.assertEqual(echoed["symbol"], "ZZFAKE")
        self.assertEqual(echoed["quantity"], 5)

    def test_read_back_falls_back_to_symbol_side_quantity_and_time(self):
        # A venue that acknowledges without a usable id is exactly why the
        # fallback exists.
        sim = self.sim(ack_without_id=True)
        self.disarm()
        result = sim.submit(dict(TICKET), "key-fallback")
        self.assertEqual(result.matched_by, "attributes")
        self.assertEqual(result.outcome, "success")
        self.assertFalse(self.armed())

    def test_an_order_outside_the_time_window_is_not_a_match(self):
        """Yesterday's identical order must not answer for today's.

        The attribute fallback is (symbol, side, quantity, submitted_at +/-
        120s); without the time bound it would match any order ever placed in
        that name and size.
        """
        sim = self.sim(ack_without_id=True,
                       distort=lambda order: dict(order,
                                                  submitted_at=order["submitted_at"] - 600))
        self.disarm()
        with self.assertRaises(venue.VerificationMismatch):
            sim.submit(dict(TICKET), "key-stale")
        self.assertTrue(self.armed())
        self.assertEqual(venue.MATCH_WINDOW_S, 120.0)

    def test_a_read_back_that_disagrees_arms_the_switch_and_cancels_nothing(self):
        """The scariest read-back: our id, somebody else's quantity.

        An automatic cancel here would be one more unconfirmed order action
        taken by software that has just demonstrated it does not know what it
        did, so the venue stops and the operator looks.
        """
        sim = self.sim(distort=lambda order: dict(order, qty="999"))
        self.disarm()
        with patch.object(sim, "_cancel") as cancel:
            with self.assertRaises(venue.VerificationMismatch) as caught:
                sim.submit(dict(TICKET), "key-disagree")
            cancel.assert_not_called()
        self.assertIn("999", str(caught.exception))
        self.assertTrue(self.armed())
        self.assertEqual(sim.cancelled, [])
        rows = self.journal_rows()
        self.assertEqual([row["outcome"] for row in rows], ["intent", "unknown"])
        self.assertIn("verification mismatch", rows[1]["detail"])

    def test_a_field_the_venue_did_not_report_is_a_mismatch_not_a_pass(self):
        # "We could not compare it" and "it agrees" are different facts, and
        # only one of them is a reason to stop worrying.
        sim = self.sim(distort=lambda order: {k: v for k, v in order.items()
                                              if k != "symbol"})
        self.disarm()
        with self.assertRaises(venue.VerificationMismatch) as caught:
            sim.submit(dict(TICKET), "key-missingfield")
        self.assertIn("symbol", str(caught.exception))
        self.assertTrue(self.armed())

    def test_a_venue_that_cannot_read_back_is_unknown_and_arms_the_switch(self):
        # Not a success with the checking skipped.
        sim = self.sim(can_read_back=False)
        self.disarm()
        with self.assertRaises(venue.UnknownOutcome):
            sim.submit(dict(TICKET), "key-noreadback")
        self.assertTrue(self.armed())
        self.assertEqual(self.ledger("key-noreadback")["outcome"], "unknown")

    def test_without_the_recent_capability_there_is_no_attribute_fallback(self):
        sim = self.sim(ack_without_id=True, can_list_recent=False)
        self.disarm()
        with self.assertRaises(venue.VerificationMismatch) as caught:
            sim.submit(dict(TICKET), "key-nofallback")
        self.assertIn("cannot list recent orders", str(caught.exception))
        self.assertTrue(self.armed())


# ── the Alpaca adapter, against a stub on loopback ───────────────────────────

class _StubState:
    def __init__(self):
        self.orders, self.by_client, self.requests = {}, {}, []
        self.sequence, self.force = 0, None


class _StubHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    @property
    def state(self):
        return self.server.state

    def _send(self, code, payload):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _record(self, method, body=None):
        # Lower-cased, because urllib.request capitalises header names on the
        # way out ("APCA-API-KEY-ID" leaves as "Apca-api-key-id") and HTTP
        # treats them case-insensitively. A test that asserted the literal case
        # would be asserting urllib's formatting, not that the key was sent.
        self.state.requests.append(
            {"method": method, "path": self.path, "body": body,
             "headers": {k.lower(): v for k, v in self.headers.items()}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._record("POST", body)
        if self.state.force is not None:
            return self._send(*self.state.force)
        client_id = body.get("client_order_id")
        if client_id in self.state.by_client:
            # What Alpaca does with a duplicate client order id, which is the
            # far end of the idempotency guarantee.
            return self._send(422, {"message": "client_order_id must be unique"})
        self.state.sequence += 1
        order = {
            "id": f"stub-order-{self.state.sequence:04d}",
            "client_order_id": client_id, "symbol": body.get("symbol"),
            "side": body.get("side"), "qty": body.get("qty"), "status": "accepted",
            "submitted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        self.state.orders[order["id"]] = order
        self.state.by_client[client_id] = order
        self._send(200, order)

    def do_GET(self):
        self._record("GET")
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/v2/orders:by_client_order_id":
            client_id = (query.get("client_order_id") or [None])[0]
            order = self.state.by_client.get(client_id)
            return self._send(200, order) if order else self._send(404, {"message": "order not found"})
        if parsed.path == "/v2/orders":
            return self._send(200, list(self.state.orders.values()))
        if parsed.path.startswith("/v2/orders/"):
            order = self.state.orders.get(parsed.path.rsplit("/", 1)[-1])
            return self._send(200, order) if order else self._send(404, {"message": "order not found"})
        self._send(404, {"message": "no such route"})

    def do_DELETE(self):
        self._record("DELETE")
        order_id = urllib.parse.urlparse(self.path).path.rsplit("/", 1)[-1]
        order = self.state.orders.get(order_id)
        if order is None:
            return self._send(404, {"message": "order not found"})
        order["status"] = "canceled"
        self._send(204, None)


class AlpacaPaperTests(_NeedsVenue):
    def setUp(self):
        super().setUp()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        self.server.state = _StubState()
        self.state = self.server.state
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.env = {venue.KEY_ENV: STUB_KEY, venue.SECRET_ENV: STUB_SECRET}

    def alpaca(self, **kw):
        kw.setdefault("root", self.root)
        kw.setdefault("guardrails_config", CONFIG)
        kw.setdefault("base_url", self.base_url)
        kw.setdefault("env", self.env)
        return venue.AlpacaPaperVenue(**kw)

    def test_the_live_endpoint_is_refused_by_construction(self):
        """There is no flag that turns this adapter live.

        A paper adapter that could be pointed at production by a configuration
        value is a live adapter with a default.
        """
        for live in ("https://api.alpaca.markets", "https://api.alpaca.markets/v2",
                     "https://broker-api.alpaca.markets"):
            with self.subTest(url=live), self.assertRaises(ValueError) as caught:
                venue.AlpacaPaperVenue(root=self.root, base_url=live, env=self.env)
            self.assertIn("LIVE", str(caught.exception))

    def test_only_the_paper_host_and_loopback_are_accepted(self):
        # A whitelist, not a blacklist: a live endpoint Alpaca adds tomorrow is
        # refused by one and permitted by the other.
        self.assertEqual(venue.check_base_url(f"https://{venue.PAPER_HOST}"),
                         f"https://{venue.PAPER_HOST}")
        self.assertEqual(venue.check_base_url(self.base_url), self.base_url)
        for bad in ("https://alpaca-paper-api.example.com", "http://example.com",
                    f"http://{venue.PAPER_HOST}", "ftp://127.0.0.1", "", None):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                venue.check_base_url(bad)

    def test_the_credentials_come_from_the_environment_and_name_where_not_to_put_them(self):
        self.assertEqual(venue.read_credentials(self.env), (STUB_KEY, STUB_SECRET))
        for missing in ({}, {venue.KEY_ENV: STUB_KEY}, {venue.SECRET_ENV: STUB_SECRET}):
            with self.subTest(env=sorted(missing)), \
                    self.assertRaises(venue.VenueError) as caught:
                venue.read_credentials(missing)
            message = str(caught.exception)
            self.assertIn(venue.KEY_ENV, message)
            self.assertIn(venue.SECRET_ENV, message)
            # ~/.agentmux/env is sourced into every agent pane, so a key placed
            # there is handed to every worker. The error says so.
            self.assertIn(".agentmux/env", message)

    def test_describe_says_whether_a_credential_is_configured_and_never_what_it_is(self):
        described = self.alpaca().describe()
        blob = json.dumps(described)
        self.assertNotIn(STUB_SECRET, blob)
        self.assertNotIn(STUB_KEY, blob)
        self.assertTrue(described["credentials"]["configured"])
        self.assertEqual(described["credentials"]["source"], "environment")
        self.assertFalse(self.alpaca(env={}).describe()["credentials"]["configured"])

    def test_no_credential_literal_is_committed_in_the_module(self):
        source = Path(venue.__file__).read_text(encoding="utf-8")
        found = re.findall(
            r"""(?i)(?:secret|api[_-]?key|token|password)\s*=\s*["'][A-Za-z0-9/+_-]{16,}["']""",
            source)
        self.assertEqual(found, [])

    def test_a_paper_order_round_trips_through_the_stub(self):
        alpaca = self.alpaca()
        self.disarm()
        result = alpaca.submit(dict(TICKET), "key-alpaca")
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.matched_by, "order_id")
        self.assertTrue(result.venue_order_id.startswith("stub-order-"))
        self.assertFalse(self.armed())
        echoed = alpaca.read_back(result)
        self.assertEqual((echoed["symbol"], echoed["side"], echoed["quantity"]),
                         ("ZZFAKE", "buy", 5))
        self.assertEqual([row["outcome"] for row in self.journal_rows()],
                         ["intent", "success"])

    def test_the_idempotency_key_is_sent_as_the_client_order_id(self):
        alpaca = self.alpaca()
        self.disarm()
        alpaca.submit(dict(TICKET), "key-clientid")
        posts = [r for r in self.state.requests if r["method"] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["body"]["client_order_id"], "key-clientid")
        self.assertEqual(posts[0]["body"]["qty"], "5")
        self.assertEqual(posts[0]["body"]["limit_price"], "12.5")
        # The credential travels in a header, never in the url or the body.
        self.assertEqual(posts[0]["headers"]["apca-api-key-id"], STUB_KEY)
        self.assertEqual(posts[0]["headers"]["apca-api-secret-key"], STUB_SECRET)
        self.assertNotIn(STUB_SECRET, posts[0]["path"])
        self.assertNotIn(STUB_SECRET, json.dumps(posts[0]["body"]))

    def test_a_refusal_is_rejected_and_a_server_fault_is_unknown(self):
        """Two different facts, acted on differently.

        Rejected means the venue said no and nothing changed. A 5xx may have
        been processed, so it is unknown - and unknown arms the switch.
        """
        alpaca = self.alpaca()
        self.disarm()
        self.state.force = (403, {"message": "insufficient buying power"})
        with self.assertRaises(venue.Rejected):
            alpaca.submit(dict(TICKET), "key-refused")
        self.assertFalse(self.armed())

        self.state.force = (500, {"message": "internal"})
        with self.assertRaises(venue.UnknownOutcome):
            alpaca.submit(dict(TICKET), "key-fault")
        self.assertTrue(self.armed())

    def test_a_duplicate_client_order_id_reads_back_rather_than_sending_again(self):
        """The far end's half of the guarantee, with our ledger gone.

        A second broker root is a machine that lost its ledger. Alpaca still
        refuses the duplicate client order id, and the adapter resolves it by
        READING, not by sending something else.
        """
        self.disarm()
        self.alpaca().submit(dict(TICKET), "key-duplicate")

        other_root = Path(self.temp.name) / "broker-two"
        other_root.mkdir()
        killswitch.disarm(killswitch.DISARM_PHRASE, actor="tester",
                          config=CONFIG, root=other_root)
        amnesiac = self.alpaca(root=other_root)
        result = amnesiac.submit(dict(TICKET), "key-duplicate")
        self.assertEqual(result.outcome, "success")
        # One order at the venue, not two.
        self.assertEqual(len(self.state.orders), 1)
        self.assertEqual(result.venue_order_id, "stub-order-0001")

    def test_the_adapter_declares_every_capability_it_really_has(self):
        alpaca = self.alpaca()
        self.disarm()
        self.assertEqual(alpaca.capabilities(),
                         {"submit": True, "read_back": True, "recent": True,
                          "cancel": True})
        result = alpaca.submit(dict(TICKET), "key-caps")
        self.assertTrue(any(order["venue_order_id"] == result.venue_order_id
                            for order in alpaca.recent(since=0)))
        # cancel() exists for an operator who has looked. Nothing calls it.
        self.assertEqual(alpaca.cancel(result)["cancelled"], True)
        self.assertEqual(self.state.orders[result.venue_order_id]["status"],
                         "canceled")


class BoundaryTests(_NeedsVenue):
    def test_the_journal_and_the_ledger_default_outside_the_repository(self):
        """This repo is PUBLIC and a push cannot be taken back.

        docs/investing-boundary.md names the two destinations; this asserts the
        code actually points at one of them when nobody passes a root.
        """
        repo = Path(venue.__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as elsewhere:
            with patch.dict(os.environ, {"LOCALAPPDATA": elsewhere}, clear=False):
                for path in (venue.order_journal_path(), venue.ledger_dir()):
                    self.assertTrue(str(path).startswith(elsewhere), path)
                    self.assertNotIn(repo, path.parents)
            environment = {k: v for k, v in os.environ.items() if k != "LOCALAPPDATA"}
            environment["AGENTMUX_HOME"] = elsewhere
            with patch.dict(os.environ, environment, clear=True):
                for path in (venue.order_journal_path(), venue.ledger_dir()):
                    self.assertTrue(str(path).startswith(elsewhere), path)
                    self.assertNotIn(repo, path.parents)

    def test_a_venue_writes_nothing_until_it_submits(self):
        # A venue that is constructed and then refuses - a bad ticket, an armed
        # switch before the journal - leaves no trace at all.
        self.sim()
        self.assertEqual(list(self.root.iterdir()), [])


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed - len(result.skipped)}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
