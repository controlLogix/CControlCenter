'use strict';

// Fetch the roll call and render one card per agent.
(function () {
  const list = document.getElementById('agents');
  const status = document.getElementById('status');

  // Neutral stand-in for an avatar that has not been drawn yet (or fails to load).
  function placeholder(agent) {
    const box = document.createElement('div');
    box.className = 'avatar avatar-placeholder';
    box.setAttribute('role', 'img');
    box.setAttribute('aria-label', `${agent.name} (avatar unavailable)`);
    box.textContent = (agent.name || agent.id || '?').charAt(0).toUpperCase();
    return box;
  }

  function avatar(agent) {
    const img = document.createElement('img');
    img.className = 'avatar';
    img.src = agent.avatar;
    img.alt = `${agent.name} avatar`;
    img.width = 96;
    img.height = 96;
    img.decoding = 'async';
    img.addEventListener('error', () => img.replaceWith(placeholder(agent)), { once: true });
    return img;
  }

  function field(className, text) {
    const el = document.createElement('p');
    el.className = className;
    el.textContent = text;
    return el;
  }

  function card(agent) {
    const item = document.createElement('li');
    item.className = 'card';
    item.dataset.agent = agent.id;

    const name = document.createElement('h2');
    name.className = 'name';
    name.textContent = agent.name;

    const body = document.createElement('div');
    body.className = 'card-body';
    body.append(name, field('role', agent.role), field('provider', agent.provider));

    item.append(avatar(agent), body);
    return item;
  }

  fetch('/api/agents', { headers: { Accept: 'application/json' } })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((agents) => {
      list.replaceChildren(...agents.map(card));
      status.textContent = `${agents.length} agents`;
      status.classList.add('visually-hidden');
    })
    .catch((err) => {
      status.textContent = `Could not load agents (${err.message}).`;
      status.classList.add('error');
    });
})();
