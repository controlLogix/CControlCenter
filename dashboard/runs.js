/* Runs — what is being worked on right now, and what is waiting on you.
 *
 * WHAT THIS ANSWERS. Every other view shows you agents: panes scrolling, a board of
 * cards, a journal of what was said. None of them answered the question you actually
 * have while work is in flight — is this run finished, and if not, what is holding it
 * and on whom. That answer lived only in `agentmux run status` in a terminal.
 *
 * THE BLOCKING LINE IS THE POINT. A job table gets you there eventually; one sentence
 * ("a3f19c/2 submitted, waiting on netcap-reviewer") gets you there at a glance, and
 * that difference is what separates a status surface from a log. It is computed
 * server-side from the same fold the gate itself uses, so it can never disagree with
 * the decision the gate will make.
 *
 * THE REVIEW BLOCK IS A GATE, NOT A REPORT. When every job is verified but the run is
 * not complete, this view asks you to read the diff and say yes. A reviewer verdict
 * answers "was the job done"; it cannot answer "was that the right job", because the
 * same orchestrator wrote the brief the reviewer checked against. You are the only one
 * who can answer the second, so an orchestrated run stops here.
 *
 * POLLING IS SPLIT. The list endpoint already folds every run, so the 5s poll draws
 * every summary and blocking line from one request; a run's job table and its diff are
 * fetched only for cards you have actually opened. There is no SSE, because the pane
 * is already streamed — clicking an agent name drops you into it.
 */
