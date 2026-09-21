// Exhaustive readability check across every grid configuration.
//
// Loaded by the page (a <script> tag, so it is reviewable and runnable by hand:
// open devtools and `await fitMatrix()`), and driven by test_fit.py.
//
// WHAT "READABLE" MEANS HERE, as checkable properties. For every combination of
// columns x row-height x text-mode x legibility-floor, and for every pane:
//
//   legible     the applied font size is >= the legibility floor
//   capped      ... and <= the chosen maximum
//   stable      fitting twice does not move the font size. Four earlier attempts at
//               this all oscillated or ratcheted (188 cols asked for in a 730px cell;
//               51x199; 182x40 -> 180x39 -> 178x37), every one of them because a
//               measurement taken at the current size fed the choice of the next size.
//   crisp       no CSS transform on any terminal. A transform resamples already-
//               rendered glyphs, which is what made small text blurry mush rather
//               than merely small - the original complaint.
//   predicted   cols * wRatio * font equals the real rendered grid width. If the
//               model and reality disagree, every decision built on it is luck.
//   fits        when the pane is inside the cell, it really is inside the cell
//   reachable   when it is not, the cell can actually be scrolled to the rest
//   content     in 'fit content', the cell is tall enough for the rows that HAVE
//               content (blank rows below are clipped deliberately)
//
// GROUND TRUTH IS `.xterm-screen`, NOT `host.scrollWidth`.
//
// `.xterm` fills its container, so its width is the cell's width - measuring it tells
// you nothing about the glyphs. And scrollWidth includes xterm's hidden IME textarea,
// which follows the cursor and can sit ~40px beyond the last character; using it as
// "is text clipped" reports overflow for panes that are entirely visible. xterm sizes
// `.xterm-screen` explicitly to cols x rows cells, so that is the real grid box.

const FIT_COL_MODES = ['auto', '1', '2', '3', '4', '5', '6', '8'];
const FIT_ROW_MODES = ['180', '120', '280', 'fill', 'fitcontent'];
// Text sizes to sweep: 'auto' (fit to the cell) plus explicit sizes, which must be
// honoured exactly. The old auto/fixed mode select is gone - one control now decides.
const FIT_TEXT_MODES = ['auto', '8', '14'];
const FIT_MIN_FONTS = ['6', '7', '10'];

function fitEls() {
  return {
    layout: document.getElementById('layoutMode'),
    rowH: document.getElementById('rowHeight'),
    fontSz: document.getElementById('fontSize'),
    minFont: document.getElementById('minFont'),
    syncSz: document.getElementById('syncSize'),
  };
}

function screenBox(rec) {
  const el = rec.term && rec.term.element;
  const screen = el && el.querySelector('.xterm-screen');
  return screen ? { w: screen.offsetWidth, h: screen.offsetHeight } : null;
}

// Assertions for one pane in one configuration. Returns an array of failures.
function checkPane(name, rec, ctx) {
  const problems = [];
  const bad = (what, detail) => problems.push(`${ctx.tag} ${name} ${what}: ${detail}`);
  const host = rec.termHost;
  const fs = rec.appliedFont;
  const term = rec.term && rec.term.element;
  const box = screenBox(rec);

  if (!(typeof fs === 'number' && fs >= ctx.floor - 0.01)) {
    bad('legible', `font ${fs} is below the ${ctx.floor}px floor`);
  }
  if (!(typeof fs === 'number' && fs <= ctx.cap + 0.01)) {
    bad('capped', `font ${fs} is above the ${ctx.cap}px cap`);
  }
  if (ctx.before !== undefined && ctx.before !== fs) {
    bad('stable', `font moved ${ctx.before} -> ${fs} on a second fit`);
  }
  const transform = rec.scaleEl.style.transform;
  if (transform && transform !== 'none') bad('crisp', `transform applied: ${transform}`);

  const painted = term ? term.querySelectorAll('.xterm-rows > div').length : 0;
  if (!painted) bad('rendered', 'no painted rows');

  if (!box) { bad('measurable', 'no .xterm-screen'); return problems; }

  const predictedW = rec.cols * rec.wRatio * fs;
  if (Math.abs(predictedW - box.w) > 2) {
    bad('predicted', `model says ${predictedW.toFixed(1)}px, real grid is ${box.w}px`);
  }

  const cs = getComputedStyle(host);
  const canScroll = ['auto', 'scroll'].includes(cs.overflowX)
                 || ['auto', 'scroll'].includes(cs.overflowY);

  // Horizontal: always real content, so it must be either inside or reachable.
  if (box.w > host.clientWidth + 2) {
    if (!canScroll) {
      bad('reachable-x', `grid ${box.w}px in a ${host.clientWidth}px cell, `
                       + `overflow is ${cs.overflowX} — the right-hand columns cannot be seen`);
    }
  }

  if (ctx.compact) {
    // 'fit content' sizes the cell to the rows in use; blanks below are clipped.
    const used = Math.min(usedRows(rec), rec.rows);
    const needed = used * rec.hRatio * fs;
    if (host.clientHeight + 2 < needed) {
      bad('content', `${used} rows of content need ${needed.toFixed(0)}px, `
                   + `cell is ${host.clientHeight}px`);
    }
  } else if (box.h > host.clientHeight + 2 && !canScroll) {
    bad('reachable-y', `grid ${box.h}px in a ${host.clientHeight}px cell, `
                     + `overflow is ${cs.overflowY} — the lower rows cannot be seen`);
  }
  return problems;
}

