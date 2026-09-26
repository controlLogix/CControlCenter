/* The whitelist test. This is the one that must not be made to pass by
 * loosening it.
 *
 * `dashboard/devicetree.py` decides what kinds of knowing exist. This package
 * decides what each one LOOKS like. The failure this file exists to cause is
 * the one where somebody adds a fifth source upstream — a SNMP sweep, an LLDP
 * neighbour table, an operator's spreadsheet import — and it renders in the 3D
 * view looking exactly like a device that answered ListIdentity, because there
 * was a default branch and the default was "solid".
 *
 * So: the four upstream sources are read out of devicetree.py itself and
 * compared. A new one fails here until a person has decided whether it is a
 * statement, an assertion or a guess.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  ORIGINS,
  UPSTREAM_SOURCES,
  TREATMENTS,
  TREATMENT_SPEC,
  effectiveOrigin,
  isOrigin,
  normalizeOrigin,
  originOf,
  originsOf,
  rankOf,
  specFor,
  treatmentFor,
} from '../src/origin.ts';

const DEVICETREE_PY = fileURLToPath(new URL('../../../dashboard/devicetree.py', import.meta.url));

test('the upstream SOURCES tuple is the contract, and it is read from the real file', () => {
  assert.ok(
    existsSync(DEVICETREE_PY),
    `dashboard/devicetree.py is the other end of this contract and it is not at ${DEVICETREE_PY}. `
    + 'Either the merge moved, in which case fix this path, or it is gone, in which case '
    + 'this package has nothing to render.',
  );
  const source = readFileSync(DEVICETREE_PY, 'utf8');
  const m = /^SOURCES\s*=\s*\(([^)]*)\)/m.exec(source);
  assert.ok(m, 'devicetree.py no longer declares a SOURCES tuple at module level');
  const declared = [...m[1].matchAll(/"([^"]+)"|'([^']+)'/g)].map((x) => x[1] ?? x[2]);

  assert.deepEqual(
    [...UPSTREAM_SOURCES],
    declared,
    'devicetree.py\'s SOURCES and this package\'s UPSTREAM_SOURCES have diverged. '
    + 'Every source the merge can produce must be classified in TREATMENTS before it '
    + 'can be drawn, because there is no default treatment and a guess drawn as a '
    + 'statement is the failure this whole view exists to prevent.',
  );
});

test('every origin maps to exactly one treatment, and nothing else is listed', () => {
  assert.deepEqual(
    Object.keys(TREATMENTS).sort(),
    [...ORIGINS].sort(),
    'TREATMENTS must have one entry per origin and no entries that are not origins',
  );
  for (const origin of ORIGINS) {
    const treatment = TREATMENTS[origin];
    assert.equal(typeof treatment, 'string', `${origin} has no treatment`);
    assert.equal(treatmentFor(origin), treatment);
    // "Exactly one" is not just "at least one": the lookup is a plain object,
    // so a duplicated key would have silently won. Assert the resolved value
    // round-trips through the public function too.
    assert.equal(specFor(origin), TREATMENT_SPEC[treatment]);
  }
});

test('every treatment in use has a spec, and no spec is unused', () => {
  const used = new Set(Object.values(TREATMENTS));
  assert.deepEqual(
    Object.keys(TREATMENT_SPEC).sort(),
    [...used].sort(),
    'TREATMENT_SPEC and the treatments actually assigned to origins have diverged',
  );
});

test('an unclassified origin throws rather than picking a default', () => {
  assert.throws(
    () => treatmentFor('snmp-sweep'),
    (err) => err instanceof Error && err.message.includes('snmp-sweep'),
    'a new origin must fail loudly at the mapping, not quietly at the material',
  );
  assert.throws(() => treatmentFor(''), /no treatment/);
  assert.throws(() => specFor('lldp'), /no treatment/);
});

test('a statement and an inference differ in something that is not colour', () => {
  const statement = TREATMENT_SPEC[TREATMENTS['cip-listidentity']];
  const inference = TREATMENT_SPEC[TREATMENTS['segment-scan']];
  assert.notEqual(
    statement.wireframe,
    inference.wireframe,
    'solid versus wireframe is the channel that survives a retheme, a projector '
    + 'and a colour vision deficiency. It is the one that must differ.',
  );
  assert.equal(statement.wireframe, false, 'a device that answered renders solid');
  assert.equal(inference.wireframe, true, 'a port sweep renders as a wireframe');
});

test('no two treatments are the same treatment under different names', () => {
  const seen = new Map();
  for (const [name, spec] of Object.entries(TREATMENT_SPEC)) {
    const fingerprint = JSON.stringify(spec);
    assert.equal(
      seen.has(fingerprint),
      false,
      `${name} renders identically to ${seen.get(fingerprint)}; a distinction nobody `
      + 'can see is not a distinction',
    );
    seen.set(fingerprint, name);
  }
});

test('colours are token names, never values — palette.ts resolves them', () => {
  for (const spec of Object.values(TREATMENT_SPEC)) {
    assert.match(
      spec.colorToken,
      /^--[a-z0-9-]+$/,
      'a treatment must name a CSS custom property, so retheming the product rethemes the scene',
    );
    assert.ok(spec.opacity > 0 && spec.opacity <= 1);
    assert.equal(typeof spec.reading, 'string');
    assert.ok(spec.reading.length > 0, 'every treatment must be explainable in words');
  }
});

test('normalizeOrigin reads the free-text source forms devicetree.py writes', () => {
  assert.equal(normalizeOrigin('segment-scan'), 'segment-scan');
  assert.equal(normalizeOrigin('segment-scan (OUI)'), 'segment-scan');
  assert.equal(normalizeOrigin('cip-listidentity'), 'cip-listidentity');
  assert.equal(
    normalizeOrigin('cip-listidentity (the device said so)'),
    'cip-listidentity',
  );
  assert.equal(normalizeOrigin('  opcua-endpoints  '), 'opcua-endpoints');
  // Case-folded, because a source string is an identifier, not prose.
  assert.equal(normalizeOrigin('  OPCUA-ENDPOINTS  '), 'opcua-endpoints');
  assert.equal(normalizeOrigin('PROMOTED'), 'promoted');
});

test('normalizeOrigin will not match a longer word that merely starts the same', () => {
  assert.equal(normalizeOrigin('segment-scanner'), null);
  assert.equal(normalizeOrigin('promoted-by-hand'), null);
  assert.equal(normalizeOrigin('cip-listidentity2'), null);
  assert.equal(normalizeOrigin('cip-listidentity_v2'), null);
});

test('an unattributable source is its own thing, not one of the four', () => {
  for (const bad of [null, undefined, '', '   ', 'who knows', 42, {}]) {
    assert.equal(normalizeOrigin(bad), null);
    assert.equal(originOf(bad), 'unattributed');
  }
  assert.equal(
    TREATMENTS['unattributed'],
    'unattributed',
    '"we could not tell who said this" must not be folded into a source that means something',
  );
  assert.equal(TREATMENT_SPEC.unattributed.wireframe, true);
  assert.ok(
    TREATMENT_SPEC.unattributed.opacity < TREATMENT_SPEC.inference.opacity,
    'an unattributed claim is weaker than an inference and must not look stronger',
  );
});

test('isOrigin is a membership test, not a shape test', () => {
  assert.equal(isOrigin('segment-scan'), true);
  assert.equal(isOrigin('segment-scan (OUI)'), false);
  assert.equal(isOrigin(null), false);
  assert.equal(isOrigin(7), false);
});

test('effectiveOrigin ranks corroborating sources; it never resolves a dispute', () => {
  // A device that was swept AND answered is a device that answered.
  assert.equal(effectiveOrigin(['segment-scan', 'cip-listidentity']), 'cip-listidentity');
  assert.equal(effectiveOrigin(['cip-listidentity', 'segment-scan']), 'cip-listidentity');
  assert.equal(effectiveOrigin(['segment-scan', 'promoted']), 'promoted');
  assert.equal(effectiveOrigin(['segment-scan', 'opcua-endpoints']), 'opcua-endpoints');
  assert.equal(effectiveOrigin(['segment-scan']), 'segment-scan');
  assert.equal(effectiveOrigin(['nonsense']), 'unattributed');
  assert.equal(effectiveOrigin([]), 'unattributed');
  assert.equal(effectiveOrigin(undefined), 'unattributed');
});

test('rank orders by how much the device itself told us', () => {
  assert.ok(rankOf('cip-listidentity') < rankOf('opcua-endpoints'));
  assert.ok(rankOf('opcua-endpoints') < rankOf('promoted'));
  assert.ok(rankOf('promoted') < rankOf('segment-scan'));
  assert.ok(rankOf('segment-scan') < rankOf('unattributed'));
});

test('originsOf keeps every source, deduplicated, strongest first', () => {
  assert.deepEqual(
    originsOf(['segment-scan', 'opcua-endpoints', 'segment-scan', 'cip-listidentity']),
    ['cip-listidentity', 'opcua-endpoints', 'segment-scan'],
  );
  assert.deepEqual(originsOf(['nope']), []);
  assert.deepEqual(originsOf([]), []);
});
