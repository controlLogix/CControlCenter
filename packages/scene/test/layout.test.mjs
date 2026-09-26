/* The layout has to be arithmetic, and this is what says so.
 *
 * A force-directed graph would look better in a screenshot and would be wrong
 * in the way this product cares about: it is not reproducible, and the distance
 * between two relaxed nodes LOOKS like a measurement when it is an artefact of
 * where the simulation started. So the contract is: same devices in, identical
 * coordinates out, in any input order, on any machine, forever.
 *
 * The other half of this file is the spatial expression of the merge's rules â€”
 * one footprint per address, twins stacked over it rather than spread beside
 * it, one hub line per address rather than per node, and no line between two
 * devices unless something observed one.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { DEFAULT_LAYOUT, collectGroups, layoutTopology } from '../src/layout.ts';
import { allRows, shuffle, tree } from '../test-fixtures/tree.mjs';

const ADDRESSES = [
  '10.10.4.11', '10.10.4.12', '10.10.4.20', '10.10.4.31', '10.10.9.5', '10.10.9.7',
];

test('the same tree lays out identically, twice', () => {
  assert.deepEqual(layoutTopology(tree()), layoutTopology(tree()));
});

test('input order does not move anything', () => {
  const scrambled = tree();
  scrambled.groups = shuffle(scrambled.groups, 3);
  for (const group of scrambled.groups) group.devices = shuffle(group.devices, 11);

  const a = layoutTopology(tree());
  const b = layoutTopology(scrambled);

  const pos = (layout) => Object.fromEntries(layout.nodes.map((n) => [n.id, n.position]));
  assert.deepEqual(pos(b), pos(a), 'a scrambled snapshot must not redraw the plant');
  assert.deepEqual(b.bounds, a.bounds);
  assert.deepEqual(b.stats, a.stats);
});

test('a bare row list groups itself the same way devicetree.py would', () => {
  const groups = collectGroups(allRows());
  assert.deepEqual(groups.map((g) => g.network), ['10.10.4.0/24', '10.10.9.0/24']);
  assert.deepEqual(groups.map((g) => g.count), [4, 2]);
  assert.deepEqual(groups.map((g) => g.self_reported), [2, 1]);
});

test('addresses sort numerically, so .10 comes after .9', () => {
  const rows = [
    { address: '192.168.1.10', sources: ['segment-scan'] },
    { address: '192.168.1.9', sources: ['segment-scan'] },
    { address: '192.168.1.100', sources: ['segment-scan'] },
    { address: '192.168.1.2', sources: ['segment-scan'] },
  ];
  const [group] = collectGroups(shuffle(rows, 5));
  assert.deepEqual(
    group.devices.map((d) => d.address),
    ['192.168.1.2', '192.168.1.9', '192.168.1.10', '192.168.1.100'],
  );
});

test('every address gets exactly one footprint, and no two share one', () => {
  const layout = layoutTopology(tree());
  const byAddress = new Map();
  for (const node of layout.nodes) {
    const existing = byAddress.get(node.address);
    if (existing) assert.deepEqual(node.footprint, existing);
    else byAddress.set(node.address, node.footprint);
  }
  assert.deepEqual([...byAddress.keys()].sort(), [...ADDRESSES].sort());

  const ground = new Set();
  for (const [address, fp] of byAddress) {
    const key = `${fp[0]},${fp[2]}`;
    assert.equal(ground.has(key), false, `${address} shares a footprint with another address`);
    ground.add(key);
  }
});

test('twins stack over one footprint rather than standing beside it', () => {
  const layout = layoutTopology(tree());
  const twins = layout.nodes.filter((n) => n.address === '10.10.4.20');
  assert.equal(twins.length, 2);
  assert.equal(twins[0].position[0], twins[1].position[0], 'same x: it is one address');
  assert.equal(twins[0].position[2], twins[1].position[2], 'same z: it is one address');
  assert.notEqual(twins[0].position[1], twins[1].position[1], 'different y: it is two stories');
  assert.equal(
    Math.abs(twins[0].position[1] - twins[1].position[1]),
    DEFAULT_LAYOUT.twinGap,
  );
  // Centred, so being argued about neither promotes nor demotes an address.
  const mid = (twins[0].position[1] + twins[1].position[1]) / 2;
  assert.equal(mid, twins[0].footprint[1]);
});

test('one hub line per address, never one per twin', () => {
  const layout = layoutTopology(tree());
  const segmentLinks = layout.links.filter((l) => l.kind === 'segment');
  assert.equal(
    segmentLinks.length,
    ADDRESSES.length,
    'a disagreement about a vendor does not put a second device on the subnet',
  );
  assert.deepEqual(segmentLinks.map((l) => l.to).sort(), [...ADDRESSES].sort());
});

test('the argument itself is drawn, once per adjacent pair of twins', () => {
  const layout = layoutTopology(tree());
  const conflictLinks = layout.links.filter((l) => l.kind === 'conflict');
  assert.equal(conflictLinks.length, 1);
  const twins = layout.nodes.filter((n) => n.address === '10.10.4.20');
  assert.deepEqual(conflictLinks[0].a, twins[0].position);
  assert.deepEqual(conflictLinks[0].b, twins[1].position);
});

test('no line between two devices unless something observed one', () => {
  const bare = layoutTopology(tree());
  assert.equal(
    bare.links.some((l) => l.kind === 'adjacency'),
    false,
    'the merge produces no adjacency, so the scene must draw none',
  );

  const withEdges = tree();
  withEdges.adjacency = [
    { a: '10.10.4.11', b: '10.10.4.12', source: 'cip-listidentity' },
    { a: '10.10.4.11', b: '10.10.4.31', source: 'segment-scan' },
    { a: '10.10.4.11', b: '10.10.4.12', source: 'who knows' },
    { a: '10.10.4.11', b: '10.10.99.99', source: 'cip-listidentity' },
  ];
  const layout = layoutTopology(withEdges);
  const edges = layout.links.filter((l) => l.kind === 'adjacency');
  assert.equal(edges.length, 2, 'an unattributable edge and an edge to nowhere are both dropped');
  assert.equal(layout.stats.droppedAdjacency, 2);
  assert.deepEqual(edges.map((e) => e.confidence), ['observed', 'inferred']);
});

test('the material treatment travels with the node, resolved from the origin', () => {
  const layout = layoutTopology(tree());
  const byId = Object.fromEntries(layout.nodes.map((n) => [n.id, n]));

  assert.equal(byId['10.10.4.11'].wireframe, true, 'a port sweep is a wireframe');
  assert.equal(byId['10.10.4.12'].wireframe, false, 'a device that answered is solid');
  assert.equal(byId['10.10.4.31'].halo, 'accent', 'an operator assertion is marked');
  assert.equal(byId['10.10.9.5'].wireframe, false, 'an OPC UA endpoint list is self-reported');

  for (const node of layout.nodes) {
    assert.match(node.colorToken, /^--/, 'a node names a token, never a colour');
    assert.equal(typeof node.reading, 'string');
  }
});

test('stats count the three things the 2D panel leads with', () => {
  const layout = layoutTopology(tree());
  assert.equal(layout.stats.addresses, 6);
  assert.equal(layout.stats.nodes, 7, 'six addresses, one of them split');
  assert.equal(layout.stats.conflicted, 1);
  assert.equal(layout.stats.selfReported, 3);
  assert.equal(layout.stats.segments, 2);
});

test('bounds contain everything they claim to', () => {
  const layout = layoutTopology(tree());
  const { min, max } = layout.bounds;
  for (const node of layout.nodes) {
    for (const axis of [0, 1, 2]) {
      assert.ok(node.position[axis] >= min[axis], 'a node outside the minimum bound');
      assert.ok(node.position[axis] <= max[axis], 'a node outside the maximum bound');
    }
  }
  assert.ok(Number.isFinite(layout.bounds.radius));
  assert.ok(layout.bounds.radius > 0);
});

test('nothing in, nothing out, and the bounds are still finite', () => {
  for (const empty of [null, undefined, [], { groups: [] }, { groups: null }, {}]) {
    const layout = layoutTopology(empty);
    assert.deepEqual(layout.nodes, []);
    assert.deepEqual(layout.links, []);
    assert.deepEqual(layout.segments, []);
    assert.equal(layout.stats.addresses, 0);
    for (const n of [...layout.bounds.min, ...layout.bounds.max, layout.bounds.radius]) {
      assert.ok(Number.isFinite(n), 'an empty scene must still be framable');
    }
  }
});

test('subnets never overlap, however lopsided the plant is', () => {
  const rows = [];
  for (let i = 1; i <= 60; i += 1) rows.push({ address: `10.0.1.${i}`, sources: ['segment-scan'] });
  for (let i = 1; i <= 2; i += 1) rows.push({ address: `10.0.2.${i}`, sources: ['segment-scan'] });
  const layout = layoutTopology(rows);

  const [busy, quiet] = layout.segments;
  const gap = Math.hypot(
    busy.position[0] - quiet.position[0],
    busy.position[2] - quiet.position[2],
  );
  assert.ok(
    gap > busy.radius + quiet.radius,
    `subnets at ${gap} apart with radii ${busy.radius} and ${quiet.radius} would overlap`,
  );

  // And inside the busy one, still no two devices on the same spot.
  const spots = new Set(
    layout.nodes
      .filter((n) => n.network === '10.0.1.0/24')
      .map((n) => `${n.position[0]},${n.position[2]}`),
  );
  assert.equal(spots.size, 60);
});

test('a non-IP address is grouped as unknown rather than dropped', () => {
  const layout = layoutTopology([
    { address: 'plc-01.local', sources: ['promoted'] },
    { address: '999.1.1.1', sources: ['segment-scan'] },
  ]);
  assert.deepEqual(layout.segments.map((s) => s.network), ['unknown']);
  assert.equal(layout.stats.addresses, 2);
});

test('layout options are honoured and still deterministic', () => {
  const opts = { ringStep: 20, twinGap: 12, deviceHeight: 3 };
  const a = layoutTopology(tree(), opts);
  const b = layoutTopology(tree(), opts);
  assert.deepEqual(a, b);
  const twins = a.nodes.filter((n) => n.address === '10.10.4.20');
  assert.equal(Math.abs(twins[0].position[1] - twins[1].position[1]), 12);
  assert.equal(twins[0].footprint[1], 3);
});
