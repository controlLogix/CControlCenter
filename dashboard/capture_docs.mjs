// Re-capture the five screenshots in docs/images/ against a real dashboard.
//
// WHY THIS EXISTS. The screenshots show the product's name in the rendered UI, so
// a rebrand cannot fix them with a text edit - they have to be taken again. Doing
// that by hand is unrepeatable and quietly goes stale; test_e2e.mjs already brings
// up a real dashboard on an ephemeral port with a throwaway AGENTMUX_HOME and
// navigates every view, so this borrows that machinery and adds the one thing it
// never had: page.screenshot().
//
// NOT part of run_tests.sh. Five PNGs is ~450 KB of binary churn per run, which is
// repo poison in a gate that runs constantly. This is an operator command.
//
// Usage (via capture_docs.sh, which builds the server and the seeded home):
//     node dashboard/capture_docs.mjs <baseURL> <playwrightDir> [outDir]
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const [baseURL, playwrightDir, outDirArg] = process.argv.slice(2);
if (!baseURL || !playwrightDir) {
  console.error('usage: node dashboard/capture_docs.mjs <baseURL> <playwrightDir> [outDir]');
  process.exit(2);
}
const outDir = resolve(outDirArg || 'docs/images');
mkdirSync(outDir, { recursive: true });

// Same shape as test_e2e.mjs:29 - createRequire against the directory, not an
// ESM import of index.js, which resolves to a module without the named exports.
const { firefox } = createRequire(import.meta.url)(playwrightDir);

// Same browser and viewport as the e2e suite, so a screenshot looks like what that
// suite asserts on rather than a second, differently-sized reality.
const browser = await firefox.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1400, height: 950 } });
const page = await context.newPage();

const problems = [];
page.on('pageerror', err => problems.push(String(err)));

await page.goto(baseURL, { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.nav-item[data-view="terminals"]');

const show = async (view) => {
  await page.click(`.nav-item[data-view="${view}"]`);
  await page.waitForSelector(`#view${view[0].toUpperCase() + view.slice(1)}:not([hidden])`);
};
const tab = async (view, panel) => {
  await page.click(`[data-tabs="${view}"] .subtab[data-panel="${panel}"]`);
  await page.waitForSelector(`#view${panel[0].toUpperCase() + panel.slice(1)}:not([hidden])`);
};

// Each shot names the file it replaces. Order matters only in that `settings` opens
// a card first, so it is taken last.
const SHOTS = [
  ['board.png', async () => { await show('board'); }],
  ['iiot.png', async () => { await show('iiot'); }],
  ['runs-view.png', async () => { await show('runs'); }],
  ['status-feed.png', async () => { await show('status'); await tab('status', 'feed'); }],
  ['settings-orchestration.png', async () => {
    await show('settings');
    // The orchestration card is what the file is named for; open it so the shot
    // shows the settings rather than a column of collapsed summaries.
    await page.evaluate(() => {
      for (const d of document.querySelectorAll('#viewSettings details')) {
        if (/orchestrat/i.test(d.textContent || '')) d.open = true;
      }
    });
  }],
];

let taken = 0;
for (const [name, go] of SHOTS) {
  try {
    await go();
    // Let the view settle: these panels poll, and a shot taken mid-render shows a
    // spinner or a half-filled table, which is worse than an out-of-date picture.
    await page.waitForTimeout(900);
    const path = resolve(outDir, name);
    await page.screenshot({ path, fullPage: false });
    console.log('  captured  ' + name);
    taken++;
  } catch (err) {
    console.error('  FAILED    ' + name + ' - ' + err.message);
  }
}

await browser.close();

if (problems.length) {
  console.error('page errors while capturing:\n  ' + problems.join('\n  '));
}
console.log(`\ncaptured ${taken} of ${SHOTS.length} into ${outDir}`);
process.exit(taken === SHOTS.length ? 0 : 1);
