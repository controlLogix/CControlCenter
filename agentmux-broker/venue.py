"""Where an order actually leaves this machine, and how we find out what it did.

WHY AN INTERFACE BEFORE A BROKER. The plan builds against paper execution first:
an ExecutionVenue with an Alpaca PAPER adapter is free, has a real order
lifecycle, carries no ToS exposure, and exercises read-back, the guardrails, the
idempotency key, the kill switch and the audit record end to end with no money
and no Fidelity contact. Fidelity then becomes one adapter behind an interface
that already has a proven consumer. That is not a hedge on the decision - it is
how the first live order gets to be the first CORRECT live order.

THE ORDERING LIVES IN THE BASE CLASS, NOT IN THE ADAPTERS. submit() is a final
template: it journals, checks the switch, burns the key, transmits, reads back
and settles, in that order, once, for every venue that will ever exist here. An
adapter supplies _transmit() and _fetch() and cannot reorder any of it. The
alternative - an interface of promises each adapter keeps on its honour - is how
the second adapter ends up subtly different from the first, and the difference
is only discovered by the order that went wrong.

  1. the ticket is shaped like an order        guardrails.validate_ticket
  2. has this key already been transmitted     the ledger, read from disk
  3. intent, flushed and FSYNC'D               writejournal.intent
  4. is the switch disarmed                    killswitch, re-read, right here
  5. the key is burned, durably                before a byte goes out
  6. transmit                                  the adapter
  7. read back and verify                      the adapter, then matched here
  8. the terminal record                       success | rejected | unknown

Steps 3 and 5 are both on the disk before step 6. A process that dies between
them leaves a record of what it was trying to do and a key that says it tried -
which is the whole difference between an audit trail and a log.

A MISSING CAPABILITY MUST LOOK MISSING. Every optional method raises
NotSupported rather than returning an empty list or a None that reads like an
answer. A venue that cannot list its recent orders cannot fall back to matching
on attributes, so it says so and the verification fails closed. The failure mode
this exists to prevent is a read-back that "passed" because nothing was checked.

THERE IS NO RETRY. Not a disabled one, not a guarded one - no method. An unknown
outcome means we do not know whether an order exists, and the only safe action
is a human looking at the account. A replay of an already-transmitted key
returns what happened the first time, including by raising what it raised; it
never sends a second order. The code that would resend is the code that turns
one unknown order into two.

A MISMATCH ARMS THE SWITCH AND CANCELS NOTHING. An automatic cancel is one more
unconfirmed order action taken by software that has just demonstrated it does
not know what it did. cancel() exists for an operator who has looked; nothing in
this module calls it.

NO CREDENTIAL IS EVER IN THIS FILE, in the browser, or in ~/.agentmux/env - that
file is sourced into every agent pane, which would hand the key to every worker.
The environment of the broker process, and nowhere else.
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# writejournal.py is IMPORTED rather than copied. It already carries the
# fsync-before-the-wire guarantee, the settle-once rule and the four outcome
# words, and it exists because this project previously had three journals with
# three ideas of what an outcome is. A fourth - a private one for orders - would
# be the same mistake with a more expensive subject.
_DASHBOARD = _HERE.parent / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))

import guardrails
import killswitch
import writejournal


# How far apart the venue's timestamp and ours may be and still be the same
# order, when there is no id to match on. Two minutes: wide enough for a slow
# acknowledgement and a clock that is not ours, narrow enough that yesterday's
# identical order cannot answer for today's.
MATCH_WINDOW_S = 120.0

# Every optional thing a venue might do. Declared per adapter, and anything
# declared False raises NotSupported rather than pretending.
CAPABILITIES = ("submit", "read_back", "recent", "cancel")

# Both live OUTSIDE the repository - see docs/investing-boundary.md. This repo
# is public and a push cannot be taken back.
JOURNAL_NAME = "order-journal.jsonl"
LEDGER_DIR = "submissions"


class VenueError(Exception):
    """Something went wrong at the venue end."""


class NotSupported(VenueError):
    """This venue cannot do that, and will not pretend otherwise."""


class Rejected(VenueError):
    """The venue said no and nothing changed. A known, clean outcome."""


class UnknownOutcome(VenueError):
    """We do not know whether an order exists. Investigate at the account.

    Deliberately NOT paired with anything that resends. The switch is armed by
    the time this is raised.
    """


class VerificationMismatch(UnknownOutcome):
    """The read-back is not the order we sent. A subclass of unknown on purpose:
    an order that does not match is an order we cannot account for."""


class IdempotencyConflict(VenueError):
    """One key, two different tickets. Refused rather than guessed at."""


def _ticket_fields(ticket):
    return {
        "symbol": str(ticket.get("symbol") or "").upper(),
        "side": str(ticket.get("side") or "").lower(),
        "type": str(ticket.get("type") or "").lower(),
        "quantity": int(ticket.get("quantity") or 0),
        "limit_price": ticket.get("limit_price"),
    }


def _ticket_digest(ticket):
    """What makes two submissions of one key the same submission.

    A key is an authorisation for a SPECIFIC order. Reusing it for a different
    one is either a bug or a second order wearing the first one's permission,
    and both are refused rather than resolved for the caller.
    """
    blob = json.dumps(_ticket_fields(ticket), sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def ledger_dir(root=None):
    """Where the record of burned idempotency keys lives: outside the repo."""
    return killswitch.broker_root(root) / LEDGER_DIR


def order_journal_path(root=None):
    """Where the order journal lives: outside the repo, beside the switch."""
    return killswitch.broker_root(root) / JOURNAL_NAME


def _ledger_path(root, key):
    # Hashed, so a key cannot choose a filename and nothing about the order is
    # legible from a directory listing.
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return ledger_dir(root) / f"{digest}.json"


def _ledger_read(root, key):
    path = _ledger_path(root, key)
    try:
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A ledger entry we cannot read is not an absent one. Treating it as
        # absent would resend, which is the one thing this file exists to stop.
        raise UnknownOutcome(
            f"the submission record for this key cannot be read at {path}; "
            "whether an order was sent is unknown - look at the account")
    return record if isinstance(record, dict) else None


def _ledger_write(root, key, record):
    """Durable before it returns. Same posture as the intent, same reason."""
    path = _ledger_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    return record


class Submission:
    """What happened to one order. Carries no way to send another.

    `already_submitted` is a fact about this call, not an affordance: it says
    the key had been transmitted before and this is the recorded result.
    """

    __slots__ = ("venue", "key", "reference", "venue_order_id", "status",
                 "outcome", "symbol", "side", "quantity", "submitted_at",
                 "matched_by", "already_submitted", "detail")

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
        self.already_submitted = bool(fields.get("already_submitted"))

    @classmethod
    def from_record(cls, record, *, already_submitted=False):
        return cls(already_submitted=already_submitted,
                   **{k: record.get(k) for k in cls.__slots__
                      if k != "already_submitted"})

    def as_dict(self):
        return {name: getattr(self, name) for name in self.__slots__}

    def __repr__(self):
        return (f"<Submission {self.outcome} {self.symbol} {self.side} "
                f"{self.quantity} id={self.venue_order_id!r}>")


def _as_quantity(value):
    # Venues report quantity as a string as often as a number. A value we cannot
    # read as a whole number of shares is None, and None never compares equal.
    try:
        if isinstance(value, bool) or value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number.is_integer():
        return None
    return int(number)


def _as_epoch(value):
    """Seconds since the epoch, or None. RFC3339 in, or a number straight through."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    # Nanoseconds are common on order timestamps and datetime takes at most six
    # digits, so the tail is trimmed rather than the whole value discarded.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def normalise_order(raw):
    """One shape for what a venue says an order is. None when there is nothing."""
    if not isinstance(raw, dict):
        return None
    return {
        "venue_order_id": raw.get("venue_order_id") or raw.get("id"),
        "client_order_id": raw.get("client_order_id"),
        "symbol": (raw.get("symbol") or "").upper() or None,
        "side": (raw.get("side") or "").lower() or None,
        "quantity": _as_quantity(raw.get("quantity", raw.get("qty"))),
        "status": raw.get("status"),
        "submitted_at": _as_epoch(raw.get("submitted_at")),
        "raw": raw.get("raw", raw),
    }


