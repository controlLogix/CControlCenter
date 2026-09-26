"""Server-side order limits: every rule runs, every refusal says why.

THE TWO PROPERTIES THAT MATTER, and both are about what the operator is told
rather than about arithmetic:

  EVERY RULE RUNS. No short-circuit. Somebody who fixes one violation and
  resubmits into a second has been told half the truth twice, and will conclude
  the system is arguing with them.

  A MISSING NUMBER IS NEVER A SMALL ONE. An unpriced market order has no
  notional; returning zero would clear every size limit, and the order most
  likely to surprise someone would be the one that skipped the check.

The negative tests carry the weight here, as with the kill switch: a limit that
permits when it should refuse fails quietly and expensively.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import guardrails
except ImportError as exc:
    guardrails = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


CONFIG = {
    "max_notional": 25000,
    "max_portfolio_fraction": 0.10,
    "max_orders_per_day": 3,
    "denylist": ["MEME"],
    "require_limit_outside_rth": True,
    "max_trades_per_symbol_per_day": 2,
}
# A Tuesday at 10:00 Eastern - inside regular hours.
OPEN = datetime(2026, 9, 22, 10, 0)
CLOSED = datetime(2026, 9, 22, 19, 30)
CONTEXT = {"portfolio_value": 500000, "orders_today": 0, "market_time": OPEN,
           "trades_today_by_symbol": {}}
TICKET = {"symbol": "AAPL", "side": "buy", "type": "limit",
          "quantity": 100, "limit_price": 150.0}


class _NeedsGuardrails(unittest.TestCase):
    def setUp(self):
        if guardrails is None:
            self.fail(f"agentmux-broker/guardrails.py is missing: {IMPORT_ERROR}")

    def check(self, ticket=None, config=None, context=None):
        return guardrails.evaluate(ticket if ticket is not None else dict(TICKET),
                                   config=config if config is not None else CONFIG,
                                   context=context if context is not None else dict(CONTEXT))

    def rule(self, outcome, name):
        return next(r for r in outcome["results"] if r["rule"] == name)


class ShapeTests(_NeedsGuardrails):
    def test_a_well_formed_ticket_within_every_limit_passes(self):
        outcome = self.check()
        self.assertTrue(outcome["passed"], outcome["refusals"])
        self.assertEqual(outcome["refusals"], [])

    def test_a_malformed_ticket_is_refused_before_any_limit_runs(self):
        # The reasons must read as "this is not an order", not as a risk
        # decision. Running size limits against a quantity of "ten" would
        # produce nonsense that looks like a limit.
        outcome = self.check({"symbol": "aapl", "side": "long", "type": "stop",
                              "quantity": "ten"})
        self.assertFalse(outcome["passed"])
        self.assertEqual(outcome["results"], [])
        self.assertTrue(outcome["malformed"])
        self.assertTrue(all("not a valid order" in r for r in outcome["refusals"]))

    def test_a_market_order_carrying_a_limit_price_is_ambiguous_and_refused(self):
        outcome = self.check(dict(TICKET, type="market", limit_price=150.0))
        self.assertFalse(outcome["passed"])
        self.assertTrue(any("must not carry a limit_price" in p
                            for p in outcome["malformed"]))

    def test_fractional_and_negative_quantities_are_refused(self):
        for qty in (0, -5, 1.5, True, "100", None):
            with self.subTest(quantity=qty):
                outcome = self.check(dict(TICKET, quantity=qty))
                self.assertFalse(outcome["passed"])


class EveryRuleRunsTests(_NeedsGuardrails):
    def test_all_failures_are_reported_not_just_the_first(self):
        # THE property. Three violations at once must produce three reasons.
        outcome = self.check(
            dict(TICKET, symbol="MEME", quantity=1000, limit_price=500.0),
            context=dict(CONTEXT, orders_today=9))
        self.assertFalse(outcome["passed"])
        broken = {r["rule"] for r in outcome["results"] if not r["passed"]}
        self.assertIn("max_notional", broken)
        self.assertIn("symbol", broken)
        self.assertIn("max_orders_per_day", broken)
        self.assertGreaterEqual(len(outcome["refusals"]), 3)

    def test_every_rule_reports_even_when_everything_passes(self):
        outcome = self.check()
        self.assertEqual(len(outcome["results"]), len(guardrails.RULES))

    def test_a_rule_the_config_does_not_set_says_so_rather_than_passing_silently(self):
        # Deleting a line should be visible. "applies: false" is a different
        # answer from "checked and fine", and somebody who removed a limit by
        # accident needs to see which.
        outcome = self.check(config={})
        for result in outcome["results"]:
            self.assertFalse(result["applies"],
                             f"{result['rule']} claims to apply with no config")
            self.assertTrue(result["passed"])
        self.assertTrue(outcome["passed"])


class ReasonTests(_NeedsGuardrails):
    def test_a_refusal_names_the_number_that_broke_and_the_one_it_broke(self):
        # "max_notional" is not a reason. A refusal a person cannot act on is a
        # refusal they will route around.
        outcome = self.check(dict(TICKET, quantity=1000, limit_price=500.0))
        reason = self.rule(outcome, "max_notional")["reason"]
        self.assertIn("$500,000", reason)
        self.assertIn("$25,000", reason)

    def test_the_portfolio_refusal_shows_the_fraction_and_both_amounts(self):
        outcome = self.check(dict(TICKET, quantity=500, limit_price=200.0))
        reason = self.rule(outcome, "max_portfolio_fraction")["reason"]
        self.assertIn("20.0%", reason)
        self.assertIn("10%", reason)
        self.assertIn("$100,000", reason)

    def test_the_denylist_refusal_names_the_symbol(self):
        outcome = self.check(dict(TICKET, symbol="MEME"))
        self.assertIn("MEME", self.rule(outcome, "symbol")["reason"])


class MissingNumberTests(_NeedsGuardrails):
    def test_an_unpriced_market_order_is_refused_not_cleared(self):
        # THE dangerous case. notional() returns None, and a None that read as
        # zero would clear every size limit - so the order most likely to
        # surprise someone would be the one that skipped the check.
        outcome = self.check(dict(TICKET, type="market", limit_price=None),
                             context=dict(CONTEXT, mark_price=None))
        self.assertFalse(outcome["passed"])
        reason = self.rule(outcome, "max_notional")["reason"]
        self.assertIn("cannot be priced", reason)

    def test_a_market_order_with_a_mark_is_priced_and_checked(self):
        outcome = self.check(dict(TICKET, type="market", limit_price=None),
                             context=dict(CONTEXT, mark_price=150.0))
        self.assertTrue(self.rule(outcome, "max_notional")["passed"])

    def test_notional_returns_none_rather_than_zero(self):
        self.assertIsNone(guardrails.notional({"quantity": 10}))
        self.assertIsNone(guardrails.notional({"quantity": 0, "limit_price": 5}))
        self.assertEqual(guardrails.notional({"quantity": 10, "limit_price": 5}), 50.0)

    def test_an_unknown_portfolio_value_refuses_rather_than_passing(self):
        for equity in (None, 0, -1, "lots"):
            with self.subTest(equity=equity):
                outcome = self.check(context=dict(CONTEXT, portfolio_value=equity))
                self.assertFalse(self.rule(outcome, "max_portfolio_fraction")["passed"])

    def test_an_unknown_order_count_refuses_rather_than_passing(self):
        outcome = self.check(context=dict(CONTEXT, orders_today=None))
        self.assertFalse(self.rule(outcome, "max_orders_per_day")["passed"])


class HoursTests(_NeedsGuardrails):
    def test_a_market_order_outside_regular_hours_is_refused(self):
        outcome = self.check(dict(TICKET, type="market", limit_price=None),
                             context=dict(CONTEXT, market_time=CLOSED, mark_price=150.0))
        result = self.rule(outcome, "require_limit_outside_rth")
        self.assertFalse(result["passed"])
        self.assertIn("outside regular hours", result["reason"])

    def test_a_limit_order_is_acceptable_at_any_hour(self):
        # A limit order is exactly the instrument for trading outside them.
        outcome = self.check(context=dict(CONTEXT, market_time=CLOSED))
        self.assertTrue(self.rule(outcome, "require_limit_outside_rth")["passed"])

    def test_a_weekend_market_order_is_refused(self):
        saturday = datetime(2026, 9, 26, 12, 0)
        outcome = self.check(dict(TICKET, type="market", limit_price=None),
                             context=dict(CONTEXT, market_time=saturday, mark_price=150.0))
        self.assertFalse(self.rule(outcome, "require_limit_outside_rth")["passed"])

    def test_an_unknown_market_time_refuses_a_market_order(self):
        outcome = self.check(dict(TICKET, type="market", limit_price=None),
                             context=dict(CONTEXT, market_time=None, mark_price=150.0))
        self.assertFalse(self.rule(outcome, "require_limit_outside_rth")["passed"])


class ListAndChurnTests(_NeedsGuardrails):
    def test_an_allowlist_refuses_everything_not_on_it(self):
        config = dict(CONFIG, allowlist=["AAPL", "MSFT"])
        self.assertTrue(self.check(config=config)["passed"])
        outcome = self.check(dict(TICKET, symbol="TSLA"), config=config)
        self.assertFalse(self.rule(outcome, "symbol")["passed"])

    def test_the_denylist_wins_over_the_allowlist(self):
        # Being on both is a contradiction, and the safe reading of a
        # contradiction on an order ticket is no.
        config = dict(CONFIG, allowlist=["MEME"], denylist=["MEME"])
        outcome = self.check(dict(TICKET, symbol="MEME"), config=config)
        self.assertFalse(self.rule(outcome, "symbol")["passed"])
        self.assertIn("denylist", self.rule(outcome, "symbol")["reason"])

    def test_the_churn_guard_counts_per_symbol(self):
        context = dict(CONTEXT, trades_today_by_symbol={"AAPL": 2, "MSFT": 1})
        outcome = self.check(context=context)
        self.assertFalse(self.rule(outcome, "churn")["passed"])
        # ...and a different symbol is unaffected.
        self.assertTrue(self.rule(self.check(dict(TICKET, symbol="MSFT"),
                                             context=context), "churn")["passed"])


class ConfigTests(_NeedsGuardrails):
    def test_an_absent_config_file_is_empty_not_permissive(self):
        missing = Path(__file__).resolve().parent / "no-such-guardrails.json"
        self.assertEqual(guardrails.load(missing), {})

    def test_a_corrupt_config_file_is_empty_rather_than_raising(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "guardrails.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(guardrails.load(path), {})

    def test_the_digest_changes_with_a_limit_and_not_with_key_order(self):
        # What the kill switch keys its re-arm on.
        import killswitch
        base = killswitch.guardrails_digest(CONFIG)
        reordered = {k: CONFIG[k] for k in reversed(list(CONFIG))}
        self.assertEqual(killswitch.guardrails_digest(reordered), base)
        loosened = dict(CONFIG, max_notional=250000)
        self.assertNotEqual(killswitch.guardrails_digest(loosened), base)


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed - len(result.skipped)}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
