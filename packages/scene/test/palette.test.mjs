/* Two things: that the tokens are read correctly, and that there is nothing to
 * read them INSTEAD of.
 *
 * The second is the one that rots. Token plumbing is easy to write and easy to
 * work around at 5pm — one hard-coded orange for a highlight, and the scene no
 * longer rethemes with the product. design/tokens.css says it plainly: "a
 * literal in a component is a duration that cannot be switched off", and the
 * same is true of a colour. So the source tree is scanned, and a colour literal
 * anywhere in it fails this suite.
 *
 * It also checks the reduced-motion contract end to end, because that contract
 * lives in a stylesheet: --dur-slow goes to 0ms inside the reduced-motion
 * block, and a camera move that reads its duration from that token becomes a
 * jump with no branch in the renderer at all.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

import {
  hexToRgb,
  packRgb,
  parseColor,
  prefersReducedMotion,
  readColor,
  readDurationMs,
  readFontStack,
  readNumberToken,
  readPalette,
  readToken,
} from '../src/palette.ts';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));
const TOKENS_CSS = fileURLToPath(new URL('../../../design/tokens.css', import.meta.url));

/** A document that answers getComputedStyle from a token map, and nothing else. */
function fakeDoc(tokens = {}, { motion = null, reduced = false } = {}) {
  const documentElement = {
    dataset: motion ? { motion } : {},
    getAttribute: (name) => (name === 'data-motion' ? motion : null),
  };
  const defaultView = {
    getComputedStyle: (el) => {
      assert.equal(el, documentElement, 'tokens are read off :root, not off a node');
      return { getPropertyValue: (name) => tokens[name] ?? '' };
    },
    matchMedia: (query) => ({
      matches: query.includes('prefers-reduced-motion') ? reduced : false,
    }),
  };
  return { documentElement, defaultView };
}

// ── the rule that rots ──────────────────────────────────────────────────────

test('there is not one colour literal anywhere in src/', () => {
  const offenders = [];
  for (const name of readdirSync(SRC)) {
    if (!name.endsWith('.ts')) continue;
    const text = readFileSync(join(SRC, name), 'utf8');
    text.split('\n').forEach((line, i) => {
      // A CSS hex colour, or a packed one of the kind three.js takes.
      if (/#[0-9a-fA-F]{3,8}\b/.test(line) || /\b0x[0-9a-fA-F]{6}\b/.test(line)) {
        offenders.push(`${name}:${i + 1}: ${line.trim()}`);
      }
    });
  }
  assert.deepEqual(
    offenders,
    [],
    'a colour here is a second source of truth for the palette, and it is the one '
    + 'nobody remembers to update. Put it in design/tokens.css and read the token.',
  );
});

test('every token this package reads is actually declared in design/tokens.css', () => {
  const css = readFileSync(TOKENS_CSS, 'utf8');
  const declared = new Set([...css.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm)].map((m) => m[1]));

  const asked = new Set();
  for (const name of readdirSync(SRC)) {
    if (!name.endsWith('.ts')) continue;
    const text = readFileSync(join(SRC, name), 'utf8');
    for (const m of text.matchAll(/'(--[a-z0-9-]+)'/g)) asked.add(m[1]);
  }

  assert.ok(asked.size > 0, 'the scan found no tokens at all, so it is not testing anything');
  const missing = [...asked].filter((t) => !declared.has(t));
  assert.deepEqual(
    missing,
    [],
    'these tokens are read by the scene but not declared in design/tokens.css, so they '
    + 'would silently fall back to grey',
  );
});

test('the reduced-motion block really does zero the duration this package reads', () => {
  const css = readFileSync(TOKENS_CSS, 'utf8');
  const block = /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\n\}/.exec(css);
  assert.ok(block, 'design/tokens.css no longer has a reduced-motion block');
  assert.match(
    block[1],
    /--dur-slow:\s*0ms/,
    'focus() reads --dur-slow. If that stops collapsing to zero, the camera starts '
    + 'easing for people who asked it not to.',
  );
});

// ── reading ─────────────────────────────────────────────────────────────────

test('readToken returns the declared text, or an empty string', () => {
  const doc = fakeDoc({ '--accent': ' #f6623e ' });
  assert.equal(readToken('--accent', doc), '#f6623e');
  assert.equal(readToken('--nope', doc), '');
});

test('readToken never throws, whatever it is handed', () => {
  for (const bad of [null, undefined, {}, { documentElement: null }, 7, 'nope']) {
    assert.equal(readToken('--accent', bad), '');
  }
  const hostile = {
    documentElement: {},
    defaultView: { getComputedStyle() { throw new Error('detached'); } },
  };
  assert.equal(readToken('--accent', hostile), '', 'a render loop is no place for an exception');
});

test('parseColor understands the forms a token can hold', () => {
  assert.deepEqual(parseColor('#ffffff'), [1, 1, 1]);
  assert.deepEqual(parseColor('#000000'), [0, 0, 0]);
  assert.deepEqual(parseColor('fff'), [1, 1, 1]);
  assert.deepEqual(parseColor('#FFF'), [1, 1, 1]);
  assert.deepEqual(parseColor('rgb(255, 0, 0)'), [1, 0, 0]);
  assert.deepEqual(parseColor('rgb(0 255 0)'), [0, 1, 0]);
  const mid = parseColor('#808080');
  assert.ok(Math.abs(mid[0] - 0.502) < 0.005);
});

