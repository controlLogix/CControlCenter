#!/usr/bin/env node
/* The half of the token discipline ESLint cannot see: CSS.
 *
 * design/tokens.css is the one file where a colour, a curve or a duration is
 * decided. Every other stylesheet in this package must read them with var().
 * That is not a style preference - the reduced-motion block in tokens.css works
 * by setting --dur-* to 0ms in one place, and a literal `280ms` in a component
 * stylesheet is a duration that block cannot switch off. Somebody is made ill
 * by the animation it fails to stop.
 *
 * So this fails the build on:
 *   - a hex colour, rgb()/rgba()/hsl() literal, or a named CSS colour in src/
 *   - a bare duration (200ms, 0.3s) outside a var()
 *   - a cubic-bezier() written out rather than read from a token
 *
 * Exit code 1 with the offending file:line, so it can be a CI gate rather than
 * a paragraph in a README that nobody reads twice.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const srcDir = join(root, 'src');

/** Durations of exactly 0 are not a duration - they are "off", and they cannot
 *  be made worse by reduced motion. Allowed so a rule can state `0s` plainly. */
const ZERO = /^0(?:\.0+)?m?s$/;

const CHECKS = [
  { name: 'hex colour', re: /#[0-9a-fA-F]{3,8}\b/g },
  { name: 'rgb()/hsl() literal', re: /\b(?:rgba?|hsla?)\s*\(/g },
  { name: 'cubic-bezier() literal', re: /\bcubic-bezier\s*\(/g },
  { name: 'duration literal', re: /(?<![\w-])\d+(?:\.\d+)?m?s\b/g, allow: ZERO },
];

/** A line inside a comment is documentation, not a declaration. Strip block
 *  comments before testing, or every sentence that explains which hex a token
 *  replaced would trip the check that exists because of it. Replaced with
 *  spaces rather than removed, so reported line numbers stay true. */
function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '));
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (entry.endsWith('.css')) out.push(full);
  }
  return out;
}

const problems = [];
for (const file of walk(srcDir)) {
  const raw = readFileSync(file, 'utf8');
  const lines = stripComments(raw).split('\n');
  lines.forEach((line, i) => {
    for (const check of CHECKS) {
      check.re.lastIndex = 0;
      let m;
      while ((m = check.re.exec(line)) !== null) {
        if (check.allow && check.allow.test(m[0])) continue;
        problems.push(`${relative(root, file)}:${i + 1}  ${check.name}: ${m[0].trim()}`);
      }
    }
  });
}

if (problems.length) {
  console.error('Token discipline failed. design/tokens.css is where these are decided:\n');
  for (const p of problems) console.error('  ' + p);
  console.error('\nIf the value you need is not a token, report it - do not add a literal here.');
  process.exit(1);
}

console.log('Token discipline: no colour, curve or duration literals in src/*.css.');
