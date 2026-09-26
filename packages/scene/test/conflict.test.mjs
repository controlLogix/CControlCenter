/* The splitting rule: two disagreeing sources make two nodes, never one.
 *
 * devicetree.py refuses to pick a winner in the merge. A renderer can undo that
 * refusal without touching the data â€” by drawing one box and moving the
 * argument into a tooltip. One box means one device with one vendor to anyone
 * more than a metre from the screen, and the whole reason the merge kept both
 * values is that which one is wrong is a question for a person.
 *
 * So these tests assert the negative as hard as the positive: not only "a
 * conflict produces two nodes" but "no input with a conflict ever produces
 * one", and "neither node carries the other's value".
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { splitDevice, splitDevices } from '../src/conflict.ts';
import { allRows, tree } from '../test-fixtures/tree.mjs';

const conflictedRow = () => allRows().find((r) => r.address === '10.10.4.20');

test('a row nobody disagreed about is exactly one node', () => {
  const row = allRows().find((r) => r.address === '10.10.4.12');
  const nodes = splitDevice(row);
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].conflicted, false);
  assert.equal(nodes[0].address, '10.10.4.12');
  assert.deepEqual(nodes[0].claims, []);
  assert.equal(nodes[0].claimCount, 1);
  assert.equal(nodes[0].claimIndex, 0);
});

test('a sweep that corroborates a device that spoke does not downgrade it', () => {
  const row = allRows().find((r) => r.address === '10.10.4.12');
  const [node] = splitDevice(row);
  assert.equal(node.origin, 'cip-listidentity');
  assert.equal(node.treatment, 'statement');
  // Nothing is discarded, only ranked: the sweep is still on the node.
  assert.deepEqual(node.origins, ['cip-listidentity', 'segment-scan']);
  assert.deepEqual(node.corroborating, ['segment-scan']);
});

test('a port sweep on its own is an inference and says so', () => {
  const row = allRows().find((r) => r.address === '10.10.4.11');
  const [node] = splitDevice(row);
  assert.equal(node.origin, 'segment-scan');
  assert.equal(node.treatment, 'inference');
  assert.equal(node.sublabel, 'unidentified',
    'an address nothing named is an open port, not a device with a blank name');
});

test('an operator\'s saved row is an assertion, not the device speaking', () => {
  const row = allRows().find((r) => r.address === '10.10.4.31');
  const [node] = splitDevice(row);
  assert.equal(node.origin, 'promoted');
  assert.equal(node.treatment, 'asserted');
});

test('two disagreeing sources produce two nodes', () => {
  const nodes = splitDevice(conflictedRow());
  assert.equal(nodes.length, 2, 'a disagreement is two nodes or it is not visible');
  assert.equal(nodes[0].address, nodes[1].address, 'both nodes are the same address');
  assert.ok(nodes.every((n) => n.conflicted === true));
  assert.ok(nodes.every((n) => n.claimCount === 2));
  assert.deepEqual(nodes.map((n) => n.claimIndex), [0, 1]);
});

test('neither node carries the other\'s value â€” nothing is averaged', () => {
  const nodes = splitDevice(conflictedRow());
  const claimed = nodes.map((n) => n.claims.map((c) => c.value));
  assert.deepEqual(claimed, [['Siemens AG'], ['Rockwell Automation']]);
  for (const node of nodes) {
    const values = node.claims.map((c) => c.value);
    assert.equal(values.length, 1, 'one claimant asserted one value for one field');
  }
  // Every recorded value survives the split, and no value is invented.
  const flat = nodes.flatMap((n) => n.claims.map((c) => c.value)).sort();
  assert.deepEqual(flat, ['Rockwell Automation', 'Siemens AG']);
});

test('the two nodes do not look alike: one is a guess and one is a statement', () => {
  const nodes = splitDevice(conflictedRow());
  const byOrigin = Object.fromEntries(nodes.map((n) => [n.origin, n]));
  assert.ok(byOrigin['segment-scan'], 'the OUI side is attributed to the sweep');
  assert.ok(byOrigin['cip-listidentity'], 'the other side is attributed to the device');
  assert.equal(byOrigin['segment-scan'].treatment, 'inference');
  assert.equal(byOrigin['cip-listidentity'].treatment, 'statement');
});

test('a source that reported the address but not the disputed field gets no node', () => {
  const nodes = splitDevice(conflictedRow());
  assert.equal(nodes.length, 2, 'the OPC UA endpoint list is not a third opinion');
  for (const node of nodes) {
    assert.deepEqual(
      node.corroborating,
      ['opcua-endpoints'],
      'it reported the address, so it is recorded â€” as corroboration, not as a claim',
    );
  }
});

test('each twin says what it claims and who claimed it', () => {
  const nodes = splitDevice(conflictedRow());
  assert.equal(nodes[0].sublabel, 'vendor: Siemens AG');
  assert.equal(nodes[1].sublabel, 'vendor: Rockwell Automation');
  assert.equal(nodes[0].claimant, 'segment-scan (OUI)');
  assert.equal(nodes[1].claimant, 'cip-listidentity');
});

test('node ids are unique and stable across repeated splits', () => {
  const a = splitDevices(allRows()).map((n) => n.id);
  const b = splitDevices(allRows()).map((n) => n.id);
  assert.deepEqual(a, b, 'the same input must produce the same ids');
  assert.equal(new Set(a).size, a.length, 'ids collide, so a selection would land on two nodes');
});

test('NO row carrying a conflict ever collapses to a single node', () => {
  /* The property, not the example. Every shape of conflict this package can
   * be handed, including the malformed ones the merge does not produce. */
  const shapes = [
    [{ field: 'vendor', values: [{ value: 'a', source: 'segment-scan (OUI)' }, { value: 'b', source: 'cip-listidentity' }] }],
    [{ field: 'vendor', values: [{ value: 'a', source: 'segment-scan' }, { value: 'b', source: 'segment-scan (OUI)' }] }],
    [{ field: 'vendor', values: [{ value: 'a', source: 'segment-scan' }, { value: 'b', source: 'segment-scan' }] }],
    [{ field: 'vendor', values: [{ value: 'a', source: null }, { value: 'b', source: null }] }],
    [{ field: 'vendor', values: [{ value: 'a', source: 'weird' }, { value: 'b', source: 'also weird' }] }],
    [{ field: 'vendor', values: [{ value: 'a', source: 'segment-scan' }] }],
    [{ field: 'vendor', values: [] }],
    [
      { field: 'vendor', values: [{ value: 'a', source: 'segment-scan (OUI)' }, { value: 'b', source: 'cip-listidentity' }] },
      { field: 'mac', values: [{ value: 'x', source: 'segment-scan (OUI)' }, { value: 'y', source: 'cip-listidentity' }] },
    ],
  ];
  for (const conflicts of shapes) {
    const nodes = splitDevice({ address: '10.0.0.1', sources: ['segment-scan'], conflicts });
    assert.ok(
      nodes.length >= 2,
      `a flagged row rendered as ${nodes.length} node(s): ${JSON.stringify(conflicts)}`,
    );
  }
});

