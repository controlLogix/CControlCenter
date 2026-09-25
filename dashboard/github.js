/* GitHub: account, repositories, and the two writes worth doing from a dashboard.
 *
 * SIGN-IN, WITHOUT A SECRET EVER TOUCHING THIS PAGE. The server drives
 * `gh auth login --web`, which is GitHub's device flow: it mints a one-time code,
 * you type that code at github.com/login/device in your own browser, and GitHub
 * hands the token to `gh`, which puts it in `gh`'s own credential store. The code
 * shown here is not a secret - it is worthless without your GitHub session - and
 * the token never passes through this process or this page. That is the same rule
 * the rest of the dashboard follows for every other credential.
 *
 * WHAT "FULL ACCESS" MEANS AND DOES NOT. Creating a repository and opening an
 * issue are here, each behind a confirmation and each journalled. Pushing, merging,
 * force-pushing and deleting are not, and that is deliberate: those are the
 * operations where an accidental click cannot be walked back, and a terminal with
 * the working tree in front of you is the right place for them. Everything else on
 * the panel is a read.
 */
(() => {
  'use strict';

  let api, loading = false;
  let account = null, login = null, data = null;
  let actorValue = '';
  let notice = '';
  let pollTimer = null;

  // ── the account card ───────────────────────────────────────────────────────

  function accountCard() {
    const {el} = api;
    const card = el('article', 'gh-account');
    card.appendChild(el('h3', '', 'Account'));

    if (!account.cli) {
      card.appendChild(el('p', 'error', account.message));
      card.appendChild(el('code', 'act-cmd', account.command));
      return card;
    }

    const line = el('p', 'field-state');
    if (account.authenticated) {
      line.dataset.state = 'ok';
      line.textContent = `Signed in as ${account.login}`
        + (account.name ? ` (${account.name})` : '')
        + ` on ${account.hostname}`;
    } else {
      line.dataset.state = 'bad';
      line.textContent = 'Not signed in.';
    }
    card.appendChild(line);

    if (account.authenticated) {
      card.appendChild(el('p', 'muted', account.scopes.length
        ? `Token scopes: ${account.scopes.join(', ')}`
        : 'Token scopes: none reported. Writes will be refused.'));
      if (account.rate) {
        const reset = new Date(account.rate.reset * 1000).toLocaleTimeString();
        card.appendChild(el('p', 'muted',
          `API budget: ${account.rate.remaining} of ${account.rate.limit} left, resets ${reset}.`));
      }
    }
    if (account.message) card.appendChild(el('p', 'notice', account.message));

    // -- the sign-in flow -----------------------------------------------------
    const bar = el('div', 'row');
    const actor = el('input', 'rin');
    actor.type = 'text'; actor.maxLength = 64; actor.size = 14;
    actor.placeholder = 'Operator / actor';
    actor.value = actorValue;
    actor.setAttribute('aria-label', 'Operator name');
    actor.addEventListener('input', () => { actorValue = actor.value.trim(); });
    bar.appendChild(actor);

    if (!account.authenticated) {
      const start = el('button', 'btn', 'Sign in to GitHub');
      start.disabled = !account.can_login || (login && login.state !== 'idle' && login.state !== 'error' && login.state !== 'done');
      start.addEventListener('click', signIn);
      bar.appendChild(start);
    } else {
      const out = el('button', 'btn', 'Sign out');
      out.addEventListener('click', signOut);
      bar.appendChild(out);
    }
    const again = el('button', 'btn', 'Check again');
    again.addEventListener('click', load);
    bar.appendChild(again);
    card.appendChild(bar);

    if (!account.can_login && !account.authenticated) {
      card.appendChild(el('p', 'notice',
        'This host cannot run the interactive flow, so there is no button for it rather than one that does nothing. Run this in a terminal instead:'));
      card.appendChild(el('code', 'act-cmd', login ? login.command : 'gh auth login --web'));
    }

    if (login && login.code) {
      const box = el('div', 'gh-code');
      box.appendChild(el('p', '', 'One-time code — type this at GitHub, then come back:'));
      const code = el('p', 'gh-code-value', login.code);
      code.title = 'This code is useless without your own GitHub session. It is not a secret.';
      box.appendChild(code);
      const link = el('a', 'gh-code-link', login.url);
      link.href = login.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      box.appendChild(link);
      const copy = el('button', 'btn', 'Copy code');
      copy.addEventListener('click', () => {
        navigator.clipboard.writeText(login.code).then(
          () => { notice = 'Code copied.'; render(); },
          () => { notice = 'Could not reach the clipboard; type the code above.'; render(); });
      });
      const cancel = el('button', 'btn', 'Cancel');
      cancel.addEventListener('click', async () => {
        try { login = await api.post('api/github/cancel', {}); render(); }
        catch (err) { notice = err.message; render(); }
      });
      const row = el('div', 'row');
      row.append(copy, cancel);
      box.appendChild(row);
      card.appendChild(box);
    } else if (login && login.state === 'starting') {
      card.appendChild(el('p', 'muted', 'Asking GitHub for a code…'));
    }
    if (login && login.error) card.appendChild(el('p', 'error', login.error));

    return card;
  }

  async function signIn() {
    if (!actorValue) { notice = 'Enter your operator name first; the sign-in is journalled.'; render(); return; }
    try {
      login = await api.post('api/github/login', {actor: actorValue});
      notice = '';
      render();
      watchLogin();
    } catch (err) { notice = err.message; render(); }
  }

  async function signOut() {
    if (!actorValue) { notice = 'Enter your operator name first; the sign-out is journalled.'; render(); return; }
    if (!window.confirm('Sign this machine out of GitHub? Every tool using gh loses its credential, not just this page.')) return;
    try {
      const out = await api.post('api/github/logout', {actor: actorValue});
      account = out.account;
      notice = 'Signed out.';
      render();
    } catch (err) { notice = err.message; render(); }
  }

  // The device flow finishes on GitHub's side, not ours, so the page has to watch
  // for it. Stops the moment it resolves - a poll that outlives what it was waiting
  // for is how a panel ends up hammering an endpoint forever.
  function watchLogin() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const out = await api.getJSON('api/github/auth');
        login = out.login;
        account = out.account;
        if (['done', 'error', 'idle'].includes(login.state)) {
          clearInterval(pollTimer);
          pollTimer = null;
          if (login.state === 'done') notice = 'Signed in.';
          load();
          return;
        }
        render();
      } catch (_) { /* a blip mid-flow is not worth tearing the panel down for */ }
    }, 2000);
  }

  // ── writes ─────────────────────────────────────────────────────────────────

  function createRepoCard() {
    const {el} = api;
    const box = el('details', 'subcard');
    box.appendChild(el('summary', '', 'Create a repository'));
    if (!account.authenticated) {
      box.appendChild(el('p', 'muted', 'Sign in first.'));
      return box;
    }
    const form = el('div', 'row wrap');
    const owner = el('input', 'rin');
    owner.size = 12; owner.placeholder = `owner (default ${account.login})`;
    owner.setAttribute('aria-label', 'Owner');
    const name = el('input', 'rin');
    name.size = 16; name.placeholder = 'repository name';
    name.setAttribute('aria-label', 'Repository name');
    const visibility = el('select', '');
    for (const value of ['private', 'public', 'internal']) {
      const option = el('option', '', value);
      option.value = value;
      visibility.appendChild(option);
    }
    visibility.setAttribute('aria-label', 'Visibility');
    const description = el('input', 'rin');
    description.size = 26; description.placeholder = 'description (optional)';
    description.setAttribute('aria-label', 'Description');
    const go = el('button', 'btn', 'Create');
    form.append(owner, name, visibility, description, go);
    box.appendChild(form);
    box.appendChild(el('p', 'hint', 'Defaults to private. The repository is created empty — nothing in this working tree is pushed.'));

    go.addEventListener('click', async () => {
      if (!actorValue) { notice = 'Enter your operator name first.'; render(); return; }
      const target = `${owner.value.trim() || account.login}/${name.value.trim()}`;
      if (!name.value.trim()) { notice = 'A repository name is required.'; render(); return; }
      if (!window.confirm(`Create ${visibility.value} repository ${target}?`)) return;
      go.disabled = true;
      try {
        const out = await api.post('api/github/repo', {
          name: name.value.trim(), owner: owner.value.trim() || undefined,
          visibility: visibility.value,
          description: description.value.trim() || undefined,
          actor: actorValue, confirm: true,
        });
        notice = `${out.detail} ${out.url}`;
        name.value = description.value = '';
        load();
      } catch (err) { notice = err.message; render(); }
      finally { go.disabled = false; }
    });
    return box;
  }

  function createIssueCard() {
    const {el} = api;
    const box = el('details', 'subcard');
    box.appendChild(el('summary', '', 'Open an issue'));
    if (!account.authenticated) {
      box.appendChild(el('p', 'muted', 'Sign in first.'));
      return box;
    }
    const form = el('div', 'row wrap');
    const repo = el('input', 'rin');
    repo.size = 20; repo.placeholder = 'owner/name';
    repo.setAttribute('aria-label', 'Repository');
    repo.setAttribute('list', 'ghRepoList');
    const list = el('datalist', '');
    list.id = 'ghRepoList';
    for (const entry of (data && data.repos) || []) {
      if (!entry.nwo) continue;
      const option = el('option', '');
      option.value = entry.nwo;
      list.appendChild(option);
    }
    const title = el('input', 'rin');
    title.size = 28; title.placeholder = 'title';
    title.setAttribute('aria-label', 'Issue title');
    const go = el('button', 'btn', 'Open issue');
    form.append(repo, list, title, go);
    box.appendChild(form);
    const body = el('textarea', 'code-area');
    body.rows = 4; body.placeholder = 'body (optional, Markdown)';
    body.setAttribute('aria-label', 'Issue body');
    box.appendChild(body);

    go.addEventListener('click', async () => {
      if (!actorValue) { notice = 'Enter your operator name first.'; render(); return; }
      if (!repo.value.trim() || !title.value.trim()) {
        notice = 'A repository (owner/name) and a title are required.'; render(); return;
      }
      if (!window.confirm(`Open an issue on ${repo.value.trim()}?\n\n${title.value.trim()}`)) return;
      go.disabled = true;
      try {
        const out = await api.post('api/github/issue', {
          repo: repo.value.trim(), title: title.value.trim(),
          body: body.value || undefined, actor: actorValue, confirm: true,
        });
        notice = `${out.detail} ${out.url}`;
        title.value = body.value = '';
      } catch (err) { notice = err.message; }
      finally { go.disabled = false; render(); }
    });
    return box;
  }

  // ── the repository snapshot, as before but under the account ──────────────

  function repoSection(repo) {
    const {el} = api;
    const section = el('article', 'gh-repo');
    section.appendChild(el('h3', '', repo.name));
    section.appendChild(el('p', 'muted', repo.path));
    if (repo.branch) {
      section.appendChild(el('strong', '', `${repo.branch} · ${repo.ahead ?? '?'} ahead / ${repo.behind ?? '?'} behind · ${repo.dirty_files ? `DIRTY: ${repo.dirty_files} files` : 'clean'}`));
      if (repo.ahead > 0) section.appendChild(el('p', 'error', `${repo.ahead} UNPUSHED COMMITS`));
      section.appendChild(el('p', 'muted', `Tracking: ${repo.upstream || 'none'}`));
    }
    for (const error of repo.errors) section.appendChild(el('p', 'error', error));
    section.appendChild(el('h4', '', 'Recent commits'));
    for (const commit of repo.commits || []) {
      section.appendChild(el('p', '', `${commit.sha} ${commit.subject} · ${commit.date}`));
    }
    for (const [key, title] of [['prs', 'Open pull requests'], ['runs', 'Recent workflow runs — failures first']]) {
      section.appendChild(el('h4', '', title));
      if (!repo[key].length) {
        section.appendChild(el('p', 'muted',
          data.gh.state !== 'ready' || repo.errors.some(e => e.startsWith(key + ':'))
            ? 'Unavailable' : 'None'));
      }
      for (const row of repo[key]) {
        const label = key === 'prs'
          ? `#${row.number} ${row.title} · review: ${row.reviewDecision || 'PENDING'} · CI: ${row.ci}`
          : `${row.displayTitle} · ${row.conclusion || row.status} · ${row.duration_seconds ?? '?'}s${row.status !== 'completed' ? ' elapsed' : ''}`;
        const p = el('p', '', label);
        try {
          const url = new URL(row.url);
          if (url.protocol === 'https:') {
            const a = el('a', '', ' View on GitHub');
            a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer';
            p.appendChild(a);
          }
        } catch (_) { /* no link for invalid URLs */ }
        section.appendChild(p);
      }
    }
    return section;
  }

  function render() {
    const {el} = api;
    const root = document.getElementById('viewGithub');
    const nodes = [];

    const header = el('div', 'vhead');
    header.appendChild(el('h2', '', 'GitHub'));
    const stamp = el('span', 'stamp');
    stamp.textContent = data ? `checked ${data.checked_at} · cached 30s` : '';
    header.appendChild(stamp);
    header.appendChild(el('span', 'spacer'));
    const refresh = el('button', 'btn', 'Refresh');
    refresh.addEventListener('click', load);
    header.appendChild(refresh);
    nodes.push(header);

    if (notice) {
      const box = el('p', 'notice', notice);
      box.setAttribute('role', 'status');
      nodes.push(box);
    }
    if (account) nodes.push(accountCard());
    if (account) {
      const writes = el('div', 'gh-writes');
      writes.append(createRepoCard(), createIssueCard());
      nodes.push(writes);
    }

    if (data) {
      nodes.push(el('p', 'hint', 'Repository rows are read-only and use local tracking refs; no fetch is performed. Configure them in AGENTMUX_HOME/github.json (default ~/.agentmux/github.json): {"repos":[{"name":"repo","path":"/path/to/repo"}]}'));
      if (data.gh.state !== 'ready' && data.gh.message) {
        nodes.push(el('p', 'error', `${data.gh.message}${data.gh.command ? ` Run: ${data.gh.command}` : ''}`));
      }
      for (const error of data.errors) nodes.push(el('p', 'error', error));
      for (const repo of data.repos) nodes.push(repoSection(repo));
    }
    root.replaceChildren(...nodes);
  }

  async function load() {
    if (loading) return;
    loading = true;
    const root = document.getElementById('viewGithub');
    try {
      const [auth, snapshot] = await Promise.all([
        api.getJSON('api/github/auth'),
        api.getJSON('api/github'),
      ]);
      account = auth.account;
      login = auth.login;
      data = snapshot;
      render();
    } catch (err) {
      root.replaceChildren(api.el('p', 'error', `GitHub panel unavailable: ${err.message}`));
    } finally { loading = false; }
  }

  window.addEventListener('agentmux:ready', () => {
    api = window.AGENTMUX;
    api.registerView('github', load, 30000);
  }, {once: true});
})();
