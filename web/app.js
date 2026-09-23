'use strict';

(function () {
  const list = document.getElementById('agents');
  const status = document.getElementById('status');

  // Neutral placeholder shown when an avatar file is missing or fails to load.
  function placeholder(agent) {
    const div = document.createElement('div');
    div.className = 'avatar avatar-placeholder';
    div.setAttribute('role', 'img');
    div.setAttribute('aria-label', agent.name + ' (avatar unavailable)');
    div.textContent = (agent.name || '?').charAt(0).toUpperCase();
    return div;
  }

  function card(agent) {
    const li = document.createElement('li');
    li.className = 'card';

    const img = document.createElement('img');
    img.className = 'avatar';
    img.src = agent.avatar;
    img.alt = agent.name + ' avatar';
    img.width = 96;
    img.height = 96;
    img.addEventListener('error', function () {
      img.replaceWith(placeholder(agent));
    }, { once: true });

    const body = document.createElement('div');
    body.className = 'card-body';

    const name = document.createElement('h2');
    name.textContent = agent.name;
    const role = document.createElement('p');
    role.className = 'role';
    role.textContent = agent.role;
    const provider = document.createElement('p');
    provider.className = 'provider provider-' + String(agent.provider).toLowerCase();
    provider.textContent = agent.provider;

    body.append(name, role, provider);
    li.append(img, body);
    return li;
  }

  fetch('/api/agents')
    .then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then(function (agents) {
      list.replaceChildren.apply(list, agents.map(card));
      status.textContent = agents.length + ' agents';
      status.classList.add('visually-hidden');
    })
    .catch(function (err) {
      status.textContent = 'Could not load agents: ' + err.message;
      status.classList.add('error');
    });
})();
