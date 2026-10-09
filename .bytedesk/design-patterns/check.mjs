#!/usr/bin/env node
// Standalone, dependency-free gate copied into consuming repositories.
import { readFileSync, existsSync, lstatSync, realpathSync } from 'node:fs';
import { resolve, relative, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export const VERSION = '1.1.0';
// Repository-relative home of the copied gate, policy and review records.
export const STORE = '.bytedesk/design-patterns';
export const RULES = Array.from({ length: 11 }, (_, i) => `DP${String(i + 1).padStart(3, '0')}`);
const excluded = new Set([`${STORE}/review.json`, `${STORE}/remediation.json`]);
// Files the architecture plugin writes on every sync: its C4 model, generated
// DSL, evidence lock, verification cache and tooling copy. They describe the
// code rather than change it, so they must not make a pattern review stale
// (and trip the commit hook) each time the architecture model is refreshed.
const excludedPrefixes = ['.bytedesk/architecture/'];
const excludedArchitecture = new Set(['docs/architecture/model.yaml', 'docs/architecture/workspace.dsl', 'docs/architecture/evidence.lock.json', 'docs/architecture/verification.json']);
const isExcluded = file => excluded.has(file) || excludedArchitecture.has(file) || excludedPrefixes.some(p => file.startsWith(p));
export const sha = data => createHash('sha256').update(data).digest('hex');
const nonempty = v => typeof v === 'string' && v.trim().length > 0;
export function git(root, args) {
  return execFileSync('git', ['-C', root, ...args], { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
}
export function rootPath(root) {
  const actual = realpathSync(resolve(root));
  const top = realpathSync(git(actual, ['rev-parse', '--show-toplevel']).trim());
  if (git(actual, ['rev-parse', '--show-prefix']).trim()) throw new Error('Pass the repository root, not a subdirectory.');
  return top;
}
export function safeFile(root, file) {
  if (!nonempty(file) || isAbsolute(file) || file.includes('\\') || file.split('/').some(p => !p || p === '.' || p === '..' || p === '.git')) throw new Error(`Invalid repository path: ${file}`);
  const target = resolve(root, file);
  const rel = relative(root, target);
  if (rel.startsWith('..') || isAbsolute(rel)) throw new Error(`Path leaves repository: ${file}`);
  if (!existsSync(target)) throw new Error(`Missing evidence/source: ${file}`);
  const real = realpathSync(target);
  const realRel = relative(root, real);
  if (realRel.startsWith('..') || isAbsolute(realRel) || lstatSync(target).isSymbolicLink()) throw new Error(`Linked path is not reviewable evidence: ${file}`);
  if (!lstatSync(target).isFile()) throw new Error(`Expected a file: ${file}`);
  return target;
}
export function files(root) {
  return [...new Set(git(root, ['ls-files', '-z', '--cached', '--others', '--exclude-standard']).split('\0').filter(Boolean))].sort();
}
export function digest(root) {
  root = rootPath(root);
  const hash = createHash('sha256');
  for (const file of files(root)) {
    if (isExcluded(file)) continue;
    const target = resolve(root, file);
    hash.update(file + '\0');
    if (!existsSync(target)) { hash.update('deleted\0'); continue; }
    // Symlinks/submodules must be reviewed separately rather than traversed outside the repo.
    safeFile(root, file);
    hash.update(sha(readFileSync(target)) + '\0');
  }
  return hash.digest('hex');
}
function json(root, file) { return JSON.parse(readFileSync(safeFile(root, file), 'utf8')); }
function text(root, file) { return readFileSync(safeFile(root, file), 'utf8'); }
function registry(root) {
  const body = text(root, '.context/design-patterns.md');
  const matches = [...body.matchAll(/<!-- design-patterns-registry:v1 -->\s*```json\s*([\s\S]*?)```/g)];
  if (matches.length !== 1) throw new Error('Exactly one design-patterns-registry:v1 JSON block is required');
  return JSON.parse(matches[0][1]);
}
function at(root, commit, file) {
  return execFileSync('git', ['-C', root, 'show', `${commit}:${file}`], { maxBuffer: 32 * 1024 * 1024, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
}
function ancestor(root, earlier, later) {
  try { git(root, ['merge-base', '--is-ancestor', earlier, later]); return true; } catch { return false; }
}
export function check(root, { base, today = new Date().toISOString().slice(0, 10) } = {}) {
  root = rootPath(root);
  const errors = [];
  const require = (test, message) => { if (!test) errors.push(message); };
  const evidence = (list, label) => {
    require(Array.isArray(list) && list.length > 0, `${label}: evidence files required`);
    for (const path of Array.isArray(list) ? list : []) {
      try { safeFile(root, path); } catch (e) { errors.push(`${label}: ${e.message}`); }
    }
  };
  try {
    const p = json(root, `${STORE}/project.json`);
    const r = json(root, `${STORE}/review.json`);
    const debt = json(root, `${STORE}/remediation.json`);
    const catalog = json(root, `${STORE}/catalog.json`);
    const patterns = registry(root);
    const claudeRule = text(root, '.claude/rules/design-patterns.md');
    const claudeFrontendRule = text(root, '.claude/rules/frontend-components.md');
    const sharedRule = text(root, `${STORE}/agent-rules.md`);
    const frontendPolicy = text(root, `${STORE}/frontend-rules.md`);
    const claudeInstructions = text(root, 'CLAUDE.md');
    const codexInstructions = text(root, 'AGENTS.md');
    const diagrams = text(root, '.context/design-patterns-diagrams.md');
    require(p.baselineVersion === VERSION, `Uniform baseline ${VERSION} required`);
    require(catalog.schemaVersion === '1.0.0' && Array.isArray(catalog.patterns), 'Pinned pattern catalog is missing or invalid');
    require(patterns.schemaVersion === '1.0.0' && Array.isArray(patterns.entries), 'Pattern registry schemaVersion 1.0.0 and entries array required');
    require(claudeRule.includes('.context/design-patterns.md') && claudeRule.includes('.context/design-patterns-diagrams.md'), 'Claude project rule must point to both design-pattern context files');
    require(claudeFrontendRule.includes('src/components/{atoms,molecules,organisms,templates}') && frontendPolicy.includes('## Atomization rule'), 'Strict frontend Claude rule and shared atomization policy required');
    require(sharedRule.includes('Dofactory') && sharedRule.includes('Enterprise Integration Patterns'), 'Shared agent rules must name both approved pattern sources');
    require(claudeInstructions.includes('<!-- design-patterns-context:start -->') && claudeInstructions.includes('<!-- design-patterns-context:end -->'), 'CLAUDE.md managed design-patterns block required');
    require(codexInstructions.includes('<!-- design-patterns-context:start -->') && codexInstructions.includes('<!-- design-patterns-context:end -->'), 'AGENTS.md managed design-patterns block required');
    require(diagrams.includes('## Abstract pattern architecture') && diagrams.includes('## Concrete implementation architecture') && diagrams.includes('```mermaid') && diagrams.includes('```plantuml'), 'Abstract and concrete Mermaid/PlantUML diagrams required');
    const approved = new Map((catalog.patterns ?? []).map(x => [`${x.catalog}:${x.name}`, x]));
    const registryIds = new Set();
    for (const entry of patterns.entries ?? []) {
      require(nonempty(entry.id) && !registryIds.has(entry.id), `Pattern registry ID missing/duplicated: ${entry.id}`); registryIds.add(entry.id);
      require(['planned','applied','observed','referenced','evaluated','retired'].includes(entry.status), `${entry.id}: invalid pattern lifecycle status`);
      const known = approved.get(`${entry.catalog}:${entry.pattern}`);
      require(Boolean(known), `${entry.id}: pattern is not in the pinned Dofactory/EIP catalog`);
      if (known) require(entry.source === known.source && entry.referenceDepth === known.referenceDepth, `${entry.id}: source/reference depth must match pinned catalog`);
      require(nonempty(entry.how) && nonempty(entry.why), `${entry.id}: how and why are required`);
      require(nonempty(entry.tradeoffs), `${entry.id}: tradeoffs are required`);
      if (['applied','observed'].includes(entry.status)) {
        require(Array.isArray(entry.locations) && entry.locations.length > 0, `${entry.id}: applied/observed pattern locations required`);
        for (const location of entry.locations ?? []) {
          require(nonempty(location.symbol), `${entry.id}: location symbol required`);
          try { safeFile(root, location.path); } catch (e) { errors.push(`${entry.id}: ${e.message}`); }
        }
        evidence(entry.verificationEvidence, `${entry.id} verification`);
        require(diagrams.includes(entry.id), `${entry.id}: applied/observed pattern must appear in the architecture diagrams`);
      }
      if (['planned','referenced','evaluated'].includes(entry.status)) evidence(entry.decisionEvidence, `${entry.id} decision`);
      if (entry.status === 'retired') require(nonempty(entry.retiredReason), `${entry.id}: retired reason required`);
    }
    require(!('exceptions' in p) && !('disabledRules' in p) && !('ruleOverrides' in p), 'Repository policy exceptions are forbidden');
    require(nonempty(p.owner), 'Project owner required');
    const surfaces = ['web', 'desktop', 'backend', 'codesys', 'library'];
    require(Array.isArray(p.surfaces) && p.surfaces.length > 0 && p.surfaces.every(x => surfaces.includes(x)), 'Valid project surfaces required');
    require(Array.isArray(p.languages) && p.languages.length > 0 && p.languages.every(nonempty), 'Languages required');
    const frontend = p.surfaces?.some(x => ['web', 'desktop'].includes(x));
    if (frontend) {
      require(Array.isArray(p.frontendRoots) && p.frontendRoots.length > 0, 'Web/desktop projects must declare frontendRoots');
      const tracked = files(root);
      for (const declared of Array.isArray(p.frontendRoots) ? p.frontendRoots : []) {
        require(typeof declared === 'string' && !isAbsolute(declared) && !declared.includes('\\') && !declared.split('/').some(x => x === '..' || x === '.' || !x), `Invalid frontend root: ${declared}`);
        const prefix = declared ? `${declared}/` : '';
        for (const tier of ['atoms','molecules','organisms','templates']) {
          const tierPrefix = `${prefix}src/components/${tier}/`;
          require(tracked.some(file => file.startsWith(tierPrefix)), `${tierPrefix} must contain a tracked index, README, or component`);
        }
        const source = /\.(?:ts|tsx|js|jsx|vue|svelte|razor|xaml|cs|swift|kt)$/i;
        for (const file of tracked.filter(file => file.startsWith(`${prefix}src/`) && source.test(file))) {
          const componentPart = file.slice(`${prefix}src/`.length);
          if (/^(?:ui|common|shared|widgets)\//i.test(componentPart) || /^features\/[^/]+\/components\//i.test(componentPart)) errors.push(`${file}: reusable frontend components must use src/components atomic tiers`);
          if (componentPart.startsWith('components/')) {
            const valid = /^components\/(atoms|molecules|organisms|templates)\/(?:index\.[^/]+|[A-Z][^/]*\/[^/]+)$/.test(componentPart) || /^components\/index\.[^/]+$/.test(componentPart);
            require(valid, `${file}: invalid atomic component location`);
          }
        }
      }
    }
    for (const key of ['decision', 'rationale']) require(nonempty(p.architecture?.[key]), `Architecture ${key} required from interview`);
    for (const key of ['constraints', 'alternatives']) require(Array.isArray(p.architecture?.[key]) && p.architecture[key].length > 0 && p.architecture[key].every(nonempty), `Architecture ${key} required`);
    require(Array.isArray(p.toolchains) && p.toolchains.length > 0 && p.toolchains.every(t => nonempty(t.name) && nonempty(t.version) && /^v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?$/.test(t.version)), 'Record exact numeric toolchain version strings, not ranges or release channels');
    for (const key of ['build', 'test']) require(Array.isArray(p.verification?.[key]) && p.verification[key].length > 0 && p.verification[key].every(nonempty), `Verification ${key} commands required`);
    evidence(p.decisionEvidence, 'Project decisions');
    require(nonempty(r.reviewer), 'Review author required');
    require(r.sourceDigest === digest(root), 'Review is stale or missing: inspect changes and refresh sourceDigest');
    require(Array.isArray(r.findings), 'Review findings must be an array');
    require(Array.isArray(debt), 'Remediation must be an array');
    const findings = Array.isArray(r.findings) ? r.findings : [];
    const remediation = Array.isArray(debt) ? debt : [];
    const ids = new Set();
    for (const f of findings) {
      require(nonempty(f.id) && !ids.has(f.id), `Finding ID missing/duplicated: ${f.id}`); ids.add(f.id);
      require(RULES.includes(f.rule), `${f.id}: unknown rule`);
      require(nonempty(f.summary) && nonempty(f.symbol), `${f.id}: summary and symbol required`);
      evidence([f.path], f.id);
    }
    for (const id of RULES) {
      const a = r.rules?.[id];
      const applicable = ['DP009','DP011'].includes(id) ? frontend : id === 'DP010' ? p.surfaces?.includes('codesys') : true;
      if (!applicable) {
        require(a?.status === 'not-applicable' && nonempty(a.reason), `${id}: explain surface-based non-applicability`);
        require(!findings.some(f => f.rule === id), `${id}: findings conflict with non-applicability`);
        continue;
      }
      const count = findings.filter(f => f.rule === id).length;
      require(a?.status === (count ? 'findings' : 'pass'), `${id}: applicable rule must be ${count ? 'findings' : 'pass'}`);
      require(nonempty(a?.rationale), `${id}: review rationale required`);
      evidence(a?.evidence, id);
    }
    let baseCommit;
    let changed = new Set();
    let previousDebt = [];
    if (base) {
      baseCommit = git(root, ['rev-parse', '--verify', `${base}^{commit}`]).trim();
      require(ancestor(root, baseCommit, 'HEAD'), 'CI base must be an ancestor of HEAD');
      changed = new Set(git(root, ['diff', '--name-only', '-z', baseCommit, '--']).split('\0').filter(Boolean));
      let priorBytes;
      try { priorBytes = at(root, baseCommit, `${STORE}/remediation.json`); }
      catch { /* First adoption has no debt ledger in the base. */ }
      if (priorBytes) {
        try { previousDebt = JSON.parse(priorBytes.toString()); }
        catch { errors.push('Malformed base remediation ledger'); }
      }
      if (!Array.isArray(previousDebt)) { errors.push('Invalid base remediation ledger'); previousDebt = []; }
      try {
        const old = JSON.parse(at(root, baseCommit, `${STORE}/project.json`).toString());
        require(old.adoptionCommit === p.adoptionCommit, 'Cannot reset adoptionCommit to reclassify new violations as legacy');
      } catch (e) {
        // A first adoption has no project record in the base. Malformed existing JSON must not bypass the invariant.
        let existed = false;
        try { at(root, baseCommit, `${STORE}/project.json`); existed = true; } catch {}
        if (existed) errors.push(`Invalid base project record: ${e.message}`);
      }
    }
    if (p.adoptionCommit !== null) {
      require(/^[0-9a-f]{40}$/.test(p.adoptionCommit ?? ''), 'adoptionCommit must be null or a full commit SHA');
      require(ancestor(root, p.adoptionCommit, baseCommit ?? 'HEAD'), 'Adoption commit must precede the CI base/HEAD');
    }
    const debtIds = new Set();
    for (const d of remediation) {
      require(nonempty(d.id) && !debtIds.has(d.id), `Duplicate/missing remediation ID: ${d.id}`); debtIds.add(d.id);
      require(['open', 'resolved'].includes(d.status), `${d.id}: remediation status must be open or resolved`);
      require(nonempty(d.owner) && nonempty(d.issue), `${d.id}: remediation owner and issue required`);
      if (d.status === 'resolved') {
        evidence(d.resolutionEvidence, `${d.id} resolution`);
        require(!ids.has(d.id), `${d.id}: resolved remediation still has an active finding`);
      } else {
        require(ids.has(d.id), `${d.id}: open remediation must retain its finding`);
        const validDate = /^\d{4}-\d{2}-\d{2}$/.test(d.due ?? '') && !Number.isNaN(Date.parse(d.due)) && new Date(d.due).toISOString().slice(0, 10) === d.due;
        require(validDate && d.due >= today, `${d.id}: valid, unexpired remediation deadline required`);
      }
    }
    for (const previous of previousDebt) {
      require(remediation.some(d => d.id === previous.id), `${previous.id}: preserve remediation history; resolve with evidence instead of deleting`);
    }
    for (const f of findings) {
      const d = remediation.find(d => d.id === f.id && d.status === 'open');
      require(Boolean(d), `${f.id}: violation needs repair or mandatory legacy remediation`);
      if (!d) continue;
      require(!changed.has(f.path), `${f.id}: changed-file violation cannot be deferred`);
      require(p.adoptionCommit !== null, `${f.id}: greenfield violations cannot be legacy debt`);
      try {
        const historic = sha(at(root, p.adoptionCommit, f.path));
        require(d.sourceHash === historic && sha(readFileSync(safeFile(root, f.path))) === historic, `${f.id}: legacy source must be unchanged since adoption`);
      } catch { errors.push(`${f.id}: cannot prove legacy source at adoption commit`); }
    }
  } catch (e) { errors.push(e.message); }
  return { baselineVersion: VERSION, ok: errors.length === 0, errors, assurance: 'Validates review attestations, source freshness and remediation; does not prove semantic correctness or execute build/tests.' };
}
export function options(args) {
  const out = {};
  for (let i = 0; i < args.length; i += 2) {
    if (!args[i].startsWith('--') || args[i + 1] === undefined || args[i + 1].startsWith('--')) throw new Error(`Expected --key value, got ${args[i]}`);
    const key = args[i].slice(2);
    if (key in out) throw new Error(`Repeated option: ${key}`);
    out[key] = args[i + 1];
  }
  return out;
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const [command, ...args] = process.argv.slice(2); const opts = options(args);
    if (!['check', 'digest'].includes(command)) throw new Error('Usage: node check.mjs check|digest --root <repo> [--base <commit>]');
    for (const key of Object.keys(opts)) if (!['root', 'base'].includes(key)) throw new Error(`Unknown option: ${key}`);
    const result = command === 'digest' ? { sourceDigest: digest(opts.root ?? '.') } : check(opts.root ?? '.', opts);
    console.log(JSON.stringify(result, null, 2)); if (result.ok === false) process.exitCode = 1;
  } catch (e) { console.error(e.message); process.exitCode = 1; }
}
