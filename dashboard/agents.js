/* Read-only file definitions. Refresh explicitly after editing a definition. */
(() => {
  'use strict';

  let ui;
  let loading = false;

  function remedy(error) {
    if (error.includes('duplicate name')) {
      return 'Rename one definition file and its name field, or remove a duplicate, then refresh.';
    }
    if (error.includes('unknown key')) {
      return 'Remove or correct the unknown frontmatter key, then refresh.';
    }
    return 'Correct the reported error in the source file, then refresh.';
  }

  function setup() {
    if (ui) return ui;
    const { el } = window.CCC;
    const section = document.getElementById('viewAgents');
    const header = el('div', 'agents-header');
    header.appendChild(el('h2', '', 'Agents'));
    const refresh = el('button', 'btn', 'Refresh');
    refresh.type = 'button';
    refresh.addEventListener('click', loadAgents);
    const stamp = el('span', 'stamp');
    stamp.setAttribute('aria-live', 'polite');
    header.appendChild(refresh);
    header.appendChild(stamp);
    const content = el('div', 'agents-content');
    section.replaceChildren(header,
      el('p', 'hint', 'Agent definitions are read-only here. Edit their source files, then refresh.'),
      content);
    ui = { refresh, stamp, content };
    return ui;
  }

  async function loadAgents() {
    const { el, getJSON, say } = window.CCC;
    const { refresh, stamp, content } = setup();
    if (loading) return;
    loading = true;
    refresh.disabled = true;
    say(stamp, 'Loading definitions…');
    try {
      const data = await getJSON('api/board/agents');
      if (!data || !Array.isArray(data.agents) || !Array.isArray(data.problems)) {
        throw new Error('response must include agents and problems arrays');
      }
      const nodes = [];
      if (data.problems.length) {
        const problems = el('section', 'agents-problems');
        problems.setAttribute('aria-label', 'Definition problems');
        problems.appendChild(el('h3', '', 'Definition problems'));
        for (const problem of data.problems) {
          const row = el('article', 'agents-problem');
          row.appendChild(el('strong', 'agents-path', problem.path));
          row.appendChild(el('span', 'agents-scope', problem.scope));
          // Keep the complete backend diagnostic: collisions include every path.
          row.appendChild(el('p', 'agents-error', problem.error));
          row.appendChild(el('p', 'agents-remedy', remedy(String(problem.error))));
          problems.appendChild(row);
        }
        nodes.push(problems);
      }
      const list = el('section', 'agents-list');
      list.setAttribute('aria-label', 'Agent definitions');
      list.appendChild(el('h3', '', 'Definitions'));
      if (!data.agents.length) list.appendChild(el('p', 'empty', 'No usable agent definitions found.'));
      for (const agent of data.agents) {
        const card = el('article', 'agents-definition');
        const title = el('div', 'agents-title');
        title.appendChild(el('h4', '', agent.name));
        title.appendChild(el('span', 'agents-scope', agent.scope));
        card.appendChild(title);
        if (agent.description) card.appendChild(el('p', '', agent.description));
        const fields = el('dl', 'agents-fields');
        for (const [label, value] of [['CLI', agent.cli], ['Posture', agent.posture], ['Role', agent.role]]) {
          fields.appendChild(el('dt', '', label));
          fields.appendChild(el('dd', '', value || '—'));
        }
        card.appendChild(fields);
        card.appendChild(el('p', 'agents-path', agent.path));
        list.appendChild(card);
      }
      nodes.push(list);
      content.replaceChildren(...nodes);
      say(stamp, `${data.agents.length} definitions · ${data.problems.length} problems`);
    } catch (err) {
      // Retain the last successful result, but clearly mark it as stale.
      say(stamp, `Definitions unavailable: ${err.message}. Displayed results may be out of date; refresh to retry.`);
    } finally {
      loading = false;
      refresh.disabled = false;
    }
  }

  window.addEventListener('ccc:ready', () => {
    window.CCC.registerView('agents', loadAgents);
  }, { once: true });
})();