// Wait for the fit to actually finish rather than guessing a delay.
//
// A layout change settles over several frames: apply font -> xterm re-renders
// asynchronously -> re-measure -> refine. Measured at ~600ms on this machine. A fixed
// sleep shorter than that reads the PREVIOUS configuration's font and then reports
// "unstable" when the code is merely still working - which it did, for 130 checks,
// until this replaced it.
async function fitQuiesce(timeoutMs) {
  const deadline = Date.now() + (timeoutMs || 2500);
  const sample = () => [...panes.values()].map((r) => r.appliedFont).join(',');
  let previous = null, same = 0;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 80));
    const now = sample();
    same = now === previous ? same + 1 : 0;
    previous = now;
    if (same >= 3) return true;        // three identical samples: at rest
  }
  return false;                        // ran out of patience; caller asserts anyway
}

async function fitMatrix(options) {
  const opts = options || {};
  const settle = opts.settle || 220;
  const afterFit = opts.afterFit || 120;   // the post-font-change rAF must land
  const E = fitEls();
  const restore = {
    layout: E.layout.value, rowH: E.rowH.value, fontSz: E.fontSz.value,
    minFont: E.minFont.value, sync: E.syncSz.checked,
  };
  // Pane-size sync rewrites the agent's geometry mid-run, which would change cols
  // underneath the matrix. Fitting is what is under test here.
  E.syncSz.checked = false;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const failures = [];
  let checked = 0;

  for (const minFont of (opts.minFonts || FIT_MIN_FONTS)) {
    for (const zoom of (opts.textModes || FIT_TEXT_MODES)) {
      for (const rowH of (opts.rowModes || FIT_ROW_MODES)) {
        for (const cols of (opts.colModes || FIT_COL_MODES)) {
          E.minFont.value = minFont; E.fontSz.value = zoom;
          E.rowH.value = rowH; E.layout.value = cols;
          applyLayoutPrefs();
          await sleep(settle);
          const settled = await fitQuiesce();

          const before = new Map();
          panes.forEach((rec, name) => before.set(name, rec.appliedFont));
          // Once at rest, fitting again must change nothing. This is the property that
          // four earlier attempts failed: each pass moved the answer.
          panes.forEach((rec) => applyFit(rec));
          await sleep(afterFit);
          await fitQuiesce(800);
          if (!settled) failures.push(`${cols}col/${rowH}/${zoom}/min${minFont}: `
                                    + 'never reached a steady state');

          const ctx = {
            tag: `${cols}col/${rowH}/${zoom}/min${minFont}`,
            // An explicit size is exact: it is both the floor and the cap.
            floor: zoom === 'auto' ? parseFloat(minFont) : parseFloat(zoom),
            cap: zoom === 'auto' ? HARD_MAX_FONT : parseFloat(zoom),
            compact: rowH === 'fitcontent',
          };
          for (const [name, rec] of panes) {
            if (rec.minimized) continue;
            checked++;
            failures.push(...checkPane(name, rec, { ...ctx, before: before.get(name) }));
          }
        }
      }
    }
  }

  E.layout.value = restore.layout; E.rowH.value = restore.rowH;
  E.fontSz.value = restore.fontSz; E.minFont.value = restore.minFont;
  E.syncSz.checked = restore.sync;
  applyLayoutPrefs();

  return {
    configurations: (opts.minFonts || FIT_MIN_FONTS).length
                  * (opts.textModes || FIT_TEXT_MODES).length
                  * (opts.rowModes || FIT_ROW_MODES).length
                  * (opts.colModes || FIT_COL_MODES).length,
    paneChecks: checked,
    failed: failures.length,
    failures: failures.slice(0, 30),
  };
}

// One configuration, reported in the numbers a human wants to read.
async function fitProbe(cols, rowH, textSize, minFont) {
  const E = fitEls();
  E.layout.value = cols; E.rowH.value = rowH;
  E.fontSz.value = textSize; E.minFont.value = minFont;
  applyLayoutPrefs();
  await new Promise((r) => setTimeout(r, 420));
  const rows = [];
  for (const [name, rec] of panes) {
    const host = rec.termHost, box = screenBox(rec);
    rows.push({
      name, pane: `${rec.cols}x${rec.rows}`,
      cell: `${host.clientWidth}x${host.clientHeight}`,
      grid: box ? `${box.w}x${box.h}` : '?',
      font: rec.appliedFont,
      charPx: rec.wRatio ? +(rec.wRatio * rec.appliedFont).toFixed(2) : null,
      scrolls: host.classList.contains('scrolls'),
      note: rec.headEls.fit.textContent,
    });
  }
  return {
    gridCols: getComputedStyle(document.getElementById('grid')).getPropertyValue('--cols').trim(),
    panes: rows,
  };
}
