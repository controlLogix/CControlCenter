"""Ordered recovery fixtures; no in-memory result establishes durable ownership."""
import copy
from datetime import datetime
import json
from pathlib import Path
import unittest

import test_conformance as wire
from test_state_models import request


EARLY = '2026-10-09T12:01:00Z'
DEADLINE = '2026-10-09T12:05:00Z'
LATE = '2026-10-09T12:06:00Z'
RESERVE = ['expected_version_matches', 'executor_selected', 'grant_recorded', 'effect_intent_committed']
RESULT = ['executor_and_grant_match', 'repository_version_verified', 'artifact_bytes_verified', 'result_recorded']


class FixtureRejected(Exception):
    pass


class FixtureOwner:
    """Trusted test coordinator, not a deployable owner or authentication service."""
    def __init__(self, case, machine, state):
        self.case, self.machine, self.state = case, machine, state
        self.revision, self.pending = 0, False
        self.outcomes = {}
        self.transitions = 0

    def both(self, operations, accepted=True):
        rows = [client.many(operations) for client in self.case.clients]
        for replies in rows:
            for reply in replies:
                if accepted:
                    wire.Conformance.accepted(self.case, reply)
                else:
                    wire.Conformance.rejected(self.case, reply)
        if accepted:
            self.case.assertEqual(rows[0], rows[1])
            return [r['result'] for r in rows[0]]

    def digest(self, payload):
        return self.both([{'op': 'canonical', 'value': payload}])[0]['sha256']

    @staticmethod
    def admission(now, deadline, requester='owner', scope='project-one'):
        if requester != 'owner' or scope != 'project-one':
            raise FixtureRejected('current_authorization_denied')
        if datetime.fromisoformat(now) >= datetime.fromisoformat(deadline):
            raise FixtureRejected('deadline_expired')

    def submit(self, operation, event, role, guards, payload, *, expected=None,
               now=EARLY, deadline=DEADLINE, policy='allow', approval=False,
               requester='owner', scope='project-one'):
        self.admission(now, deadline, requester, scope)
        digest = self.digest(payload)
        binding = (self.machine, 'entity-one', 'hub-one', 'project-one', event, role, digest)
        value = request(self.machine, self.state, event, role, guards,
                        self.revision, self.pending, operation)
        value['intent']['payloadDigest'] = digest
        value['intent']['expectedRevision'] = self.revision if expected is None else expected
        if policy == 'hard_deny':
            # Human approval cannot manufacture the mandatory not-hard-denied proof.
            value['guards'].pop('not_hard_denied', None)
            self.both([{'op': 'evaluateTransition', 'request': value}], accepted=False)
            raise FixtureRejected('hard_denied')
        if policy == 'review_required' and not approval:
            raise FixtureRejected('review_required')
        if operation in self.outcomes:
            previous = self.outcomes[operation]
            if binding != previous['binding']:
                raise FixtureRejected('operation_conflict')
            return copy.deepcopy(previous['result'])
        result = self.both([{'op': 'evaluateTransition', 'request': value}])[0]
        self.state, self.revision, self.pending = result['state'], result['revision'], result['cancellationPending']
        self.transitions += 1
        self.outcomes[operation] = {'binding': binding, 'result': copy.deepcopy(result)}
        return result

    def rejected_transition(self, event, role, guards, expected=None):
        value = request(self.machine, self.state, event, role, guards,
                        self.revision, self.pending, 'rejected-operation')
        value['intent']['expectedRevision'] = self.revision if expected is None else expected
        value['intent']['payloadDigest'] = self.digest({'event': event})
        self.both([{'op': 'evaluateTransition', 'request': value}], accepted=False)

    def lookup(self, operation, payload, *, now, deadline, requester='owner', scope='project-one'):
        # This is a newly admitted lookup, not replay of an expired command credential.
        self.admission(now, deadline, requester, scope)
        digest = self.digest(payload)
        if operation not in self.outcomes:
            return {'status': 'unknown'}
        prior = self.outcomes[operation]
        if prior['binding'][-1] != digest:
            raise FixtureRejected('operation_conflict')
        return {'status': 'recorded', 'outcome': copy.deepcopy(prior['result'])}

    def transport_outcome(self, operation, non_admission=None):
        # A timeout says nothing about whether execution began. Only this fixture's
        # before-dispatch checkpoint can establish that no command was sent.
        unavailable = non_admission == {'operationId': operation, 'boundary': 'before-dispatch',
                                        'sent': False, 'evidenceRef': 'fixture:unsent-checkpoint'}
        if operation in self.outcomes:
            unavailable = False
        payload = {'operationId': operation, 'outcome': 'unavailable' if unavailable else 'unknown',
                   'recordRef': None, 'reason': 'Fixture observation only', 'retryable': unavailable}
        self.both([{'op': 'validate', 'schema': 'operation-outcome', 'value': payload}])
        return payload


class Recovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wire.Conformance.setUpClass.__func__(cls)

    def test_recovery_replay_and_authorized_late_lookup(self):
        owner = FixtureOwner(self, 'task', 'ready')
        payload = {'task': 'entity-one', 'executor': 'worker-one'}
        original = owner.submit('reserve-one', 'reserve', 'origin_owner', RESERVE, payload)
        self.assertEqual(owner.submit('reserve-one', 'reserve', 'origin_owner', RESERVE, payload), original)
        self.assertEqual((owner.state, owner.revision, owner.transitions), ('reserved', 1, 1))
        with self.assertRaisesRegex(FixtureRejected, 'current_authorization_denied'):
            owner.submit('reserve-one', 'reserve', 'origin_owner', RESERVE, payload, requester='revoked')
        with self.assertRaisesRegex(FixtureRejected, 'operation_conflict'):
            owner.submit('reserve-one', 'reserve', 'origin_owner', RESERVE, {'executor': 'other'})
        with self.assertRaisesRegex(FixtureRejected, 'deadline_expired'):
            owner.submit('reserve-two', 'reserve', 'origin_owner', RESERVE, payload, now=LATE)
        with self.assertRaisesRegex(FixtureRejected, 'deadline_expired'):
            owner.lookup('reserve-one', payload, now=LATE, deadline=DEADLINE)
        for kwargs in ({'requester': 'revoked'}, {'scope': 'foreign-project'}):
            with self.assertRaisesRegex(FixtureRejected, 'current_authorization_denied'):
                owner.lookup('reserve-one', payload, now=LATE, deadline='2026-10-09T12:07:00Z', **kwargs)
        lookup = owner.lookup('reserve-one', payload, now=LATE, deadline='2026-10-09T12:07:00Z')
        self.assertEqual(lookup, {'status': 'recorded', 'outcome': original})
        self.assertEqual((owner.state, owner.revision, owner.transitions), ('reserved', 1, 1))

    def test_recovery_reordered_stale_result_and_duplicate(self):
        owner = FixtureOwner(self, 'task', 'ready')
        owner.rejected_transition('result_received', 'origin_owner', RESULT)
        owner.submit('reserve-one', 'reserve', 'origin_owner', RESERVE, {'executor': 'worker-one'})
        owner.rejected_transition('result_received', 'origin_owner', RESULT, expected=0)
        owner.rejected_transition('timeout_reassign', 'origin_owner', [])
        result = owner.submit('result-one', 'result_received', 'origin_owner', RESULT, {'artifactDigest': 'synthetic-one'})
        self.assertEqual(owner.submit('result-one', 'result_received', 'origin_owner', RESULT, {'artifactDigest': 'synthetic-one'}), result)
        self.assertEqual((owner.state, owner.revision), ('review_pending', 2))
        owner.rejected_transition('accept', 'receiving_owner', ['acceptance_authorized', 'required_evidence_passed', 'task_version_matches'])
        accepted = owner.submit('accept-one', 'accept', 'origin_approver', ['acceptance_authorized', 'required_evidence_passed', 'task_version_matches'], {'review': 'verified'})
        self.assertEqual((accepted['state'], owner.transitions), ('accepted', 3))

    def test_recovery_cancellation_and_unknown_attempt(self):
        owner = FixtureOwner(self, 'attempt', 'running')
        owner.submit('cancel-one', 'cancel', 'execution_owner', ['cancellation_authorized', 'cancellation_intent_committed'], {'reason': 'user-request'})
        owner.submit('unknown-one', 'outcome_unknown', 'execution_owner', ['uncertainty_recorded'], {'transport': 'lost'})
        owner.rejected_transition('reconcile_running', 'execution_owner', ['same_attempt_verified', 'current_or_valid_offline_grant', 'no_pending_cancellation'])
        owner.rejected_transition('reconcile_terminal', 'execution_owner', ['same_attempt_verified', 'provider_receipt_recorded'])
        self.assertEqual((owner.state, owner.pending), ('effect_uncertain', True))
        owner.submit('cancel-rejoin', 'reconcile_cancel_pending', 'execution_owner', ['same_attempt_verified', 'cancellation_still_pending'], {'attempt': 'same'})
        end = owner.submit('stop-one', 'stop_confirmed', 'execution_owner', ['executor_stop_or_fence_verified', 'effects_reconciled', 'durable_result_intent'], {'stopEvidence': 'fixture-stop'})
        self.assertEqual((end['state'], end['cancellationPending'], owner.transitions), ('cancelled', False, 4))

    def test_recovery_approval_cannot_override_hard_denial(self):
        owner = FixtureOwner(self, 'delegation', 'approval_pending')
        guards = ['not_hard_denied', 'human_approval_valid', 'origin_reservation_and_grant_verified', 'receiver_acceptance_committed']
        with self.assertRaisesRegex(FixtureRejected, 'hard_denied'):
            owner.submit('approval-one', 'approve', 'receiving_approver', guards, {'approval': 'present'}, policy='hard_deny', approval=True)
        self.assertEqual((owner.state, owner.revision, owner.outcomes), ('approval_pending', 0, {}))
        with self.assertRaisesRegex(FixtureRejected, 'review_required'):
            owner.submit('approval-one', 'approve', 'receiving_approver', guards, {'approval': 'present'}, policy='review_required')
        result = owner.submit('approval-one', 'approve', 'receiving_approver', guards, {'approval': 'present'}, policy='review_required', approval=True)
        self.assertEqual(result['state'], 'accepted_reserved')

    def test_recovery_signed_deadline_and_unknown_outcome_payloads(self):
        examples = json.loads((Path(__file__).parent / 'vectors/payload-examples.json').read_text())
        owner = FixtureOwner(self, 'task', 'ready')
        envelope = copy.deepcopy(self.examples['message-envelope'])
        envelope.update(contractId='task-reserve', destinationServiceId='task-owner', payload=examples['task-reserve']['payload'])
        envelope['operation'].update(payloadDigest=owner.digest(envelope['payload']), taskId='task-one', attemptId='attempt-one',
                                     delegationRef={'id': 'delegation-one', 'ownerHubId': 'hub-origin', 'revision': 1})
        claims = envelope['ingressAttestation']['claims']
        for field in ('operation', 'messageId', 'kind', 'contractId', 'contractMajor', 'sourceHubId', 'sourceInstanceId', 'sentAt', 'correlationId'):
            claims[field] = copy.deepcopy(envelope[field])
        claims['audience'] = {'hubId': envelope['destinationHubId'], 'serviceId': envelope['destinationServiceId']}
        signatures = owner.both([{'op': 'sign', 'claims': claims, 'seedHex': self.seed}])[0]
        envelope['ingressAttestation']['signature'] = signatures
        query = {'op': 'verifyEnvelope', 'envelope': envelope, 'publicKeyHex': self.public, 'expectedAudience': claims['audience'], 'now': EARLY}
        owner.both([query])
        expired = copy.deepcopy(query); expired['now'] = claims['expiresAt']
        owner.both([expired], accepted=False)
        # Schema rejects pretending unknown/unavailable names an accepted record.
        for status in ('unknown', 'unavailable'):
            value = copy.deepcopy(examples['operation-outcome']['payload'])
            value['outcome'] = status
            owner.both([{'op': 'validate', 'schema': 'operation-outcome', 'value': value}], accepted=False)

    def test_recovery_unavailable_requires_observed_non_admission(self):
        owner = FixtureOwner(self, 'task', 'ready')
        self.assertEqual(owner.transport_outcome('lost-request')['outcome'], 'unknown')
        self.assertFalse(owner.transport_outcome('lost-request')['retryable'])
        proof = {'operationId': 'unsent-request', 'boundary': 'before-dispatch',
                 'sent': False, 'evidenceRef': 'fixture:unsent-checkpoint'}
        unavailable = owner.transport_outcome('unsent-request', proof)
        self.assertEqual((unavailable['outcome'], unavailable['retryable']), ('unavailable', True))
        altered = dict(proof, sent=True)
        self.assertEqual(owner.transport_outcome('unsent-request', altered)['outcome'], 'unknown')
        owner.submit('unsent-request', 'reserve', 'origin_owner', RESERVE, {'executor': 'worker-one'})
        self.assertEqual(owner.transport_outcome('unsent-request', proof)['outcome'], 'unknown')
        self.assertEqual((owner.state, owner.revision, owner.transitions), ('reserved', 1, 1))
