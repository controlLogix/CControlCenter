'use strict';

// A neutral stand-in shown when an agent's avatar file is missing or fails to load.
function placeholder(agent) {
  const el = document.createElement('div');
  el.className = 'avatar avatar-placeholder';
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', `${agent.name} (no avatar yet)`);
  el.textContent = (agent.name || agent.id || '?').charAt(0).toUpperCase();
  return el;
}

function avatar(agent) {
  const img = document.createElement('img');
  img.className = 'avatar';
  img.src = agent.avatar;
  img.alt = `${agent.name} avatar`;
  img.width = 96;
  img.height = 96;
  img.addEventListener('error', () => img.replaceWith(placeholder(agent)), { once: true });
  return img;
}

function card(agent) {
  const li = document.createElement('li');
  li.className = 'card';
  li.dataset.id = agent.id;

  const body = document.createElement('div');
  body.className = 'card-body';

  const name = document.createElement('h2');
  name.className = 'name';
  name.textContent = agent.name;

  const role = document.createElement('p');
  role.className = 'role';
  role.textContent = agent.role;

  const provider = document.createElement('p');
  provider.className = 'provider';
  provider.textContent = agent.provider;

  body.append(name, role, provider);
  li.append(avatar(agent), body);
  return li;
}

async function main() {
  const status = document.getElementById('status');
  const list = document.getElementById('agents');
  try {
    const res = await fetch('/api/agents');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const agents = await res.json();
    list.replaceChildren(...agents.map(card));
    status.textContent = `${agents.length} agents`;
  } catch (err) {
    status.textContent = `Could not load agents: ${err.message}`;
    status.classList.add('error');
  }
}

main();
