/* Read-only: refreshes GET snapshots; every value is rendered as text. */
(() => {
  'use strict';
  let loading = false;
  async function load() {
    if (loading) return;
    loading = true;
    const {el, getJSON} = window.CCC;
    const root = document.getElementById('viewGithub');
    try {
      const data = await getJSON('/api/github');
      const header = el('div', '');
      header.appendChild(el('h2', '', 'GitHub'));
      const refresh = el('button', 'btn', 'Refresh');
      refresh.addEventListener('click', load);
      header.appendChild(refresh);
      header.appendChild(el('p', 'muted', `Read-only · checked ${data.checked_at} · cached 30s. Counts use local tracking refs; no fetch is performed.`));
      header.appendChild(el('p', '', 'Configure repositories in AGENTMUX_HOME/github.json (default ~/.agentmux/github.json): {"repos":[{"name":"repo","path":"/path/to/repo"}]}'));
      if (data.gh.state !== 'ready') header.appendChild(el('p', 'error', `${data.gh.message} Run: ${data.gh.command}`));
      for (const error of data.errors) header.appendChild(el('p', 'error', error));
      const nodes = [header];
      for (const repo of data.repos) {
        const section = el('article', '');
        section.appendChild(el('h3', '', repo.name));
        section.appendChild(el('p', 'muted', repo.path));
        if (repo.branch) {
          section.appendChild(el('strong', '', `${repo.branch} · ${repo.ahead ?? '?'} ahead / ${repo.behind ?? '?'} behind · ${repo.dirty_files ? `DIRTY: ${repo.dirty_files} files` : 'clean'}`));
          if (repo.ahead > 0) section.appendChild(el('p', 'error', `${repo.ahead} UNPUSHED COMMITS`));
          section.appendChild(el('p', 'muted', `Tracking: ${repo.upstream || 'none'}`));
        }
        for (const error of repo.errors) section.appendChild(el('p', 'error', error));
        section.appendChild(el('h4', '', 'Recent commits'));
        for (const commit of repo.commits || []) section.appendChild(el('p', '', `${commit.sha} ${commit.subject} · ${commit.date}`));
        for (const [key, title] of [['prs', 'Open pull requests'], ['runs', 'Recent workflow runs — failures first']]) {
          section.appendChild(el('h4', '', title));
          if (!repo[key].length) section.appendChild(el('p', 'muted', data.gh.state !== 'ready' || repo.errors.some(e => e.startsWith(key + ':')) ? 'Unavailable' : 'None'));
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
        nodes.push(section);
      }
      root.replaceChildren(...nodes);
    } catch (err) {
      root.replaceChildren(el('p', 'error', `GitHub snapshot unavailable: ${err.message}`));
    } finally { loading = false; }
  }
  window.addEventListener('ccc:ready', () => window.CCC.registerView('github', load, 30000), {once: true});
})();
