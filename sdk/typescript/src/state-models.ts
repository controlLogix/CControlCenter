import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {ContractError, canonicalBytes, strictLoads} from './index.js';

const token = /^[a-z][a-z0-9_-]{0,95}$/;
function deny(): never { throw new ContractError('invalid_transition'); }
function record(value: any, keys?: string[]): any {
  if (!value || typeof value !== 'object' || Array.isArray(value)) deny();
  if (keys && (Object.keys(value).length !== keys.length || keys.some(k => !Object.hasOwn(value,k)))) deny();
  return value;
}
function identifier(value: unknown): void { if (typeof value !== 'string' || !token.test(value)) deny(); }
const blankReference = /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*$/u;
function reference(value: unknown): void { if (typeof value !== 'string' || blankReference.test(value) || Array.from(value).length > 512) deny(); }
function revision(value: unknown): void { if (!Number.isSafeInteger(value) || (value as number) < 0) deny(); }

function loadModels(path?: string): any {
  const location = path ?? process.env.AGENTMUX_STATE_MODELS ?? resolve(process.env.AGENTMUX_SCHEMA_DIR ?? 'contracts/v1/schemas', '../models/state-machines.json');
  let model: any;
  try { model = strictLoads(readFileSync(location)); } catch { deny(); }
  if (model.schemaVersion !== '1.0.0') deny();
  record(model.machines, ['plugin','task','delegation','attempt','effect']);
  let count = 0;
  for (const machine of Object.values(model.machines) as any[]) {
    if (!Array.isArray(machine.states) || !machine.states.length || new Set(machine.states).size !== machine.states.length) deny();
    machine.states.forEach(identifier);
    if (!machine.states.includes(machine.initial) || !Array.isArray(machine.transitions)) deny();
    const edges = new Set<string>();
    for (const edge of machine.transitions) {
      record(edge, ['from','event','to','actorRole','requires']);
      for (const key of ['from','event','to','actorRole']) identifier(edge[key]);
      if (!machine.states.includes(edge.from) || !machine.states.includes(edge.to)) deny();
      if (!Array.isArray(edge.requires) || new Set(edge.requires).size !== edge.requires.length) deny();
      edge.requires.forEach(identifier);
      const key = `${edge.from}:${edge.event}`;
      if (edges.has(key)) deny();
      edges.add(key); count++;
    }
  }
  if (count !== 68) deny();
  return model.machines;
}

/** Pure fixture oracle. Callers must supply trusted owner observations; references do not authenticate anyone or commit state. */
export function evaluateTransition(request: unknown, modelsPath?: string): object {
  canonicalBytes(request); // Reject accessors, unsupported values and invalid Unicode before reading fields.
  const r = record(request, ['schemaVersion','machine','ownerSnapshot','intent','authority','guards']);
  if (r.schemaVersion !== '1.0.0') deny();
  identifier(r.machine);
  const owner = record(r.ownerSnapshot, ['entityId','ownerHubId','scopeId','state','revision','cancellationPending']);
  const intent = record(r.intent, ['entityId','expectedRevision','event','operationId','payloadDigest']);
  const authority = record(r.authority, ['entityId','ownerHubId','scopeId','actorRole','evidenceRefs']);
  for (const key of ['entityId','ownerHubId','scopeId','state']) identifier(owner[key]);
  for (const key of ['entityId','event','operationId']) identifier(intent[key]);
  for (const key of ['entityId','ownerHubId','scopeId','actorRole']) identifier(authority[key]);
  revision(owner.revision); revision(intent.expectedRevision);
  if (typeof owner.cancellationPending !== 'boolean') deny();
  if (owner.state === 'cancel_requested' && !owner.cancellationPending) deny();
  if (owner.cancellationPending && !['cancel_requested','effect_uncertain'].includes(owner.state)) deny();
  if (owner.cancellationPending && ['reconcile_terminal','reconcile_running','validate'].includes(intent.event)) deny();
  if (owner.revision === Number.MAX_SAFE_INTEGER || owner.revision !== intent.expectedRevision) deny();
  if (typeof intent.payloadDigest !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(intent.payloadDigest)) deny();
  if (owner.entityId !== intent.entityId || ['entityId','ownerHubId','scopeId'].some(k => owner[k] !== authority[k])) deny();
  if (!Array.isArray(authority.evidenceRefs) || !authority.evidenceRefs.length || authority.evidenceRefs.length > 64 || new Set(authority.evidenceRefs).size !== authority.evidenceRefs.length) deny();
  authority.evidenceRefs.forEach(reference);
  const machines = loadModels(modelsPath);
  if (!Object.hasOwn(machines,r.machine)) deny();
  const edge = machines[r.machine].transitions.find((e: any) => e.from === owner.state && e.event === intent.event);
  if (!edge || edge.actorRole !== authority.actorRole) deny();
  record(r.guards, edge.requires);
  Object.values(r.guards).forEach(reference);
  return {machine:r.machine,entityId:owner.entityId,ownerHubId:owner.ownerHubId,scopeId:owner.scopeId,
    fromState:owner.state,state:edge.to,previousRevision:owner.revision,revision:owner.revision+1,
    operationId:intent.operationId,payloadDigest:intent.payloadDigest,event:intent.event,
    cancellationPending:edge.to === 'cancel_requested' || (owner.cancellationPending && edge.to !== 'cancelled'),
    evidenceRefs:[...authority.evidenceRefs],guardEvidence:{...r.guards}};
}