test('two claimants that normalise to the same origin are still two claimants', () => {
  const nodes = splitDevice({
    address: '10.0.0.5',
    sources: ['segment-scan'],
    conflicts: [{
      field: 'vendor',
      values: [
        { value: 'Siemens AG', source: 'segment-scan (OUI)' },
        { value: 'Beckhoff', source: 'segment-scan' },
      ],
    }],
  });
  assert.equal(nodes.length, 2, 'collapsing them by origin is averaging, one level down');
  assert.deepEqual(nodes.map((n) => n.claims[0].value), ['Siemens AG', 'Beckhoff']);
  assert.ok(nodes.every((n) => n.treatment === 'inference'));
});

test('the same claimant arguing about two fields is still one node with two claims', () => {
  const nodes = splitDevice({
    address: '10.0.0.6',
    sources: ['segment-scan', 'cip-listidentity'],
    conflicts: [
      { field: 'vendor', values: [{ value: 'a', source: 'segment-scan (OUI)' }, { value: 'b', source: 'cip-listidentity' }] },
      { field: 'device_type', values: [{ value: 'c', source: 'segment-scan (OUI)' }, { value: 'd', source: 'cip-listidentity' }] },
    ],
  });
  assert.equal(nodes.length, 2);
  assert.deepEqual(nodes.map((n) => n.claims.length), [2, 2]);
  assert.deepEqual(nodes[0].claims.map((c) => c.field), ['vendor', 'device_type']);
});

test('a flagged row with only one side recorded still shows two, and says so', () => {
  const nodes = splitDevice({
    address: '10.0.0.7',
    sources: ['segment-scan'],
    conflicts: [{ field: 'vendor', values: [{ value: 'a', source: 'segment-scan (OUI)' }] }],
  });
  assert.equal(nodes.length, 2, 'the flag is true; hiding half of it would hide the flag');
  assert.equal(nodes[1].origin, 'unattributed');
  assert.match(nodes[1].claimant, /not recorded/);
  assert.equal(nodes[1].claims.length, 0, 'no value is invented for the missing side');
});

test('a row with no address is not a node', () => {
  assert.deepEqual(splitDevice({ address: '', sources: [] }), []);
  assert.deepEqual(splitDevice({ sources: [] }), []);
  assert.deepEqual(splitDevice({ address: '   ' }), []);
});

test('a row with no sources at all is unattributed, not confirmed', () => {
  const [node] = splitDevice({ address: '10.0.0.8', sources: [] });
  assert.equal(node.origin, 'unattributed');
  assert.equal(node.treatment, 'unattributed');
});

test('the merged row travels through untouched', () => {
  const row = conflictedRow();
  const nodes = splitDevice(row);
  for (const node of nodes) {
    assert.equal(node.device, row, 'the panel must be able to render exactly what the 2D tree does');
  }
});

test('the whole fixture splits to one more node than it has addresses', () => {
  const rows = allRows();
  const nodes = splitDevices(rows);
  const flagged = rows.filter((r) => (r.conflicts ?? []).length > 0).length;
  assert.equal(flagged, 1);
  assert.equal(nodes.length, rows.length + flagged);
  assert.equal(tree().conflicts, flagged, 'the fixture matches what devicetree.py would report');
});
