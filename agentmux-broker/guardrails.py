"""Server-side limits on an order. Configured in a file, never from the page.

WHERE THESE LIVE AND WHY. In a file the operator edits, read by the process that
submits. NOT in the request, and not adjustable from the blade - a limit the
caller can raise is not a limit, it is a default. The one place a guardrail
change is allowed to take effect is on disk, and changing it re-arms the kill
switch, because the rules you agreed to are part of what you agreed to.

EVERY RULE RUNS. No short-circuit on the first failure, because an operator who
fixes one violation and resubmits into a second has been told half the truth
twice. `evaluate()` returns every result, passed and failed, and the UI renders
the lot.

EVERY FAILURE CARRIES A REASON IN PLAIN LANGUAGE, with the number that broke it
and the number it broke. "max_notional" is not a reason; "$52,000 exceeds the
$25,000 per-order limit" is. A refusal a person cannot act on is a refusal they
will route around.

WHAT THESE ARE NOT. They are not a strategy, not risk management, and not a
substitute for reading the ticket. They are the fence at the top of the cliff
for the mistakes that are mechanical: a fat-fingered quantity, a symbol nobody
meant to trade, the twelfth order of a day that was supposed to have three, a
market order into a closed session. Every one of those is a thing software can
check and a tired person cannot.

MISSING LIMITS ARE ABSENT, NOT INFINITE. A config with no `max_notional` does
not mean "any size" - it means that rule does not apply, and `evaluate()` says
so in the result rather than silently passing. The distinction matters when
somebody deletes a line and expects to be told.
"""

import json
import math
import re
from datetime import datetime, time as dtime

# A ticket is refused outright if it is not one. These are not guardrails, they
# are the shape of the thing being guarded.
SIDES = ("buy", "sell")
ORDER_TYPES = ("market", "limit")
SYMBOL_RE = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")

# US regular trading hours, Eastern. Used only to decide whether a MARKET order
# is allowed - never to block a limit order, which is exactly the instrument for
# trading outside them.
RTH_OPEN = dtime(9, 30)
RTH_CLOSE = dtime(16, 0)


class Result:
    """One rule's verdict. `applies` is False when the config does not set it."""

    __slots__ = ("rule", "passed", "applies", "reason")

    def __init__(self, rule, passed, reason, applies=True):
        self.rule, self.passed, self.reason, self.applies = rule, passed, reason, applies

    def as_dict(self):
        return {"rule": self.rule, "passed": self.passed,
                "applies": self.applies, "reason": self.reason}

    def __repr__(self):
        mark = "ok" if self.passed else "REFUSED"
        return f"<{mark} {self.rule}: {self.reason}>"


def _money(value):
    return f"${value:,.2f}"


def validate_ticket(ticket):
    """Is this even an order? Returns a list of problems, empty when it is.

    Separate from the guardrails: a malformed ticket is not a risk decision, and
    running limit checks against a quantity of "ten" would produce nonsense
    reasons that read like limits.
    """
    problems = []
    if not isinstance(ticket, dict):
        return ["the ticket is not an object"]

    symbol = ticket.get("symbol")
    if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol):
        problems.append(f"symbol {symbol!r} is not a plausible ticker")

    if ticket.get("side") not in SIDES:
        problems.append(f"side must be one of {list(SIDES)}")

    order_type = ticket.get("type")
    if order_type not in ORDER_TYPES:
        problems.append(f"type must be one of {list(ORDER_TYPES)}")

    qty = ticket.get("quantity")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        problems.append("quantity must be a positive whole number of shares")

    price = ticket.get("limit_price")
    if order_type == "limit":
        if not isinstance(price, (int, float)) or isinstance(price, bool) \
                or not math.isfinite(price) or price <= 0:
            problems.append("a limit order needs a finite positive limit_price")
    elif price is not None:
        # A market order carrying a price is ambiguous about which it is, and
        # ambiguity on an order ticket is not something to resolve for someone.
        problems.append("a market order must not carry a limit_price")

    return problems


def notional(ticket, *, mark_price=None):
    """What this order is worth, and None when that cannot be known.

    A market order has no price on the ticket, so its notional depends on a mark
    that may not be available. None is returned rather than zero, because zero
    would pass every size limit - a missing number must never read as a small
    one.
    """
    qty = ticket.get("quantity")
    if not isinstance(qty, int) or qty <= 0:
        return None
    price = ticket.get("limit_price")
    if not isinstance(price, (int, float)) or price <= 0:
        price = mark_price
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    return float(qty) * float(price)


# ── the rules ────────────────────────────────────────────────────────────────

def _max_notional(ticket, config, context):
    limit = config.get("max_notional")
    if limit is None:
        return Result("max_notional", True, "no per-order size limit is configured",
                      applies=False)
    value = notional(ticket, mark_price=context.get("mark_price"))
    if value is None:
        # Cannot price it, so cannot clear it. Refusing is the only safe answer:
        # passing would mean an unpriced market order skips the size limit
        # entirely, which is the exact order most likely to surprise someone.
        return Result("max_notional", False,
                      "this order cannot be priced, so its size cannot be checked "
                      "against the " + _money(limit) + " limit; supply a limit price "
                      "or a mark")
    if value > limit:
        return Result("max_notional", False,
                      f"{_money(value)} exceeds the {_money(limit)} per-order limit")
    return Result("max_notional", True, f"{_money(value)} is within {_money(limit)}")


