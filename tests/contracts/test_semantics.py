"""Retain P00 semantic rejection vectors against the promoted independent SDKs."""
import copy
import json
from pathlib import Path
import unittest

import test_conformance as wire


class Semantics(unittest.TestCase):
    def test_p00_semantic_rejections_remain_enforced(self):
        examples = json.loads(wire.VECTORS.read_text())
        fixtures = json.loads((Path(__file__).parent / 'vectors/semantic-examples.json').read_text())
        cases = []
        for fixture in fixtures:
            value = copy.deepcopy(examples[fixture['schema']])
            parent = value
            for key in fixture['path'][:-1]:
                parent = parent[key]
            if fixture.get('remove'):
                del parent[fixture['path'][-1]]
            else:
                parent[fixture['path'][-1]] = copy.deepcopy(fixture['value'])
            cases.append((fixture['id'], {'op': 'validate', 'schema': fixture['schema'], 'value': value}))
        self.assertEqual(len(cases), 21, 'Review fixture coverage when the accepted semantic catalog changes')
        for client in (wire.Client('python'), wire.Client('typescript')):
            for (label, _), response in zip(cases, client.many([request for _, request in cases])):
                with self.subTest(client=client.language, fixture=label):
                    wire.Conformance.rejected(self, response)

    def test_identity_uniqueness_and_self_dependency(self):
        examples = json.loads(wire.VECTORS.read_text())
        cases = []
        value = copy.deepcopy(examples['plugin-manifest'])
        value['dependencies'] = [{'packageId': value['packageId'], 'minimumVersion': '1.0.0',
                                  'exclusiveMaximumVersion': '2.0.0', 'optional': False}]
        cases.append(('self-dependency', 'plugin-manifest', value))
        value = copy.deepcopy(examples['plugin-manifest'])
        duplicate = copy.deepcopy(value['contributions'][0]); duplicate['contractRef'] = 'contracts/other.json'
        value['contributions'].append(duplicate)
        cases.append(('duplicate-contribution-id-distinct-object', 'plugin-manifest', value))
        value = copy.deepcopy(examples['owner-record'])
        duplicate = copy.deepcopy(value['effects'][0]); duplicate['payload'] = {'different': True}
        value['effects'].append(duplicate)
        cases.append(('duplicate-effect-id-distinct-object', 'owner-record', value))
        for client in (wire.Client('python'), wire.Client('typescript')):
            for (label, _, _), response in zip(cases, client.many([{'op': 'validate', 'schema': schema, 'value': value} for _, schema, value in cases])):
                with self.subTest(client=client.language, fixture=label):
                    wire.Conformance.rejected(self, response)


if __name__ == '__main__':
    unittest.main()
