// Package the reviewed Claude Opus design without external runtime dependencies.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { renderScene } from '../components/organisms/index.mjs';

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const planRoot = resolve(siteRoot, '..');
const repoRoot = resolve(planRoot, '../../..');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const read = path => readFileSync(path);
const imageManifest = JSON.parse(read(resolve(planRoot, 'concept-images/prompts.json')));
const scenes = JSON.parse(read(resolve(siteRoot, 'scenes.json')));
if (scenes.length !== 6) throw new Error('The review requires exactly six scenes.');
const sourceHashes = {};
const rendered = scenes.map(scene => {
  const record = imageManifest.images.find(item => item.id === scene.id);
  if (!record) throw new Error(`Unknown scene: ${scene.id}`);
  const bytes = read(resolve(planRoot, 'concept-images', record.file));
  if (sha(bytes) !== record.sha256) throw new Error(`Image changed: ${record.file}`);
  sourceHashes[record.file] = sha(bytes);
  return renderScene({...scene, imageSrc:`data:image/png;base64,${bytes.toString('base64')}`});
}).join('\n');
const plan = read(resolve(planRoot, 'implementation-plan.md'));
const logo = read(resolve(repoRoot, 'dashboard/assets/logo-ccc.svg'));
const css = read(resolve(siteRoot, 'src/components/organisms/Scene/scene.css')).toString('utf8');
const script = read(resolve(siteRoot, 'src/features/review.js')).toString('utf8');
let html = read(resolve(siteRoot, 'src/pages/review.template.html')).toString('utf8');
const replacements = {
  '{{LOGO_DATA_URI}}': `data:image/svg+xml;base64,${logo.toString('base64')}`,
  '{{SCENES}}': rendered,
  '{{PLAN_DATA_URI}}': `data:text/markdown;charset=utf-8;base64,${plan.toString('base64')}`,
  '{{SCENE_CSS}}': css,
  '{{REVIEW_SCRIPT}}': script
};
for (const [marker, content] of Object.entries(replacements)) {
  if (!html.includes(marker)) throw new Error(`Missing template marker: ${marker}`);
  html = html.replaceAll(marker, () => content);
}
if (/\{\{(?:LOGO_DATA_URI|SCENES|PLAN_DATA_URI|SCENE_CSS|REVIEW_SCRIPT)\}\}/.test(html)) throw new Error('Unresolved template marker.');
const output = resolve(planRoot, 'agentmux-visual-review.html');
writeFileSync(output, html, 'utf8');
const report = {
  file: 'agentmux-visual-review.html',
  bytes: Buffer.byteLength(html),
  sha256: sha(html),
  imageCount: scenes.length,
  planSha256: sha(plan),
  logoSha256: sha(logo),
  imageHashes: sourceHashes,
  designAuthor: 'Claude Opus via the user-requested WSL terminal',
  packaging: 'Codex; all images, styles, scripts and source-plan download are embedded',
  productImplementation: false
};
writeFileSync(resolve(siteRoot, 'build-report.json'), JSON.stringify(report, null, 2)+'\n');
console.log(JSON.stringify(report, null, 2));