def _max_portfolio_fraction(ticket, config, context):
    limit = config.get("max_portfolio_fraction")
    if limit is None:
        return Result("max_portfolio_fraction", True,
                      "no portfolio-fraction limit is configured", applies=False)
    equity = context.get("portfolio_value")
    if not isinstance(equity, (int, float)) or equity <= 0:
        return Result("max_portfolio_fraction", False,
                      "the portfolio value is unknown, so this order's share of it "
                      "cannot be checked")
    value = notional(ticket, mark_price=context.get("mark_price"))
    if value is None:
        return Result("max_portfolio_fraction", False,
                      "this order cannot be priced, so its share of the portfolio "
                      "cannot be checked")
    fraction = value / float(equity)
    if fraction > limit:
        return Result("max_portfolio_fraction", False,
                      f"{fraction:.1%} of the portfolio exceeds the {limit:.0%} limit "
                      f"({_money(value)} of {_money(equity)})")
    return Result("max_portfolio_fraction", True,
                  f"{fraction:.1%} of the portfolio is within {limit:.0%}")


def _max_orders_per_day(ticket, config, context):
    limit = config.get("max_orders_per_day")
    if limit is None:
        return Result("max_orders_per_day", True,
                      "no daily order count limit is configured", applies=False)
    placed = context.get("orders_today")
    if not isinstance(placed, int) or placed < 0:
        return Result("max_orders_per_day", False,
                      "how many orders have been placed today is unknown, so the "
                      "daily limit cannot be checked")
    if placed >= limit:
        return Result("max_orders_per_day", False,
                      f"{placed} orders have been placed today, at the limit of {limit}")
    return Result("max_orders_per_day", True,
                  f"{placed} of {limit} orders placed today")


def _symbol_allowed(ticket, config, context):
    allow = config.get("allowlist")
    deny = config.get("denylist") or []
    symbol = str(ticket.get("symbol") or "")
    if symbol in deny:
        return Result("symbol", False, f"{symbol} is on the denylist")
    if allow:
        if symbol not in allow:
            return Result("symbol", False,
                          f"{symbol} is not on the allowlist "
                          f"({len(allow)} symbol(s) permitted)")
        return Result("symbol", True, f"{symbol} is on the allowlist")
    if deny:
        return Result("symbol", True, f"{symbol} is not on the denylist")
    return Result("symbol", True, "no allowlist or denylist is configured",
                  applies=False)


def _limit_required_outside_rth(ticket, config, context):
    if not config.get("require_limit_outside_rth"):
        return Result("require_limit_outside_rth", True,
                      "market orders outside regular hours are not restricted",
                      applies=False)
    if ticket.get("type") == "limit":
        return Result("require_limit_outside_rth", True,
                      "a limit order is acceptable at any hour")
    when = context.get("market_time")
    if not isinstance(when, datetime):
        return Result("require_limit_outside_rth", False,
                      "the market time is unknown, so a market order cannot be "
                      "cleared as inside regular hours")
    if when.weekday() >= 5 or not (RTH_OPEN <= when.time() < RTH_CLOSE):
        # A market order into a thin book is how a fat finger becomes a fill at
        # a price nobody would have typed.
        return Result("require_limit_outside_rth", False,
                      f"a market order at {when:%a %H:%M} is outside regular hours; "
                      "use a limit order")
    return Result("require_limit_outside_rth", True,
                  f"{when:%H:%M} is inside regular hours")


def _churn(ticket, config, context):
    limit = config.get("max_trades_per_symbol_per_day")
    if limit is None:
        return Result("churn", True, "no per-symbol daily limit is configured",
                      applies=False)
    symbol = str(ticket.get("symbol") or "")
    counts = context.get("trades_today_by_symbol") or {}
    placed = counts.get(symbol, 0)
    if not isinstance(placed, int) or placed < 0:
        return Result("churn", False,
                      f"how often {symbol} has been traded today is unknown")
    if placed >= limit:
        return Result("churn", False,
                      f"{symbol} has been traded {placed} time(s) today, at the "
                      f"limit of {limit}")
    return Result("churn", True, f"{symbol} traded {placed} of {limit} times today")


RULES = (
    _max_notional,
    _max_portfolio_fraction,
    _max_orders_per_day,
    _symbol_allowed,
    _limit_required_outside_rth,
    _churn,
)


def evaluate(ticket, *, config=None, context=None):
    """Run every rule. Returns {'passed': bool, 'results': [...], 'refusals': [...]}.

    Every rule runs even after one fails, because an operator who fixes one
    violation and resubmits into a second has been told half the truth twice.
    """
    config = config or {}
    context = context or {}

    problems = validate_ticket(ticket)
    if problems:
        # A malformed ticket is refused BEFORE the limits, so the reasons read
        # as "this is not an order" rather than as a risk decision.
        return {
            "passed": False,
            "malformed": problems,
            "results": [],
            "refusals": [f"the ticket is not a valid order: {p}" for p in problems],
        }

    results = [rule(ticket, config, context) for rule in RULES]
    refusals = [r.reason for r in results if not r.passed]
    return {
        "passed": not refusals,
        "malformed": [],
        "results": [r.as_dict() for r in results],
        "refusals": refusals,
    }


def load(path):
    """Read the config file. Returns {} when absent - and that is not permissive.

    An absent config means no LIMITS are configured, which `evaluate()` reports
    per rule with applies=False. It does not mean approval: the kill switch is a
    separate gate and is armed by default, so a broker with no guardrail file
    submits nothing.
    """
    try:
        text = path.read_text(encoding="utf-8") if hasattr(path, "read_text") \
            else open(path, encoding="utf-8").read()
        config = json.loads(text)
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}
