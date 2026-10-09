"""Controllable in-memory worker/provider fixtures; never execute external tools."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ResponsePlan:
    """Provider controls fixed before dispatch, using integer clock ticks."""
    delay: int = 0
    output: str = 'fixture output'
    drop_reply: bool = False
    cancel_confirmed: bool = True

    def __post_init__(self):
        if type(self.delay) is not int or self.delay < 0:
            raise ValueError('delay must be a non-negative integer')
        if not isinstance(self.output, str):
            raise ValueError('output must be text')
        if type(self.drop_reply) is not bool or type(self.cancel_confirmed) is not bool:
            raise ValueError('reply and cancellation controls must be boolean')


class FakeProvider:
    """Manual clock and explicit deliveries keep failure histories reproducible."""
    def __init__(self):
        self.now = 0
        self.available = True
        self.requests = {}
        self.pending = {}
        self.history = []

    def _record(self, kind, operation, **fields):
        self.history.append({'kind': kind, 'operation': operation, 'tick': self.now, **deepcopy(fields)})

    def submit(self, operation: str, input_text: str, plan: ResponsePlan,
               callback: Callable[[dict], None]):
        if not isinstance(operation, str) or not operation or not isinstance(input_text, str):
            raise ValueError('operation and input must be text; operation cannot be empty')
        if not isinstance(plan, ResponsePlan) or not callable(callback):
            raise ValueError('a response plan and callback are required')
        if operation in self.requests:
            raise ValueError('duplicate dispatch; reconcile the original operation')
        if not self.available:
            self._record('not_admitted', operation)
            return False
        self.requests[operation] = {'input': input_text, 'plan': plan, 'callback': callback,
                                    'due': self.now + plan.delay, 'state': 'running'}
        self._record('admitted', operation, input=input_text)
        return True

    def advance(self, ticks=1):
        if type(ticks) is not int or ticks < 0:
            raise ValueError('ticks must be a non-negative integer')
        self.now += ticks
        # Completion and delivery are separate controls: callers choose delivery order.
        for operation, request in self.requests.items():
            if request['state'] != 'running' or request['due'] > self.now:
                continue
            request['state'] = 'completed'
            self._record('completed', operation, output=request['plan'].output)
            if request['plan'].drop_reply:
                self._record('reply_lost', operation)
            else:
                self.pending[operation] = {'operation': operation, 'status': 'completed',
                                           'output': request['plan'].output}

    def deliver(self, operation):
        """Deliver exactly one queued callback, in the caller-selected order."""
        if operation not in self.pending:
            raise ValueError('no queued reply for operation')
        reply = self.pending.pop(operation)
        self._record('delivered', operation, status=reply['status'])
        self.requests[operation]['callback'](deepcopy(reply))

    def cancel(self, operation):
        request = self.requests[operation]
        self._record('cancel_requested', operation)
        if request['state'] != 'running' or not request['plan'].cancel_confirmed:
            self._record('cancel_unconfirmed', operation)
            return False
        request['state'] = 'cancelled'
        self.pending[operation] = {'operation': operation, 'status': 'cancelled', 'output': None}
        self._record('stop_confirmed', operation)
        return True

    def inspect(self, operation):
        """Explicit fixture observation; not an authenticated production lookup."""
        request = self.requests[operation]
        self._record('inspected', operation)
        return {'operation': operation, 'status': request['state'],
                'output': request['plan'].output if request['state'] == 'completed' else None}


class FakeWorker:
    """Observe provider replies without mistaking timeout for permission to retry."""
    def __init__(self, provider: FakeProvider):
        self.provider = provider
        self.operations = {}
        self.history = []

    def _record(self, kind, operation, **fields):
        self.history.append({'kind': kind, 'operation': operation,
                             'tick': self.provider.now, **deepcopy(fields)})

    def start(self, operation, input_text, plan, timeout=5):
        if type(timeout) is not int or timeout <= 0:
            raise ValueError('timeout must be a positive integer')
        if operation in self.operations:
            raise ValueError('duplicate operation; reconcile instead of dispatching again')
        admitted = self.provider.submit(operation, input_text, plan, self._receive)
        self.operations[operation] = {'status': 'running' if admitted else 'unavailable',
            'deadline': self.provider.now + timeout, 'output': None,
            'cancellationPending': False, 'admitted': admitted}
        self._record('started' if admitted else 'unavailable', operation)
        return self.snapshot(operation)

    def snapshot(self, operation):
        return deepcopy(self.operations[operation])

    def _receive(self, reply):
        operation = reply['operation']
        current = self.operations[operation]
        self._record('callback', operation, reply=reply)
        # Deadline expiry stays unknown even if poll_timeouts has not run yet.
        if (current['status'] != 'running' or current['cancellationPending']
                or self.provider.now >= current['deadline']):
            if current['status'] in ('running', 'cancel_requested'):
                current['status'] = 'unknown'
            self._record('late_observation', operation)
            return
        current.update(status=reply['status'], output=reply['output'])

    def poll_timeouts(self):
        for operation, current in self.operations.items():
            if current['status'] in ('running', 'cancel_requested') and self.provider.now >= current['deadline']:
                current['status'] = 'unknown'
                self._record('timeout', operation)

    def cancel(self, operation):
        current = self.operations[operation]
        if current['status'] not in ('running', 'unknown') or not current['admitted']:
            raise ValueError('operation cannot be cancelled')
        current.update(status='cancel_requested', cancellationPending=True)
        self._record('cancel_requested', operation)
        # Even a fixture stop observation needs explicit reconciliation.
        return self.provider.cancel(operation)

    def reconcile(self, operation):
        current = self.operations[operation]
        if not current['admitted']:
            raise ValueError('unavailable operation was never admitted')
        observed = self.provider.inspect(operation)
        self._record('reconciled_observation', operation, observed=observed)
        if current['cancellationPending']:
            if observed['status'] == 'cancelled':
                current.update(status='cancelled', output=None, cancellationPending=False)
            else:
                # A completed or running provider does not erase unresolved cancellation.
                current['status'] = 'unknown'
        else:
            current.update(status=observed['status'], output=observed['output'])
        return self.snapshot(operation)