def field_mismatches(order, ticket):
    """Every way this read-back is not the order on the ticket.

    A field the venue did not report is a MISMATCH, not a pass. "We could not
    compare it" and "it agrees" are different facts, and only one of them is a
    reason to stop worrying.
    """
    want = _ticket_fields(ticket)
    problems = []
    if order.get("symbol") != want["symbol"]:
        problems.append(f"the venue reports symbol {order.get('symbol')!r}, "
                        f"the ticket says {want['symbol']!r}")
    if order.get("side") != want["side"]:
        problems.append(f"the venue reports side {order.get('side')!r}, "
                        f"the ticket says {want['side']!r}")
    if order.get("quantity") != want["quantity"]:
        problems.append(f"the venue reports quantity {order.get('quantity')!r}, "
                        f"the ticket says {want['quantity']}")
    return problems


def within_window(order, submitted_at, window=MATCH_WINDOW_S):
    """Is the venue's timestamp close enough to ours to be the same order?"""
    when = order.get("submitted_at")
    if not isinstance(when, (int, float)) or not isinstance(submitted_at, (int, float)):
        return False
    return abs(float(when) - float(submitted_at)) <= window


class ExecutionVenue(ABC):
    """The thing that submits an order and then tells you what it did.

    Subclasses supply transport (_transmit, _fetch) and their capabilities. They
    do NOT get to supply the order of operations - see the module docstring.
    """

    name = "venue"
    mode = "paper"

    def __init__(self, *, root=None, guardrails_config=None, journal=None,
                 journal_path=None):
        #: Where the switch, the ledger and the journal live. None means the
        #: operator's real broker root, which is outside the repository.
        self.root = root
        #: The guardrails the kill switch's disarm was granted under. Passing it
        #: is what binds a disarm to the rules the operator actually saw: change
        #: a limit and the switch re-arms by construction.
        self.guardrails_config = guardrails_config
        self.journal = journal if journal is not None else writejournal.WriteJournal(
            Path(journal_path) if journal_path is not None
            else order_journal_path(self.root),
            transport=self.name)

    # ── capabilities ─────────────────────────────────────────────────────────

    def capabilities(self):
        """What this venue can do. Anything False raises NotSupported."""
        return {"submit": True, "read_back": True, "recent": False, "cancel": False}

    def supports(self, capability):
        if capability not in CAPABILITIES:
            raise ValueError(f"{capability!r} is not one of {CAPABILITIES}")
        return bool(self.capabilities().get(capability, False))

    def require(self, capability):
        """Raise NotSupported unless this venue really does that."""
        if not self.supports(capability):
            raise NotSupported(
                f"{self.name} does not support {capability}; it is not available "
                "here and this is not a temporary failure")

    def describe(self):
        """What this venue is. NEVER carries a credential - see read_credentials."""
        return {"venue": self.name, "mode": self.mode,
                "capabilities": dict(self.capabilities()),
                "journal": str(self.journal.path),
                "ledger": str(ledger_dir(self.root))}

    # ── the submission ───────────────────────────────────────────────────────

    def submit(self, ticket, idempotency_key):
        """Send one order, verify it, and record both. The ordering is the point.

        Takes NO override argument, for the same reason killswitch.allowed()
        takes none: there is nothing a caller could tell this method that should
        outrank what is on the disk under this process, right now.
        """
        problems = guardrails.validate_ticket(ticket)
        if problems:
            # Refused BEFORE the journal, so a malformed ticket leaves no trace
            # of an order that was never an order.
            raise ValueError("the ticket is not a valid order: " + "; ".join(problems))
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("a submission needs a non-empty idempotency key")
        self.require("submit")

        digest = _ticket_digest(ticket)

        # 2. Has this key already been transmitted? Read from disk, every time.
        recorded = _ledger_read(self.root, idempotency_key)
        if recorded is not None:
            return self._replay(recorded, idempotency_key, digest)

        # 3. The intent, flushed and fsync'd. If this raises, the caller must not
        # transmit - and it cannot, because the exception leaves this function
        # before anything reaches _transmit.
        handle = self.journal.intent({
            "venue": self.name, "mode": self.mode, "action": "submit",
            "idempotency_key": idempotency_key, "ticket": digest,
            "symbol": _ticket_fields(ticket)["symbol"],
            "side": _ticket_fields(ticket)["side"],
            "order_type": _ticket_fields(ticket)["type"],
            "quantity": _ticket_fields(ticket)["quantity"],
            "limit_price": ticket.get("limit_price"),
        })

        # 4. The switch, HERE, immediately before the click. Re-read from disk,
        # never cached, and never taken from a caller: the API runs in WSL and
        # this on Windows, so anything it told us is a claim about the past.
        try:
            killswitch.require_disarmed(self.root, config=self.guardrails_config)
        except killswitch.Armed as exc:
            # Nothing was sent, so the key is NOT burned - disarm and the same
            # ticket under the same key still goes.
            # `detail` and not `reason`: one field name for why a row settled
            # the way it did, so reading the journal does not require knowing
            # which path wrote the row.
            handle.settle("rejected", detail=f"the kill switch is armed: {exc}")
            raise

        # 5. Burn the key, durably, BEFORE the wire. A crash after this leaves a
        # key that says "a transmission was attempted", which is what makes the
        # next call a replay instead of a second order.
        fields = _ticket_fields(ticket)
        submitted_at = time.time()
        record = {
            "venue": self.name, "key": idempotency_key, "ticket": digest,
            "journal_id": handle.id, "symbol": fields["symbol"],
            "side": fields["side"], "quantity": fields["quantity"],
            "submitted_at": submitted_at, "venue_order_id": None,
            "status": "transmitting", "outcome": None, "detail": None,
        }
        _ledger_write(self.root, idempotency_key, record)

        # 6. The wire.
        try:
            ack = normalise_order(self._transmit(ticket, idempotency_key)) or {}
        except Rejected as exc:
            # The venue answered and refused. Nothing changed, so the switch
            # stays as it is: a clean refusal is not a reason to stop trading.
            self._fail(handle, record, "rejected", str(exc))
            raise
        except Exception as exc:  # noqa: BLE001 - see below
            # ANYTHING else is unknown. A timeout, a dropped socket, a bug in
            # this file: software that failed partway through a submission does
            # not know what it did, and saying "error" instead of "unknown"
            # would be a claim it has not earned.
            self._fail(handle, record, "unknown", f"{type(exc).__name__}: {exc}",
                       rearm="unknown_outcome")
            if isinstance(exc, UnknownOutcome):
                raise
            raise UnknownOutcome(
                f"the submission did not complete ({type(exc).__name__}: {exc}); "
                "whether an order exists is unknown - look at the account") from exc

        record["venue_order_id"] = ack.get("venue_order_id")
        record["status"] = ack.get("status")

        # 7. Read back. A venue that cannot be asked is an unknown outcome, not
        # a success with the checking skipped.
        try:
            order, matched_by = self._verify(ticket, ack, submitted_at)
        except VerificationMismatch as exc:
            # Arm, and DO NOT CANCEL. An automatic cancel is another unconfirmed
            # order action by software that has just proved it does not know
            # what it did.
            self._fail(handle, record, "unknown", f"verification mismatch: {exc}",
                       rearm="verification_mismatch")
            raise
        except NotSupported as exc:
            self._fail(handle, record, "unknown", f"cannot read back: {exc}",
                       rearm="unknown_outcome")
            raise UnknownOutcome(
                f"{self.name} cannot read this order back ({exc}), so what was "
                "submitted cannot be confirmed") from exc

        # 8. The terminal record.
        record["venue_order_id"] = order.get("venue_order_id") or record["venue_order_id"]
        record["status"] = order.get("status")
        record["matched_by"] = matched_by
        self._settle(handle, record, "success", None, matched_by=matched_by,
                     venue_order_id=record["venue_order_id"], status=record["status"])
        return Submission.from_record(record)

    def _replay(self, recorded, key, digest):
        """A key that has already been transmitted answers with what happened.

        It NEVER sends again. A replay that resent would turn one unknown order
        into two, which is the exact failure an idempotency key exists to
        prevent - and the reason there is no method here that resends by name.
        """
        if recorded.get("ticket") != digest:
            raise IdempotencyConflict(
                f"key {key!r} was already used for a different order "
                f"({recorded.get('side')} {recorded.get('quantity')} "
                f"{recorded.get('symbol')}); a key authorises one order")
        outcome = recorded.get("outcome")
        if outcome == "success":
            return Submission.from_record(recorded, already_submitted=True)
        if outcome == "rejected":
            raise Rejected(f"this order was already refused by {self.name}: "
                           f"{recorded.get('detail')}")
        raise UnknownOutcome(
            f"a submission under key {key!r} was already transmitted and its "
            f"outcome is {outcome or 'unrecorded'}; whether an order exists is "
            "unknown - look at the account rather than sending again")

    def _settle(self, handle, record, outcome, detail, **extra):
        record["outcome"] = outcome
        record["detail"] = detail
        _ledger_write(self.root, record["key"], record)
        handle.settle(outcome, detail=detail, **extra)

    def _fail(self, handle, record, outcome, detail, rearm=None):
        """Arm first, record second, and record even if arming went wrong.

        The switch is the safety-critical half and the audit row is the one that
        must exist afterwards whatever happened, so the try/finally gives each
        the property it needs rather than ordering them by convenience.
        """
        try:
            if rearm:
                killswitch.arm(rearm, root=self.root)
        finally:
            self._settle(handle, record, outcome, detail)

    def _verify(self, ticket, ack, submitted_at):
        """Find the order at the venue and prove it is the one we sent.

        By the venue's own order id first. Failing that, by (symbol, side,
        quantity, submitted_at +/- 120s) - and a venue that cannot list recent
        orders cannot do that, so it fails rather than skipping the check.
        """
        self.require("read_back")

        order, matched_by = None, None
        if ack.get("venue_order_id"):
            order = normalise_order(self._fetch(
                venue_order_id=ack.get("venue_order_id"),
                idempotency_key=ack.get("client_order_id")))
            if order is not None:
                matched_by = "order_id"

        if order is None:
            if not self.supports("recent"):
                raise VerificationMismatch(
                    "the venue has no order under the id it acknowledged, and "
                    f"{self.name} cannot list recent orders to match on "
                    "symbol, side, quantity and time instead")
            for candidate in self._fetch_recent(submitted_at - MATCH_WINDOW_S) or []:
                found = normalise_order(candidate)
                if found is None:
                    continue
                if not field_mismatches(found, ticket) and within_window(found, submitted_at):
                    order, matched_by = found, "attributes"
                    break

        if order is None:
            raise VerificationMismatch(
                "the venue has no record of this order, by id or by symbol, "
                "side, quantity and time")

        problems = field_mismatches(order, ticket)
        if problems:
            raise VerificationMismatch("; ".join(problems))
        return order, matched_by

    # ── read-back, on its own ────────────────────────────────────────────────

    def read_back(self, reference):
        """What the venue says about one order. None when it has no such order.

        `reference` is a Submission, or a venue order id as a string.
        """
        self.require("read_back")
        if isinstance(reference, Submission):
            return normalise_order(self._fetch(
                venue_order_id=reference.venue_order_id,
                idempotency_key=reference.key))
        if isinstance(reference, str) and reference.strip():
            return normalise_order(self._fetch(venue_order_id=reference))
        raise ValueError("a read-back needs a Submission or a venue order id")

    def recent(self, since=None):
        """Orders the venue has seen since `since` (epoch seconds)."""
        self.require("recent")
        return [normalise_order(row) for row
                in (self._fetch_recent(since if since is not None
                                       else time.time() - 86400) or [])]

    def cancel(self, reference):
        """Cancel an order. FOR AN OPERATOR WHO HAS LOOKED.

        Nothing in this module calls this. A read-back mismatch arms the switch
        and stops; it does not cancel, because a cancel is one more order action
        taken without knowing what the last one did.
        """
        self.require("cancel")
        order_id = reference.venue_order_id if isinstance(reference, Submission) \
            else reference
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("a cancel needs a venue order id")
        return self._cancel(order_id)

    # ── what an adapter supplies ─────────────────────────────────────────────

    @abstractmethod
    def _transmit(self, ticket, idempotency_key):
        """Send it. Return the venue's acknowledgement as a dict.

        Raise Rejected when the venue said no and nothing changed. Raise
        UnknownOutcome when the answer never arrived. Those are different facts
        and they are acted on differently.
        """

    @abstractmethod
    def _fetch(self, *, venue_order_id=None, idempotency_key=None):
        """One order as the venue reports it, or None when it has no such order."""

    def _fetch_recent(self, since):
        raise NotSupported(f"{self.name} cannot list recent orders")

    def _cancel(self, order_id):
        raise NotSupported(f"{self.name} cannot cancel orders")


