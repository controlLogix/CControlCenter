"""Check P00 draft shapes and model examples, not runtime authorization or delivery."""
import copy
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def semantic_errors(name, value):
    errors = []
    if name == 'protected-assembly':
        if {p['id'] for p in value['plugins']} != {'boot', 'kernel-lifecycle', 'internal-communication', 'exported-status'}:
            errors.append('protected_membership')
    if name == 'plugin-context':
        grant = value['effectiveGrant']
        if value['parent'] and value['parent']['instanceId'] == value['instanceId']:
            errors.append('self_parent')
        if value['parent'] and value['parent']['relationship'] == 'private' and grant['parentGrantRef'] is None:
            errors.append('private_parent_grant_required')
        if grant['subjectInstanceId'] != value['instanceId']:
            errors.append('grant_instance_binding')
        try:
            if datetime.fromisoformat(grant['issuedAt']) >= datetime.fromisoformat(grant['expiresAt']):
                errors.append('grant_interval')
        except ValueError:
            errors.append('calendar_date')
    if name == 'plugin-manifest':
        for collection, key in [('dependencies', 'packageId'), ('children', 'packageId'), ('contributions', 'id')]:
            ids = [item[key] for item in value[collection]]
            if len(ids) != len(set(ids)):
                errors.append('duplicate_' + collection)
        if any(item['packageId'] == value['packageId'] for item in value['children'] + value['dependencies']):
            errors.append('self_dependency')
        for capability in value['requestedCapabilities']:
            if capability['resourceClass'].startswith('kernel') and (capability['resourceClass'], capability['action']) != ('kernel-status', 'subscribe'):
                errors.append('protected_kernel_access')
        for dep in value['dependencies']:
            low = tuple(map(int, dep['minimumVersion'].split('.')))
            high = tuple(map(int, dep['exclusiveMaximumVersion'].split('.')))
            if low >= high:
                errors.append('dependency_interval')
    if name in ('message-envelope', 'owner-record'):
        errors.extend(semantic_errors('operation-context', value['operation']))
    if name == 'owner-record':
        ids = [effect['effectId'] for effect in value['effects']]
        if len(ids) != len(set(ids)):
            errors.append('duplicate_effect_identity')
        if value['outcome'] == 'rejected' and value['effects']:
            errors.append('rejected_operation_has_effects')
    if name == 'operation-context':
        try:
            datetime.fromisoformat(value['deadline'])
        except ValueError:
            errors.append('calendar_date')
    return errors



def nesting_errors(parent, child, manifest):
    """Check resolved fixture records; production must fetch and authenticate them."""
    errors = []
    relation = child['parent']
    if not relation or relation['instanceId'] != parent['instanceId']:
        return ['parent_instance_binding']
    mode = 'private-child' if relation['relationship'] == 'private' else 'independent'
    if mode not in manifest['installationModes'] or child['packageId'] != manifest['packageId'] or child['packageVersion'] != manifest['version']:
        errors.append('installation_mode_or_package')
    if child['hubId'] != parent['hubId']:
        errors.append('parent_hub_binding')
    # An independent reference gives the parent no inherited authority over the child.
    if relation['relationship'] == 'independent-reference':
        return errors
    source, grant = parent['effectiveGrant'], child['effectiveGrant']
    if grant['parentGrantRef'] != {'id': source['grantId'], 'ownerHubId': source['issuerHubId'], 'revision': source['revision']}:
        errors.append('parent_grant_binding')
    if grant['issuerHubId'] != source['issuerHubId']:
        errors.append('grant_issuer_binding')
    if any(grant['scope'][key] != source['scope'][key] for key in source['scope']):
        errors.append('scope_escalation')
    if not set(grant['actions']) <= set(source['actions']) or not set(grant['resourceIds']) <= set(source['resourceIds']):
        errors.append('capability_escalation')
    if datetime.fromisoformat(grant['issuedAt']) < datetime.fromisoformat(source['issuedAt']) or datetime.fromisoformat(grant['expiresAt']) > datetime.fromisoformat(source['expiresAt']):
        errors.append('grant_lifetime_escalation')
    if any(child['services'][key]['handleId'] == parent['services'][key]['handleId'] for key in child['services']):
        errors.append('parent_service_handle_reused')
    return errors


def mutate(example, fixture):
    result = copy.deepcopy(example)
    parent = result
    for part in fixture['path'][:-1]:
        parent = parent[part]
    key = fixture['path'][-1]
    if fixture.get('remove'):
        del parent[key]
    else:
        parent[key] = copy.deepcopy(fixture['value'])
    return result


