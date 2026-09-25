"""Single-use, expiring authorisations for one exact write.

THE PROPERTY THIS EXISTS FOR. The write route does not say what to write. It
says which ticket to redeem, and the ticket carries the target and the value,
fixed at the moment it was minted. So a request that is replayed, guessed or
reused can only redo a write that was already authorised, and only once.

That is the difference between "the caller is allowed to write" and "this
write is allowed", and it is the whole reason field/app.py had no write route
until this existed. A write route that predates its ticket is a write route
with no gate, and gates are not added afterwards - by then something is already
calling it the old way.

WHY THE PARAMETERS LIVE ON THE TICKET AND NOT IN THE REQUEST. If the request
carried them, the thing that was reviewed and the thing that executes would be
two separate objects that merely look alike, and every confirmation UI would be
rendering a claim rather than the write. Minting returns an id for parameters
the server already holds; redeeming hands those exact parameters back. Nothing
in between can alter them, because there is no in between.

IN MEMORY ONLY, DELIBERATELY. A ticket that survived a restart would be an
authorisation that outlived the thing that authorised it, and the operator who
approved it is not necessarily still at the desk. Restarting the sidecar
invalidates every outstanding ticket, which is the correct blast radius.

WHAT THIS IS NOT. It is not authentication - the shared secret does that, at
the door, before a body is read. It is not a confirmation UI. It is the record
that one specific write was authorised, once, and has not been used yet.
"""

import secrets
import threading
import time

DEFAULT_TTL = 120.0        # seconds; long enough to read a card, short enough to matter
MAX_OUTSTANDING = 64       # a local tool; more than this means something is looping


class TicketError(Exception):
    """A ticket could not be redeemed. The message says which of the reasons."""


class Ticket:
    """One authorised write. `action` is returned to the redeemer verbatim."""

    __slots__ = ('id', 'action', 'minted_at', 'expires_at', 'redeemed_at', 'redeemed_by')

    def __init__(self, action, ttl):
        # secrets, not uuid4: this is a bearer value, and the module that says
        # so in its name is the one to reach for.
        self.id = secrets.token_hex(16)
        self.action = action
        self.minted_at = time.time()
        self.expires_at = self.minted_at + ttl
        self.redeemed_at = None
        self.redeemed_by = None

    def expired(self, now=None):
        return (now if now is not None else time.time()) >= self.expires_at

    def summary(self):
        """What is safe and useful to hand back to a caller."""
        return {
            'ticket_id': self.id,
            'action': dict(self.action),
            'minted_at': self.minted_at,
            'expires_at': self.expires_at,
            'expires_in': max(0.0, self.expires_at - time.time()),
            'redeemed': self.redeemed_at is not None,
        }


class TicketStore:
    """Mint and redeem write authorisations. Thread-safe; the server is threaded."""

    def __init__(self, ttl=DEFAULT_TTL, max_outstanding=MAX_OUTSTANDING):
        if not isinstance(ttl, (int, float)) or ttl <= 0:
            raise ValueError('ttl must be a positive number of seconds')
        self.ttl = float(ttl)
        self.max_outstanding = int(max_outstanding)
        self._lock = threading.Lock()
        self._tickets = {}

    # ── minting ──────────────────────────────────────────────────────────────
    def mint(self, action, *, ttl=None):
        """Authorise one write. `action` must be a dict and is copied.

        Copied, because a caller that kept a reference could change the target
        after minting - and the ticket would then authorise something nobody
        looked at.
        """
        if not isinstance(action, dict) or not action:
            raise ValueError('a ticket needs an action describing the write')
        with self._lock:
            self._sweep_locked()
            if len(self._tickets) >= self.max_outstanding:
                # Refuse rather than evict. Evicting the oldest would silently
                # invalidate a ticket somebody is about to confirm, and the
                # write would fail at the least explicable moment.
                raise TicketError(
                    f'{len(self._tickets)} tickets are already outstanding; '
                    f'something is minting and not redeeming')
            ticket = Ticket(dict(action), ttl if ttl is not None else self.ttl)
            self._tickets[ticket.id] = ticket
            return ticket

    # ── redeeming ────────────────────────────────────────────────────────────
    def redeem(self, ticket_id, *, actor):
        """Consume a ticket and return its action. Raises TicketError otherwise.

        The reasons are distinguished on purpose. This is a loopback sidecar on
        one operator's machine, not a public endpoint: "that ticket expired" and
        "there is no such ticket" lead to different next actions, and collapsing
        them to be uninformative would only be uninformative to the operator.
        """
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('redeeming a ticket requires a named actor')
        if not isinstance(ticket_id, str) or not ticket_id:
            raise TicketError('no ticket id was given')
        with self._lock:
            self._sweep_locked()
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                raise TicketError('no such ticket; it may have expired or already been used')
            if ticket.redeemed_at is not None:
                raise TicketError('that ticket has already been used')
            if ticket.expired():
                raise TicketError('that ticket has expired; mint a new one and look again')
            ticket.redeemed_at = time.time()
            ticket.redeemed_by = actor
            # Removed on redemption, so "already used" is only reachable in the
            # same instant by two threads - and one of them will lose.
            self._tickets.pop(ticket_id, None)
            return dict(ticket.action)

    # ── housekeeping ─────────────────────────────────────────────────────────
    def peek(self, ticket_id):
        """What a ticket authorises, without consuming it. None if unknown."""
        with self._lock:
            self._sweep_locked()
            ticket = self._tickets.get(ticket_id)
            return ticket.summary() if ticket is not None else None

    def outstanding(self):
        with self._lock:
            self._sweep_locked()
            return [t.summary() for t in self._tickets.values()]

    def _sweep_locked(self):
        now = time.time()
        for key in [k for k, t in self._tickets.items() if t.expired(now)]:
            del self._tickets[key]