# ── the in-process fake ──────────────────────────────────────────────────────

class PaperSimVenue(ExecutionVenue):
    """A venue with no network at all. What the suite actually drives.

    The failure hooks are here rather than in the Alpaca adapter on purpose: the
    paths worth testing are a venue that acknowledges without an id, a venue
    whose read-back disagrees with the ticket, and a venue that stops answering.
    None of those should require a stub of somebody else's API to reach.
    """

    name = "paper-sim"
    mode = "paper"

    def __init__(self, *, ack_without_id=False, distort=None,
                 transmit_error=None, can_read_back=True, can_list_recent=True,
                 can_cancel=True, **kw):
        super().__init__(**kw)
        self._orders = {}
        self._sequence = 0
        #: Acknowledge without returning an id, forcing the attribute fallback.
        self.ack_without_id = bool(ack_without_id)
        #: Applied to an order on the way out, to make a read-back disagree.
        self.distort = distort
        #: Raised from _transmit instead of sending.
        self.transmit_error = transmit_error
        self._capabilities = {"submit": True, "read_back": bool(can_read_back),
                              "recent": bool(can_list_recent),
                              "cancel": bool(can_cancel)}
        #: Everything that reached the wire, for a test to count.
        self.transmissions = []
        self.cancelled = []

    def capabilities(self):
        return dict(self._capabilities)

    def _out(self, order):
        order = dict(order)
        return self.distort(order) if self.distort is not None else order

    def _transmit(self, ticket, idempotency_key):
        if self.transmit_error is not None:
            raise self.transmit_error
        fields = _ticket_fields(ticket)
        self._sequence += 1
        order = {
            "id": f"SIM-{self._sequence:04d}",
            "client_order_id": idempotency_key,
            "symbol": fields["symbol"], "side": fields["side"],
            "qty": str(fields["quantity"]), "status": "accepted",
            "submitted_at": time.time(),
        }
        self._orders[order["id"]] = order
        self.transmissions.append({"ticket": dict(ticket), "key": idempotency_key})
        ack = dict(order)
        if self.ack_without_id:
            ack.pop("id")
        return ack

    def _fetch(self, *, venue_order_id=None, idempotency_key=None):
        self.require("read_back")
        if venue_order_id and venue_order_id in self._orders:
            return self._out(self._orders[venue_order_id])
        if idempotency_key:
            for order in self._orders.values():
                if order.get("client_order_id") == idempotency_key:
                    return self._out(order)
        return None

    def _fetch_recent(self, since):
        self.require("recent")
        floor = since if isinstance(since, (int, float)) else 0.0
        return [self._out(order) for order in self._orders.values()
                if order.get("submitted_at", 0.0) >= floor]

    def _cancel(self, order_id):
        self.require("cancel")
        self.cancelled.append(order_id)
        order = self._orders.get(order_id)
        if order is None:
            return None
        order["status"] = "canceled"
        return self._out(order)


