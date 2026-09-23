'use strict';

// The four agents of the roll call, in their fixed order.
const AGENTS = [
  { id: 'conductor', name: 'Conductor', role: 'orchestrator', provider: 'Claude' },
  { id: 'developer', name: 'Developer', role: 'full-stack developer', provider: 'Claude' },
  { id: 'imager', name: 'Imager', role: 'image generator', provider: 'Grok' },
  { id: 'reviewer', name: 'Reviewer', role: 'final reviewer', provider: 'Grok' },
].map((agent) => ({ ...agent, avatar: `/avatars/${agent.id}.svg` }));

module.exports = { AGENTS };