def main():
    schemas = {path.name.removesuffix('.schema.json'): read(path.name) for path in HERE.glob('*.schema.json')}
    registry = Registry().with_resources((s['$id'], Resource.from_contents(s)) for s in schemas.values())
    validators = {}
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        validators[name] = Draft202012Validator(schema, registry=registry)
    valid = read('valid-examples.json')
    results = []
    for name, example in valid.items():
        validators[name].validate(example)
        require(not semantic_errors(name, example), f'Invalid positive model: {name}')
        results.append({'id': 'valid-' + name, 'passed': True})
    # The same declared package must remain installable in either explicit mode.
    for mode in ['independent', 'private-child']:
        sample = copy.deepcopy(valid['plugin-manifest'])
        sample['installationModes'] = [mode]
        validators['plugin-manifest'].validate(sample)
        results.append({'id': 'declared-mode-' + mode, 'passed': True})
    status_reader = copy.deepcopy(valid['plugin-manifest'])
    status_reader['requestedCapabilities'] = [{'action': 'subscribe', 'resourceClass': 'kernel-status', 'required': True}]
    validators['plugin-manifest'].validate(status_reader)
    require(not semantic_errors('plugin-manifest', status_reader), 'Kernel information must remain subscribable')
    results.append({'id': 'ordinary-plugin-can-subscribe-kernel-status', 'passed': True})
    for fixture in read('invalid-examples.json'):
        bad = mutate(valid[fixture['schema']], fixture)
        errors = list(validators[fixture['schema']].iter_errors(bad))
        require(any(e.validator == fixture['keyword'] for e in errors), 'Expected shape rejection: ' + fixture['id'])
        results.append({'id': fixture['id'], 'passed': True})
    for fixture in read('semantic-examples.json'):
        sample = mutate(valid[fixture['schema']], fixture)
        validators[fixture['schema']].validate(sample)
        require(fixture['error'] in semantic_errors(fixture['schema'], sample), 'Expected semantic rejection: ' + fixture['id'])
        results.append({'id': fixture['id'], 'passed': True})
    nesting = read('nesting-examples.json')
    for fixture in nesting['cases']:
        bundle = copy.deepcopy(nesting['baseline'])
        for change in fixture.get('changes', []):
            bundle = mutate(bundle, change)
        for key in ('parent', 'child'):
            validators['plugin-context'].validate(bundle[key])
            require(not semantic_errors('plugin-context', bundle[key]), 'Invalid nesting input: ' + fixture['id'])
        validators['plugin-manifest'].validate(bundle['manifest'])
        errors = nesting_errors(**bundle)
        require(errors == fixture['errors'], 'Unexpected nesting decision: ' + fixture['id'] + ': ' + str(errors))
        results.append({'id': fixture['id'], 'passed': True})
    machines = read('state-machines.json')['machines']
    for name, machine in machines.items():
        states = set(machine['states'])
        require(len(states) == len(machine['states']) and machine['initial'] in states, name + ': invalid states')
        keys = set()
        for edge in machine['transitions']:
            require(edge['from'] in states and edge['to'] in states and edge['requires'], name + ': invalid edge')
            key = (edge['from'], edge['event'], edge['actorRole'])
            require(key not in keys, name + ': ambiguous transition')
            keys.add(key)
    for fixture in read('model-examples.json'):
        edges = [e for e in machines[fixture['machine']]['transitions']
                 if (e['from'], e['event'], e['actorRole']) == (fixture['from'], fixture['event'], fixture['actorRole'])
                 and set(e['requires']) <= set(fixture['guards'])]
        require(bool(edges) == fixture['allowed'], 'Unexpected model decision: ' + fixture['id'])
        if edges:
            require(len(edges) == 1 and edges[0]['to'] == fixture['expectedTo'], 'Unexpected next state: ' + fixture['id'])
        results.append({'id': fixture['id'], 'passed': True})
    # A required reservation must never have an implicit timeout reassignment.
    for name in ['task', 'delegation']:
        for edge in machines[name]['transitions']:
            if edge['event'] in ('link_lost', 'timeout', 'presence_expired'):
                require(edge['from'] == edge['to'], 'Connectivity cannot release a reservation')
    report = {'status': 'passed-draft-contract-checks', 'python': platform.python_version(),
              'validator': 'jsonschema ' + importlib.metadata.version('jsonschema'),
              'schemas': len(schemas), 'stateMachines': len(machines), 'cases': results,
              'sourceSha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir()
                               if p.name.endswith('.schema.json') or p.name in ('verify.py', 'valid-examples.json', 'invalid-examples.json', 'semantic-examples.json', 'model-examples.json', 'state-machines.json', 'nesting-examples.json', 'requirements.lock')},
              'limitations': ['One validator/runtime only; independent SDK conformance remains P01.',
                             'Guard labels declare obligations; they do not prove authorization, broker behavior or human approval.',
                             'Payload and state are extension slots; each named domain contract still requires its own closed schema.',
                             'Nesting fixtures use exact scope equality, explicit resources (empty means none), and resolved parent revisions; narrower scope delegation needs an explicit future contract.',
                             'No runtime plugin loading, persistence, migration, host startup or partner execution is tested.']}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}))
        sys.exit(1)
