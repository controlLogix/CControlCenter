"""Independent contract-oracle checks; fixture evidence is not production authority."""
import copy
import json
import unittest

import test_conformance as wire


DRAFT = wire.ROOT / 'docs/planning/2026-10-09/delivery/contracts'


def request(machine, state, event, role, guards, revision=3, pending=False, operation='operation-one'):
    return {
        'schemaVersion': '1.0.0', 'machine': machine,
        'ownerSnapshot': {'entityId': 'entity-one', 'ownerHubId': 'hub-one', 'scopeId': 'project-one',
                          'state': state, 'revision': revision, 'cancellationPending': pending},
        'intent': {'entityId': 'entity-one', 'expectedRevision': revision, 'event': event,
                   'operationId': operation, 'payloadDigest': 'sha256:' + '1' * 64},
        'authority': {'entityId': 'entity-one', 'ownerHubId': 'hub-one', 'scopeId': 'project-one',
                      'actorRole': role, 'evidenceRefs': ['fixture:resolved-authority']},
        'guards': {name: 'fixture:evidence:' + name for name in guards},
    }


class StateModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machines = json.loads((DRAFT / 'state-machines.json').read_text())['machines']
        cls.clients = [wire.Client('python'), wire.Client('typescript')]

    def check_cases(self, cases):
        for client in self.clients:
            answers = client.many([{'op': 'evaluateTransition', 'request': value} for _, value, _ in cases])
            for (label, value, expected), answer in zip(cases, answers):
                with self.subTest(client=client.language, case=label):
                    if expected is None:
                        wire.Conformance.rejected(self, answer)
                    else:
                        actual = wire.Conformance.accepted(self, answer)
                        self.assertEqual(actual['state'], expected)
                        self.assertEqual(actual['previousRevision'], value['ownerSnapshot']['revision'])
                        self.assertEqual(actual['revision'], value['ownerSnapshot']['revision'] + 1)
                        self.assertEqual(actual['operationId'], value['intent']['operationId'])
                        self.assertEqual(actual['entityId'], value['ownerSnapshot']['entityId'])
                        self.assertEqual(actual['payloadDigest'], value['intent']['payloadDigest'])
                        self.assertEqual(actual['cancellationPending'], False if expected == 'cancelled' else
                                         value['ownerSnapshot']['cancellationPending'] or expected == 'cancel_requested')

    def test_all_accepted_draft_edges_and_each_missing_guard(self):
        cases = []
        count = 0
        for name, model in self.machines.items():
            for edge in model['transitions']:
                label = name + ':' + edge['from'] + ':' + edge['event']
                pending = edge['from'] == 'cancel_requested' or 'cancellation_still_pending' in edge['requires']
                value = request(name, edge['from'], edge['event'], edge['actorRole'], edge['requires'], pending=pending)
                cases.append((label, value, edge['to']))
                count += 1
                for guard in edge['requires']:
                    missing = copy.deepcopy(value); del missing['guards'][guard]
                    cases.append((label + ':missing:' + guard, missing, None))
                wrong_role = copy.deepcopy(value); wrong_role['authority']['actorRole'] = 'provider'
                cases.append((label + ':wrong-authority', wrong_role, None))
                stale = copy.deepcopy(value); stale['intent']['expectedRevision'] -= 1
                cases.append((label + ':stale-revision', stale, None))
        self.assertEqual(count, 68)
        self.check_cases(cases)

    def test_preserved_p00_model_examples(self):
        cases = []
        for fixture in json.loads((DRAFT / 'model-examples.json').read_text()):
            pending = fixture['from'] == 'cancel_requested' or 'cancellation_still_pending' in fixture['guards']
            value = request(fixture['machine'], fixture['from'], fixture['event'], fixture['actorRole'], fixture['guards'], pending=pending)
            cases.append((fixture['id'], value, fixture.get('expectedTo') if fixture['allowed'] else None))
        self.check_cases(cases)

    def test_closed_input_and_owner_binding(self):
        value = request('task', 'ready', 'reserve', 'origin_owner',
                        ['expected_version_matches', 'executor_selected', 'grant_recorded', 'effect_intent_committed'])
        cases = []
        for section in ('ownerSnapshot', 'intent', 'authority'):
            invalid = copy.deepcopy(value); invalid[section]['entityId'] = 'wrong-entity'
            cases.append((section + ':wrong-entity', invalid, None))
        for key in ('ownerHubId', 'scopeId'):
            invalid = copy.deepcopy(value); invalid['authority'][key] = 'wrong-owner'
            cases.append((key + ':wrong-owner', invalid, None))
        for section in (None, 'ownerSnapshot', 'intent', 'authority'):
            invalid = copy.deepcopy(value); (invalid if section is None else invalid[section])['extra'] = True
            cases.append((str(section) + ':unknown-field', invalid, None))
        for invalid_revision in (-1, 1.5, True, 9007199254740991):
            invalid = copy.deepcopy(value)
            invalid['ownerSnapshot']['revision'] = invalid['intent']['expectedRevision'] = invalid_revision
            cases.append(('invalid-revision:' + str(invalid_revision), invalid, None))
        for refs in ([], [''], ['same', 'same'], [True]):
            invalid = copy.deepcopy(value); invalid['authority']['evidenceRefs'] = refs
            cases.append(('invalid-authority-evidence:' + str(refs), invalid, None))
        for evidence in ('', '   ', True, ['proof']):
            invalid = copy.deepcopy(value); invalid['guards']['grant_recorded'] = evidence
            cases.append(('invalid-guard-evidence:' + str(evidence), invalid, None))
        for field, bad in [('schemaVersion', '2.0.0'), ('machine', 'unknown')]:
            invalid = copy.deepcopy(value); invalid[field] = bad
            cases.append(('unsupported:' + field, invalid, None))
        self.check_cases(cases)

    def test_ordered_reservation_result_and_origin_acceptance(self):
        # Literal expected history is independent of the promoted transition table.
        history = [
            ('ready', 'reserve', 'origin_owner', ['expected_version_matches', 'executor_selected', 'grant_recorded', 'effect_intent_committed'], 'reserved'),
            ('reserved', 'link_lost', 'origin_owner', ['observation_recorded'], 'reserved'),
            ('reserved', 'provider_done', 'execution_owner', ['provider_receipt_recorded'], None),
            ('reserved', 'timeout_reassign', 'origin_owner', [], None),
            ('reserved', 'result_received', 'origin_owner', ['executor_and_grant_match', 'repository_version_verified', 'artifact_bytes_verified', 'result_recorded'], 'review_pending'),
            ('review_pending', 'accept', 'receiving_owner', ['acceptance_authorized', 'required_evidence_passed', 'task_version_matches'], None),
            ('review_pending', 'accept', 'origin_approver', ['acceptance_authorized', 'required_evidence_passed', 'task_version_matches'], 'accepted'),
        ]
        revision = 1
        cases = []
        for index, (state, event, actor, guards, expected) in enumerate(history):
            cases.append((str(index) + ':' + event, request('task', state, event, actor, guards, revision, operation='history-' + str(index)), expected))
            revision += expected is not None
        self.check_cases(cases)

    def test_pending_cancellation_survives_uncertain_execution(self):
        cases = [
            ('cancel', request('attempt', 'running', 'cancel', 'execution_owner', ['cancellation_authorized', 'cancellation_intent_committed']), 'cancel_requested'),
            ('unknown', request('attempt', 'cancel_requested', 'outcome_unknown', 'execution_owner', ['uncertainty_recorded'], 4, True), 'effect_uncertain'),
            ('cannot-resume', request('attempt', 'effect_uncertain', 'reconcile_running', 'execution_owner', ['same_attempt_verified', 'current_or_valid_offline_grant', 'no_pending_cancellation'], 5, True), None),
            ('cannot-drop-cancel-on-terminal', request('attempt', 'effect_uncertain', 'reconcile_terminal', 'execution_owner', ['same_attempt_verified', 'provider_receipt_recorded'], 5, True), None),
            ('reconcile-cancel', request('attempt', 'effect_uncertain', 'reconcile_cancel_pending', 'execution_owner', ['same_attempt_verified', 'cancellation_still_pending'], 5, True), 'cancel_requested'),
            ('stop-proved', request('attempt', 'cancel_requested', 'stop_confirmed', 'execution_owner', ['executor_stop_or_fence_verified', 'effects_reconciled', 'durable_result_intent'], 6, True), 'cancelled'),
            ('late-task-result', request('task', 'cancel_requested', 'result_received', 'origin_owner', ['executor_and_grant_match', 'result_recorded', 'cancellation_still_pending'], 8, True), 'cancel_requested'),
            ('late-task-cannot-accept', request('task', 'cancel_requested', 'accept', 'origin_approver', ['acceptance_authorized', 'required_evidence_passed', 'task_version_matches'], 9, True), None),
        ]
        self.check_cases(cases)

    def test_delivery_receipts_do_not_advance_work(self):
        cases = []
        for machine, state in [('task', 'reserved'), ('attempt', 'running'), ('delegation', 'executing')]:
            for event in ('received', 'redelivered', 'delivery_receipt'):
                cases.append((machine + ':' + event, request(machine, state, event, 'origin_owner', []), None))
        self.check_cases(cases)

    def test_json_integer_and_unicode_reference_boundaries(self):
        value = request('task', 'ready', 'reserve', 'origin_owner',
                        ['expected_version_matches', 'executor_selected', 'grant_recorded', 'effect_intent_committed'], 3.0)
        value['authority']['evidenceRefs'] = ['\U0001f600' * 300]
        value['guards']['grant_recorded'] = '\U0001f600' * 512
        too_long = copy.deepcopy(value)
        too_long['guards']['grant_recorded'] += '\U0001f600'
        long_authority = copy.deepcopy(value)
        long_authority['authority']['evidenceRefs'] = ['a' * 513]
        cases = [('integer-valued-json-and-codepoints', value, 'reserved'),
                 ('guard-over-codepoint-limit', too_long, None),
                 ('authority-over-codepoint-limit', long_authority, None)]
        for blank in ('\u0085', '\ufeff', '\u001c', '\u2003'):
            invalid = copy.deepcopy(value); invalid['authority']['evidenceRefs'] = [blank]
            cases.append(('blank-codepoint-' + str(ord(blank)), invalid, None))
        self.check_cases(cases)

    def test_reconciliation_records_newly_discovered_cancellation(self):
        value = request('attempt', 'effect_uncertain', 'reconcile_cancel_pending', 'execution_owner',
                        ['same_attempt_verified', 'cancellation_still_pending'], 5, False)
        self.check_cases([('resolved-new-cancellation', value, 'cancel_requested')])


if __name__ == '__main__':
    unittest.main()