# ── Alpaca, paper only ───────────────────────────────────────────────────────

# The one host this adapter talks to, plus loopback for a stub. A WHITELIST, not
# a blacklist of live hosts: a new live endpoint added by Alpaca tomorrow is
# refused by a whitelist and permitted by a blacklist, and only one of those
# failure modes costs money. There is no flag to widen it.
PAPER_HOST = "paper-api.alpaca.markets"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
LIVE_HOSTS = ("api.alpaca.markets", "broker-api.alpaca.markets")
DEFAULT_BASE_URL = f"https://{PAPER_HOST}"

# Read from the broker process's environment and NOWHERE ELSE. Never a literal
# in this file, never through the browser, and never in ~/.agentmux/env, which
# is sourced into every agent pane and would hand the key to every worker.
KEY_ENV = "ALPACA_PAPER_KEY_ID"
SECRET_ENV = "ALPACA_PAPER_SECRET_KEY"


def check_base_url(url):
    """Refuse anything but the paper endpoint. Raises ValueError, returns the url."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("a base url is required")
    parsed = urllib.parse.urlparse(url.rstrip("/"))
    host = (parsed.hostname or "").lower()
    if host in LIVE_HOSTS:
        raise ValueError(
            f"{host} is Alpaca's LIVE endpoint; this adapter is paper-only and "
            "there is no option that changes that")
    if host != PAPER_HOST and host not in LOOPBACK_HOSTS:
        raise ValueError(
            f"{host or url!r} is not {PAPER_HOST} and is not loopback; this "
            "adapter talks to the paper endpoint or to a local stub, nothing else")
    if parsed.scheme != "https" and host not in LOOPBACK_HOSTS:
        raise ValueError(f"{url!r} must be https")
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{parsed.scheme!r} is not an http scheme")
    return url.rstrip("/")


def read_credentials(env=None):
    """The key and secret, from the environment. Raises if they are not there.

    Read on every request rather than held from construction, so a rotated key
    takes effect and a long-lived venue object is not a copy of a secret.
    """
    env = os.environ if env is None else env
    key, secret = env.get(KEY_ENV), env.get(SECRET_ENV)
    if not key or not secret:
        raise VenueError(
            f"set {KEY_ENV} and {SECRET_ENV} in the broker process's environment; "
            "they are not stored in this repository, not entered through the "
            "browser, and NOT put in ~/.agentmux/env, which every agent pane sources")
    return key, secret


class AlpacaPaperVenue(ExecutionVenue):
    """Alpaca's paper endpoint over urllib. Stdlib only, no alpaca-py.

    The REST surface needed here is four JSON endpoints, and the sidecar's
    dependency policy is stdlib-or-vendored. A package would be a supply chain
    and an import cycle in exchange for four functions.

    NEVER pointed at the live endpoint: see check_base_url. The tests drive a
    local stub, never Alpaca.
    """

    name = "alpaca-paper"
    mode = "paper"

    def __init__(self, *, base_url=DEFAULT_BASE_URL, timeout=15.0, env=None, **kw):
        super().__init__(**kw)
        self.base_url = check_base_url(base_url)
        self.timeout = float(timeout)
        self._env = env

    def capabilities(self):
        return {"submit": True, "read_back": True, "recent": True, "cancel": True}

    def describe(self):
        """Carries NO credential - only whether one is configured."""
        try:
            read_credentials(self._env)
            configured = True
        except VenueError:
            configured = False
        return dict(super().describe(), base_url=self.base_url,
                    credentials={"source": "environment",
                                 "variables": [KEY_ENV, SECRET_ENV],
                                 "configured": configured})

    # ── http ─────────────────────────────────────────────────────────────────

    def _request(self, method, path, body=None, *, allow_status=()):
        key, secret = read_credentials(self._env)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                     "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, _decode(response.read())
        except urllib.error.HTTPError as exc:
            payload = _decode(exc.read())
            if exc.code in allow_status:
                return exc.code, payload
            if 400 <= exc.code < 500:
                # The venue answered and refused. Nothing changed.
                raise Rejected(f"{method} {path}: {exc.code} {_message(payload)}") from exc
            # 5xx: it may have been processed. We do not know.
            raise UnknownOutcome(
                f"{method} {path}: {exc.code} {_message(payload)}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UnknownOutcome(
                f"{method} {path} did not complete: {exc}") from exc

    def _transmit(self, ticket, idempotency_key):
        fields = _ticket_fields(ticket)
        body = {
            "symbol": fields["symbol"], "side": fields["side"],
            "type": fields["type"], "qty": str(fields["quantity"]),
            "time_in_force": str(ticket.get("time_in_force") or "day"),
            # The idempotency key IS the client order id. Alpaca enforces it as
            # unique, so the far end refuses a duplicate even if our own ledger
            # were lost.
            "client_order_id": idempotency_key,
        }
        if fields["type"] == "limit":
            body["limit_price"] = str(ticket["limit_price"])

        status, payload = self._request("POST", "/v2/orders", body,
                                        allow_status=(409, 422))
        if status in (409, 422):
            text = _message(payload).lower()
            if "client_order_id" not in text and "client order id" not in text:
                raise Rejected(f"POST /v2/orders: {status} {_message(payload)}")
            # The key was already used at the venue. That is the guarantee
            # working, not a failure: read the existing order back rather than
            # sending anything else.
            existing = self._fetch(idempotency_key=idempotency_key)
            if existing is None:
                raise UnknownOutcome(
                    "Alpaca reports this client order id as already used but "
                    "returns no order for it; whether an order exists is unknown")
            return existing
        return payload

    def _fetch(self, *, venue_order_id=None, idempotency_key=None):
        if venue_order_id:
            status, payload = self._request(
                "GET", f"/v2/orders/{urllib.parse.quote(str(venue_order_id), safe='')}",
                allow_status=(404,))
            if status != 404 and isinstance(payload, dict):
                return payload
        if idempotency_key:
            query = urllib.parse.urlencode({"client_order_id": idempotency_key})
            status, payload = self._request(
                "GET", f"/v2/orders:by_client_order_id?{query}", allow_status=(404,))
            if status != 404 and isinstance(payload, dict):
                return payload
        return None

    def _fetch_recent(self, since):
        query = {"status": "all", "limit": 100, "direction": "desc"}
        if isinstance(since, (int, float)):
            query["after"] = datetime.fromtimestamp(
                float(since), timezone.utc).isoformat().replace("+00:00", "Z")
        _, payload = self._request("GET", "/v2/orders?" + urllib.parse.urlencode(query))
        return payload if isinstance(payload, list) else []

    def _cancel(self, order_id):
        status, _ = self._request(
            "DELETE", f"/v2/orders/{urllib.parse.quote(str(order_id), safe='')}",
            allow_status=(404,))
        return {"venue_order_id": order_id, "cancelled": status != 404}


def _decode(raw):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"message": raw.decode("utf-8", "replace")[:500]}


def _message(payload):
    if isinstance(payload, dict):
        return str(payload.get("message") or payload)
    return str(payload)