test('an unreadable colour falls back to a neutral, never to an invented hue', () => {
  const fallback = [0.5, 0.5, 0.5];
  for (const bad of ['', '   ', 'teal', 'var(--accent)', '#12345', null, undefined]) {
    assert.deepEqual(parseColor(bad, fallback), fallback);
  }
  assert.deepEqual(hexToRgb('not a colour', fallback), fallback);

  // With no tokens at all the palette is grey. That is correct: solid versus
  // wireframe still answers the only question the view is for.
  const blind = readPalette(null);
  for (const key of ['line', 'lineStrong', 'conflict', 'label', 'selection']) {
    const [r, g, b] = blind[key];
    assert.ok(Math.abs(r - g) < 0.06 && Math.abs(g - b) < 0.06, `${key} invented a hue`);
  }
});

test('readColor and packRgb agree, and packRgb is arithmetic', () => {
  const doc = fakeDoc({ '--accent-hot': '#ff5202' });
  assert.deepEqual(readColor('--accent-hot', undefined, doc), [1, 82 / 255, 2 / 255]);
  assert.equal(packRgb([1, 1, 1]), 0xffffff);
  assert.equal(packRgb([0, 0, 0]), 0);
  assert.equal(packRgb([1, 82 / 255, 2 / 255]), (255 << 16) | (82 << 8) | 2);
  assert.equal(packRgb([2, -1, 0.5]), (255 << 16) | (0 << 8) | 128, 'clamped, not wrapped');
});

test('durations parse in both units and fall back when they do not', () => {
  const doc = fakeDoc({
    '--dur-slow': '500ms',
    '--dur-seconds': '0.5s',
    '--dur-zero': '0ms',
    '--dur-bare': '0',
    '--dur-junk': 'slowly',
  });
  assert.equal(readDurationMs('--dur-slow', 999, doc), 500);
  assert.equal(readDurationMs('--dur-seconds', 999, doc), 500);
  assert.equal(readDurationMs('--dur-zero', 999, doc), 0);
  assert.equal(readDurationMs('--dur-bare', 999, doc), 0);
  assert.equal(readDurationMs('--dur-junk', 999, doc), 999);
  assert.equal(readDurationMs('--dur-missing', 999, doc), 999);
});

test('readNumberToken and readFontStack', () => {
  const doc = fakeDoc({ '--grain-opacity': '0.035', '--font-mono': '"JetBrains Mono", monospace' });
  assert.equal(readNumberToken('--grain-opacity', 1, doc), 0.035);
  assert.equal(readNumberToken('--nope', 1, doc), 1);
  assert.equal(readFontStack('--font-mono', doc), '"JetBrains Mono", monospace');
  assert.equal(readFontStack('--nope', doc), 'monospace', 'canvas needs a usable font string');
});

// ── the reduced-motion contract ─────────────────────────────────────────────

test('reduced motion is read from the OS setting and from the operator switch', () => {
  assert.equal(prefersReducedMotion(fakeDoc({})), false);
  assert.equal(prefersReducedMotion(fakeDoc({}, { reduced: true })), true);
  assert.equal(
    prefersReducedMotion(fakeDoc({}, { motion: 'off' })),
    true,
    'tokens.css has an explicit switch for a plant floor machine, independent of Windows',
  );
  assert.equal(prefersReducedMotion(null), false);
});

test('with the reduced-motion block in effect, focus is a jump', () => {
  // What tokens.css actually produces under @media (prefers-reduced-motion).
  const quiet = readPalette(fakeDoc(
    { '--dur-slow': '0ms', '--dur-micro': '0ms' },
    { reduced: true },
  ));
  assert.equal(quiet.focusMs, 0, 'a camera that eases for someone who asked it not to');
  assert.equal(quiet.hoverMs, 0);
  assert.equal(quiet.reducedMotion, true);

  const normal = readPalette(fakeDoc({ '--dur-slow': '500ms', '--dur-micro': '100ms' }));
  assert.equal(normal.focusMs, 500);
  assert.equal(normal.reducedMotion, false);
});

test('readPalette resolves every role it promises', () => {
  const doc = fakeDoc({
    '--surface-void': '#0d0d0f',
    '--line': '#303036',
    '--line-strong': '#45454e',
    '--accent-hot': '#ff5202',
    '--accent': '#f6623e',
    '--text-primary': '#eff1ec',
    '--text-muted': '#71717a',
    '--font-mono': 'ui-monospace',
  });
  const palette = readPalette(doc);
  assert.deepEqual(palette.void_, [13 / 255, 13 / 255, 15 / 255]);
  assert.deepEqual(palette.conflict, [1, 82 / 255, 2 / 255]);
  assert.equal(palette.fontMono, 'ui-monospace');
  assert.deepEqual(palette.color('--line'), [48 / 255, 48 / 255, 54 / 255]);
  assert.equal(palette.packed('--accent'), (246 << 16) | (98 << 8) | 62);
});
