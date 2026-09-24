/* File definition registry with inline, checksum-guarded editing. */
(() => {
  'use strict';

  let ui;
  let loading = false;

  // The shared post helper drops structured conflict hints, including file paths.
  async function writeDefinition(op, body) {
    const response = await fetch(`api/board/${op}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      const hints = Array.isArray(data.missing) ? data.missing.map(item => item.hint).filter(Boolean) : [];
      throw new Error([data.error || `HTTP ${response.status}`, ...hints].join(' · '));
    }
    return data;
  }

  function editor(agent) {
    const { el, getJSON, say } = window.CCC;
    const details = el('details', 'agents-editor');
    details.appendChild(el('summary', '', agent ? 'Edit definition' : 'Create definition'));
    const host = el('div');
    details.appendChild(host);
    let initialized = false;
    let fetching = false;
    async function initialize() {
      if (!details.open || initialized || fetching) return;
      fetching = true;
      try {
        const value = agent ? await getJSON(`api/board/agents?name=${encodeURIComponent(agent.name)}`) : {};
        if (agent && (value.scope === 'claude' || value.editable === false)) {
          throw new Error('This definition is read-only. Refresh the list.');
        }
        const form = el('form', 'agents-form');
        const inputs = {};
        const choices = {
          scope: ['repo', 'global'], posture: ['workspace-write', 'read-only', 'unrestricted'],
          role: ['worker', 'lead', 'reviewer', 'researcher'], worktree: ['per-member', 'integration', 'none']
        };
        for (const [key, label] of [
          ['name', 'Name'], ['scope', 'Scope'], ['description', 'Description'], ['cli', 'CLI'],
          ['model', 'Model (optional)'], ['auth', 'Auth method ID (optional)'], ['posture', 'Posture'],
          ['role', 'Role'], ['worktree', 'Worktree'], ['max_instances', 'Maximum instances (1–8)'],
          ['tools', 'Tools (comma separated)'], ['tools_deny', 'Denied tools (comma separated)'],
          ['capabilities', 'Capabilities (comma separated)'], ['persona', 'Persona']
        ]) {
          const wrapper = el('label', 'agents-label', label);
          const input = el(key === 'persona' ? 'textarea' : choices[key] ? 'select' : 'input', 'rin');
          input.name = key;
          if (choices[key]) for (const choice of choices[key]) {
            const option = el('option', '', choice);
            option.value = choice;
            input.appendChild(option);
          }
          const fallback = choices[key] ? choices[key][0] : key === 'max_instances' ? 1 : '';
          input.value = Array.isArray(value[key]) ? value[key].join(', ') : value[key] ?? fallback;
          if (agent && ['name', 'scope'].includes(key)) input.disabled = true;
          if (['name', 'description'].includes(key)) input.required = true;
          if (key === 'name') { input.pattern = '[a-z][a-z0-9-]{0,63}'; input.maxLength = 64; }
          if (key === 'description') input.maxLength = 2048;
          if (key === 'persona') { input.maxLength = 4096; input.rows = 8; }
          if (key === 'max_instances') { input.type = 'number'; input.min = 1; input.max = 8; input.required = true; }
          inputs[key] = input;
          wrapper.appendChild(input);
          form.appendChild(wrapper);
        }
        const save = el('button', 'btn', agent ? 'Save definition' : 'Create definition');
        save.type = 'submit';
        const stamp = el('p', 'stamp');
        stamp.setAttribute('aria-live', 'polite');
        form.appendChild(save);
        form.appendChild(stamp);
        let saving = false;
        form.addEventListener('submit', async event => {
          event.preventDefault();
          if (saving) return;
          const body = {};
          for (const [key, input] of Object.entries(inputs)) {
            const raw = input.value;
            body[key] = ['tools', 'tools_deny', 'capabilities'].includes(key)
              ? (raw.trim() ? raw.split(',').map(item => item.trim()) : [])
              : key === 'max_instances' ? Number(raw) : raw;
          }
          if (!body.cli) delete body.cli;
          if (agent) Object.assign(body, { name: value.name, scope: value.scope, path: value.path, checksum: value.checksum });
          saving = true;
          save.disabled = true;
          try {
            const saved = await writeDefinition('agentdef', body);
            Object.assign(value, saved);
            say(stamp, 'Definition saved.');
            if (!agent) { initialized = false; host.replaceChildren(); details.open = false; }
            await loadAgents();
          } catch (err) { say(stamp, err.message); }
          finally { saving = false; save.disabled = false; }
        });
        host.replaceChildren(form);
        initialized = true;
      } catch (err) {
        host.replaceChildren(el('p', 'agents-error', `${err.message} Close and reopen to retry.`));
      } finally { fetching = false; }
    }
    details.addEventListener('toggle', initialize);
    return details;
  }

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
      el('p', 'hint', 'Create and edit repo or global definitions here. Claude definitions are read-only.'),
      content, editor(null));
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
        // A definition is a file; an AGENT is a running process. Marking the name
        // here is what tells you which of these definitions is currently spawned.
        title.appendChild(window.CCC.markAgent(el('h4', '', agent.name), agent.name));
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
        if (['repo', 'global'].includes(agent.scope) && agent.editable !== false) {
          card.appendChild(editor(agent));
          const stamp = el('p', 'stamp');
          stamp.setAttribute('aria-live', 'polite');
          card.appendChild(window.CCC.deleteButton('agent definition', agent.name, agent.name,
            loadAgents, stamp, () => writeDefinition('agentdrop', {
              name: agent.name, scope: agent.scope, path: agent.path, checksum: agent.checksum
            })));
          card.appendChild(stamp);
        } else card.appendChild(el('p', 'hint', 'Read-only definition'));
        list.appendChild(card);
      }
      nodes.push(list);
      content.replaceChildren(...nodes);
      window.CCC.refreshLiveMarks(document.getElementById('viewAgents'));
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
    window.CCC.registerPanel('organization', 'agents', loadAgents);
  }, { once: true });
})();