(() => {
  'use strict';

  let api = null;
  let snap = null;                 // the last /api/runs payload
  const details = new Map();       // run id -> detail payload, for open cards only
  const diffs = new Map();         // run id -> diff payload, for open cards only
  const open = new Set();          // run ids whose card is expanded
  const busy = new Set();          // run ids with a review decision in flight
  const drafts = new Map();        // run id -> half-typed review note
  let notice = '';
  let signature = null;            // what the DOM was last built from
  const root = document.getElementById('viewRuns');
  const badge = document.getElementById('badgeRuns');

  const PREF_KEY = 'ccc.runs.v1';
  function prefs() {
    try { return JSON.parse(localStorage.getItem(PREF_KEY) || '{}') || {}; }
    catch (_) { return {}; }
  }
  function savePrefs(next) {
    try { localStorage.setItem(PREF_KEY, JSON.stringify(next)); } catch (_) {}
  }

  function clock(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? String(iso).slice(0, 19) : d.toLocaleTimeString();
  }

  function chip(text, kind) {
    const node = api.el('span', 'run-chip' + (kind ? ' ' + kind : ''), text);
    return node;
  }

  // ── what a run is asking of you ───────────────────────────────────────────
  //
  // Ordered by how much it wants your attention, because the badge and the sort both
  // read it and they must not disagree about which run is the urgent one.
  function attention(run) {
    if (run.escalated && run.escalated.length) return 'escalated';
    if (run.review && run.review.state === 'stale') return 'stale';
    if (run.review && run.review.state === 'pending') return 'review';
    return '';
  }

  function updateBadge() {
    if (!badge) return;
    const wanting = (snap && snap.runs || []).filter((r) => attention(r));
    badge.hidden = wanting.length === 0;
    badge.textContent = String(wanting.length);
    badge.title = wanting.length
      ? wanting.map((r) => `${r.run}: ${attention(r)}`).join(' · ') : '';
  }

  // ── the review gate ───────────────────────────────────────────────────────

  function reviewBlock(run) {
    const {el} = api;
    const state = (run.review && run.review.state) || null;
    if (!state) return null;

    const box = el('div', 'run-review ' + state);

    if (state === 'approved') {
      box.appendChild(el('div', 'run-review-head',
        `Approved by ${run.review.by || 'you'} at ${clock(run.review.at)} — the`
        + ' orchestrator may complete this run.'));
      if (run.review.note) box.appendChild(el('div', 'run-review-note', run.review.note));
      return box;
    }
    if (state === 'changes') {
      box.appendChild(el('div', 'run-review-head',
        `Changes requested at ${clock(run.review.at)}.`));
      if (run.review.note) box.appendChild(el('div', 'run-review-note', run.review.note));
      return box;
    }
    if (state === 'stale') {
      // The approval pinned digests and something moved since. Saying "approved"
      // here would be a lie about which bytes you saw, which is the whole reason
      // the digests are pinned at all.
      box.appendChild(el('div', 'run-review-head',
        `Your approval no longer covers this work — ${run.review.drift.length} file(s)`
        + ' changed after you approved it. Review again.'));
      box.appendChild(el('div', 'run-review-note', run.review.drift.join(', ')));
    } else {
      box.appendChild(el('div', 'run-review-head',
        `All ${run.jobs} job(s) verified. Read the diff and decide — the orchestrator`
        + ' will not complete this run until you do.'));
    }

    const diff = diffs.get(run.run);
    const pane = el('pre', 'run-diff');
    if (!diff) {
      pane.textContent = 'Loading the diff…';
    } else if (!diff.files.length) {
      pane.textContent = diff.note;
    } else if (!diff.diff.trim()) {
      pane.textContent = 'No changes against the commit this run started from, for the'
        + ' files it submitted. Check the job table below — that is what you would see'
        + ' if the run ended up reverting its own work.';
    } else {
      pane.textContent = diff.diff + (diff.truncated ? '\n\n… diff truncated.' : '');
    }
    // A caveat about WHAT is being compared belongs beside the diff, not instead of
    // it. Someone approving a diff needs to know it is measured from this run's own
    // starting point rather than from whatever HEAD happens to be now.
    if (diff && diff.note && diff.files.length) {
      box.appendChild(el('div', 'run-diff-rejected', diff.note));
    }
    const files = el('div', 'run-diff-files');
    if (diff && diff.files.length) {
      files.appendChild(el('span', 'run-diff-label', 'files: '));
      files.appendChild(el('span', '', diff.files.join(', ')));
      if (diff.base) {
        files.appendChild(el('div', '',
          `since ${diff.base.slice(0, 9)} — the commit this run started from`));
      }
    }
    if (diff && diff.rejected && diff.rejected.length) {
      // A submitted path is agent-authored text and the server refused these. Say so
      // rather than quietly diffing a subset — an unexplained gap in a review is the
      // kind of thing that gets approved anyway.
      files.appendChild(el('div', 'run-diff-rejected',
        `not shown (path refused): ${diff.rejected.join(', ')}`));
    }
    if (files.childNodes.length) box.appendChild(files);
    box.appendChild(pane);

    // The note survives a re-render. A poll landing mid-sentence used to take the
    // textarea with it, which is the fastest way to teach someone not to write
    // anything in the box you asked them to write in.
    const note = document.createElement('textarea');
    note.className = 'run-note';
    note.rows = 2;
    note.placeholder = 'optional note — required when requesting changes';
    note.value = drafts.get(run.run) || '';
    note.addEventListener('input', () => drafts.set(run.run, note.value));
    box.appendChild(note);

    const acts = el('div', 'run-acts');
    const approve = el('button', 'btn primary', 'Approve — the orchestrator may close it');
    const reject = el('button', 'btn', 'Request changes');
    approve.disabled = reject.disabled = busy.has(run.run);
    approve.addEventListener('click', () => decide(run, 'approved', note.value));
    reject.addEventListener('click', () => {
      if (!note.value.trim()) {
        notice = 'Say what needs changing — a rejection with no reason gives the'
          + ' orchestrator nothing to act on.';
        render();
        return;
      }
      decide(run, 'changes', note.value);
    });
    acts.appendChild(approve);
    acts.appendChild(reject);
    box.appendChild(acts);
    return box;
  }

  async function decide(run, decision, note) {
    if (busy.has(run.run)) return;
    if (decision === 'approved') {
      const what = run.request ? `\n\n${run.request}` : '';
      if (!window.confirm(
        `Approve run ${run.run}?${what}\n\n${run.jobs} job(s), all verified. The`
        + ' orchestrator will complete the run and close its board cards.')) return;
    }
    busy.add(run.run);
    notice = '';
    render();
    try {
      await api.post(`api/runs/${encodeURIComponent(run.run)}/review`,
                     {decision, note: note || ''});
      notice = decision === 'approved'
        ? `Run ${run.run} approved.`
        : `Changes requested on ${run.run}.`;
      details.delete(run.run);
      diffs.delete(run.run);
      drafts.delete(run.run);        // it has been recorded; it is no longer a draft
    } catch (err) {
      notice = `Could not record that: ${err.message}`;
    } finally {
      busy.delete(run.run);
    }
    await refresh();
  }

  // ── the job table ─────────────────────────────────────────────────────────

  function jobTable(detail) {
    const {el, markAgent} = api;
    const table = el('table', 'run-jobs');
    const body = document.createElement('tbody');
    table.appendChild(body);
    const head = el('tr', '');
    for (const label of ['job', 'state', 'worker', 'reviewer', 'attempts', 'last', '']) {
      head.appendChild(el('th', '', label));
    }
    body.appendChild(head);
    for (const job of detail.jobs) {
      const row = el('tr', 'job ' + job.state);
      row.appendChild(el('td', 'j-id', job.job));
      row.appendChild(el('td', 'j-state', job.state));
      // markAgent is the whole reuse of the live-marking system: a name here becomes
      // clickable the moment that agent is running and goes plain again when it is
      // torn down, without this table re-rendering.
      row.appendChild(markAgent(el('td', 'j-who', job.worker || '—'), job.worker));
      row.appendChild(markAgent(el('td', 'j-who', job.reviewer || '—'), job.reviewer));
      // `tries=2` means nothing without the ceiling, and the ceiling is MAX_ATTEMPTS
      // in run.py — served in the payload rather than duplicated here, so raising it
      // there cannot leave this reading 2/3 forever.
      row.appendChild(el('td', 'j-tries', `${job.attempts}/${detail.maxAttempts}`));
      row.appendChild(el('td', 'j-last', clock(job.last)));
      const flags = el('td', 'j-flags');
      if (job.stale) flags.appendChild(chip('agent gone', 'bad'));
      // One chip for where the job got to, not a running tally of everywhere it has
      // been: "verified" already implies it was briefed and submitted, and saying all
      // three makes the row longer without making it say more.
      if (job.state === 'verified') {
        flags.appendChild(chip(`verified · ${job.verdicts} verdict(s)`, 'ok'));
      } else if (job.submission) flags.appendChild(chip('submitted', ''));
      else if (job.brief) flags.appendChild(chip('briefed', ''));
      if (job.task) flags.appendChild(chip(job.task, ''));
      row.appendChild(flags);
      body.appendChild(row);
    }
    return table;
  }

  // ── rendering ─────────────────────────────────────────────────────────────

  // Put the caret back where a needed redraw took it from.
  function restoreTyping(typing) {
    if (!typing || !typing.run) return;
    for (const card of root.querySelectorAll('details.run')) {
      if (card.querySelector('.run-id')?.textContent !== typing.run) continue;
      const note = card.querySelector('.run-note');
      if (!note) return;
      note.focus();
      try { note.setSelectionRange(typing.start, typing.end); } catch (_) {}
      return;
    }
  }

  // WHAT THE DOM WAS BUILT FROM.
  //
  // This view polls every 5 seconds and draws itself with replaceChildren, and for
  // most of those polls nothing has changed. Rebuilding anyway detached the button
  // you were reaching for and blew away the note you were typing — you cannot use a
  // review form that reconstructs itself under your hands twice a minute. So the
  // render is skipped outright when the answer is identical to the one on screen.
  // Everything the DOM depends on has to appear here, or a real change will be
  // silently swallowed; that is a worse failure than a needless redraw, so the
  // signature deliberately includes the loading and in-flight states too.
  function currentSignature() {
    return JSON.stringify([
      snap && snap.runs, snap && snap.tmux, notice, prefs().showComplete,
      [...open].sort(),
      [...busy].sort(),
      [...details.keys()].sort().map((k) => [k, details.get(k).jobs]),
      [...diffs.keys()].sort(),
    ]);
  }

  function render(force) {
    if (!root || !snap) return;
    const next = currentSignature();
    if (!force && next === signature) return;
    signature = next;
    const {el} = api;
    const saved = prefs();
    // Where the caret was, so a redraw that IS needed does not eject you from the
    // box mid-word either.
    const active = document.activeElement;
    const typing = active && active.classList.contains('run-note')
      ? {start: active.selectionStart, end: active.selectionEnd,
         run: active.closest('details.run')?.querySelector('.run-id')?.textContent}
      : null;
    root.replaceChildren();

    const head = el('div', 'runs-head');
    head.appendChild(el('h2', '', 'Runs'));
    const counts = (snap.runs || []).reduce((acc, r) => {
      acc[r.complete ? 'done' : 'open'] += 1;
      if (attention(r)) acc.wanting += 1;
      return acc;
    }, {open: 0, done: 0, wanting: 0});
    head.appendChild(el('span', 'runs-count',
      `${counts.open} open · ${counts.done} complete`
      + (counts.wanting ? ` · ${counts.wanting} waiting on you` : '')));
    if (!snap.tmux) {
      // stale is derived from the live roster, so an unreachable tmux means the
      // question was not answered. Saying nothing would let the table read as
      // "every agent alive", which is the exact lie the flag exists to prevent.
      head.appendChild(chip('tmux unreachable — liveness unknown', 'warn'));
    }
    const showDone = document.createElement('label');
    showDone.className = 'runs-filter';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = saved.showComplete !== false;
    box.addEventListener('change', () => {
      savePrefs(Object.assign(prefs(), {showComplete: box.checked}));
      render(true);
    });
    showDone.appendChild(box);
    showDone.appendChild(document.createTextNode(' show completed'));
    head.appendChild(showDone);
    root.appendChild(head);

    if (notice) root.appendChild(el('div', 'runs-notice', notice));

    const runs = (snap.runs || []).filter((r) => box.checked || !r.complete);
    if (!runs.length) {
      root.appendChild(el('div', 'runs-empty',
        snap.runs && snap.runs.length
          ? 'No open runs. Tick "show completed" to see finished ones.'
          : 'No runs yet. One appears here as soon as `agentmux run start` opens it.'));
      updateBadge();
      restoreTyping(typing);
      return;
    }

    for (const run of runs) {
      const card = api.collapsible(`runs:${run.run}`, 'card run', !run.complete);
      const summary = document.createElement('summary');
      summary.appendChild(el('span', 'run-id', run.run));
      if (run.complete && run.forced) summary.appendChild(chip('COMPLETE (FORCED)', 'bad'));
      else if (run.complete) summary.appendChild(chip('complete', 'ok'));
      else summary.appendChild(chip('open', 'warn'));
      summary.appendChild(el('span', 'run-count', `${run.verified}/${run.jobs} verified`));
      const want = attention(run);
      if (want === 'escalated') summary.appendChild(chip('parked for you', 'bad'));
      else if (want === 'stale') summary.appendChild(chip('approval out of date', 'bad'));
      else if (want === 'review') summary.appendChild(chip('waiting on your review', 'warn'));
      else if (run.review && run.review.state === 'approved') {
        summary.appendChild(chip('approved', 'ok'));
      }
      summary.appendChild(el('span', 'spacer'));
      summary.appendChild(el('span', 'run-time', clock(run.last)));
      card.appendChild(summary);

      if (run.request) card.appendChild(el('div', 'run-request', run.request));
      if (run.blockingText) {
        card.appendChild(el('div', 'run-blocking', `Blocking: ${run.blockingText}`));
      }

      const review = reviewBlock(run);
      if (review) card.appendChild(review);

      const detail = details.get(run.run);
      if (detail) card.appendChild(jobTable(detail));
      else card.appendChild(el('div', 'run-loading', 'Loading jobs…'));

      // Only an OPEN card costs a detail request. The summary above is already drawn
      // from the list payload, so a collapsed run is free.
      card.addEventListener('toggle', () => {
        if (card.open) { open.add(run.run); loadDetail(run.run); }
        else { open.delete(run.run); }
      });
      if (card.open) {
        open.add(run.run);
        // A card that starts open never fires `toggle`, so without this its job table
        // waited for the next 5s poll - you opened Runs and stared at "Loading jobs…"
        // for five seconds on the one card you came to read.
        if (!details.has(run.run)) loadDetail(run.run);
      }
      root.appendChild(card);
    }
    updateBadge();
    restoreTyping(typing);
  }

  // ── fetching ──────────────────────────────────────────────────────────────

  // In-flight guard. render() asks for the detail of every open card, and loadDetail
  // ends by rendering, so without this an open card would chase its own tail.
  const loading = new Set();

  async function loadDetail(id) {
    if (loading.has(id)) return;
    loading.add(id);
    try {
      details.set(id, await api.getJSON(`api/runs/${encodeURIComponent(id)}`));
    } catch (_) { /* the summary still renders; a failed detail is not fatal */ }
    const run = (snap && snap.runs || []).find((r) => r.run === id);
    const wants = run && run.review
      && (run.review.state === 'pending' || run.review.state === 'stale');
    if (wants && !diffs.has(id)) {
      try {
        diffs.set(id, await api.getJSON(`api/runs/${encodeURIComponent(id)}/diff`));
      } catch (_) { /* the decision buttons still work without it */ }
    }
    loading.delete(id);
    render();
  }

  async function refresh() {
    if (!root) return;
    try {
      snap = await api.getJSON('api/runs?limit=30');
      notice = notice && notice.startsWith('Runs unavailable') ? '' : notice;
    } catch (err) {
      if (!snap) {
        root.replaceChildren(api.el('div', 'runs-notice',
          `Runs unavailable: ${err.message}`));
        return;
      }
      notice = `Runs unavailable: ${err.message}`;
    }
    render();
    for (const id of open) loadDetail(id);
  }

  // A cheap poll that runs even when the view is hidden, so the rail badge can tell
  // you a run is waiting on you while you are looking at something else. Same shape
  // as the feed's background poll in app.js, and the same rationale: the endpoint is
  // one fold of files already in page cache, and a notification you never see is not
  // a notification.
  async function pollBadge() {
    try {
      snap = await api.getJSON('api/runs?limit=30');
      updateBadge();
    } catch (_) { /* silent: the view itself reports failures */ }
  }


  // ── Settings -> Orchestration ─────────────────────────────────────────────
  //
  // Registered from here rather than app.js or teams.js, so neither has to change.
  //
  // WHAT THIS CARD DELIBERATELY DOES NOT DO: start anything. A settings card that
  // launches a process is a category error - settings describe what is permitted, and
  // the act belongs where you can watch it, which is the Runs view. And there is no
  // force-complete control anywhere on this page: a page that can force-complete
  // launders a failed review into a closed run, which is exactly what run.py exists
  // to prevent.
  const ORCH_SETTINGS = [
    ['orchestratorEnabled', 'Allow a CCC orchestrator (true/false)', 'bool'],
    ['orchestratorAgent', 'Agent definition to use (blank = ccc-orchestrator)', 'name'],
    ['orchestratorScope', 'Scope: goal, epic or queue', 'choice', ['goal', 'epic', 'queue']],
    ['orchestratorNotify', 'Desktop notification on escalation (true/false)', 'bool'],
    ['orchestratorNotifyCommand', 'Command to run for notices (blank = none)', 'text'],
  ];

  async function loadOrchCard() {
    const root = document.getElementById('orchCard');
    if (!root || !api) return;
    const {el, getJSON, post, settingEditor} = api;
    let meta;
    try {
      // /api/board/meta already carries config and is far lighter than the board.
      meta = await getJSON('api/board/meta');
    } catch (err) {
      root.replaceChildren(el('p', 'error', `Orchestration settings unavailable: ${err.message}`));
      return;
    }
    const cfg = meta.config || {};
    root.replaceChildren();
    root.appendChild(el('p', 'muted',
      'An orchestrator opens runs, spawns a worker and a cross-model reviewer, briefs '
      + 'them, and collects verdicts without you. It stops before completing a run and '
      + 'waits for your approval in Runs \u2014 a reviewer can say the job was done, but '
      + 'only you can say it was the right job.'));

    for (const [key, label, kind, choices] of ORCH_SETTINGS) {
      root.appendChild(settingEditor('board', {key, label, value: cfg[key]}, loadOrchCard, {
        save: async (raw) => {
          let value = raw;
          if (kind === 'bool') {
            if (!['true', 'false'].includes(raw)) throw new Error('Enter true or false');
            value = raw === 'true';
          } else if (kind === 'choice' && !choices.includes(raw)) {
            throw new Error(`Enter one of: ${choices.join(', ')}`);
          } else if (kind === 'name' && raw && !/^[A-Za-z0-9_.-]{1,64}$/.test(raw)) {
            throw new Error('Letters, digits, dot, underscore or dash only');
          }
          await post('api/board/config', {name: key, value});
        },
      }));
    }

    // THE PRECONDITIONS, spelled out. Without this you cannot tell the difference
    // between "not allowed" and "broken", and guessing which is a bad use of anyone's
    // afternoon.
    const checks = el('div', 'orch-checks');
    checks.appendChild(el('h4', '', 'Before an orchestrator can start'));
    // THREE states, not two. Settings can be opened before the Runs poll has ever
    // run, and rendering "not yet known" as "failed" is the same lie as reporting an
    // unreachable tmux as "nobody is stale" - it sends you hunting a fault that does
    // not exist. null means unknown, and says so.
    const rows = [
      [cfg.orchestratorEnabled === true, 'Orchestration is switched on above'],
      [snap ? !!snap.tmux : null, 'tmux is reachable (liveness can be checked)'],
      [true, 'The agent definition resolves from .agentmux/agents/ on disk'],
      [snap ? !(snap.runs || []).some((r) => attention(r) === 'escalated') : null,
       'No run is currently parked waiting for you'],
    ];
    for (const [state, text] of rows) {
      const cls = state === null ? ' unknown' : state ? ' ok' : ' bad';
      const row = el('div', 'orch-check' + cls);
      row.appendChild(el('span', 'orch-mark',
        state === null ? '?' : state ? '\u2713' : '\u00d7'));
      row.appendChild(el('span', '', text
        + (state === null ? ' \u2014 not checked yet; open Runs' : '')));
      checks.appendChild(row);
    }
    root.appendChild(checks);

    // The terminal equivalents, as the Auth card already does. Shown, never run.
    const how = el('div', 'orch-how');
    how.appendChild(el('h4', '', 'Starting one'));
    how.appendChild(el('p', 'muted',
      'Deliberately a terminal action. Starting a process that writes to this '
      + 'repository is not a thing a web page should do quietly.'));
    for (const cmd of [
      'agentmux orchestrator start --request "<what it should do>"',
      'agentmux orchestrator status',
      'agentmux orchestrator stop',
    ]) {
      const line = el('div', 'orch-cmd');
      line.appendChild(el('code', '', cmd));
      const copy = el('button', 'btn small', 'copy');
      copy.addEventListener('click', () => {
        navigator.clipboard?.writeText(cmd).catch(() => {});
      });
      line.appendChild(copy);
      how.appendChild(line);
    }
    root.appendChild(how);
  }

  window.addEventListener('ccc:ready', () => {
    api = window.CCC;
    api.registerView('runs', refresh, 5000);
    api.registerCard('settings', loadOrchCard, 0);
    // NOT fired at boot. A request issued while the page is still loading competes
    // with the terminal streams and every panel's first fetch for the browser's
    // per-origin connections, and it buys a badge nobody is looking at yet — the
    // Runs view is not even on screen. It measurably delayed other panels' first
    // paint. The first badge poll waits out the load instead.
    setTimeout(() => {
      pollBadge();
      setInterval(() => { if (root && root.hidden) pollBadge(); }, 30000);
    }, 4000);
  }, {once: true});
})();
