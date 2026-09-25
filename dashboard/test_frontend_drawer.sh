#!/usr/bin/env bash
# Real drawer and shell POST code against an identity-preserving minimal DOM.
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  drawer_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$drawer_node_dir" ] || export PATH="$drawer_node_dir:$PATH"
fi
node <<'JS'
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('dashboard/kanban.js', 'utf8');
const shell = fs.readFileSync('dashboard/app.js', 'utf8');
const postSource = shell.slice(shell.indexOf('async function post('), shell.indexOf('function clock('));
const tests = [], unfinished = new Set();
let passed = 0, failed = 0, suiteFinished = false;
function test(name, fn) {
  if (process.env.DRAWER_TEST && process.env.DRAWER_TEST !== name) return;
  const entry = {name, fn}; tests.push(entry); unfinished.add(entry);
}
process.on('exit', () => {
  for (const {name} of unfinished) console.error('FAIL ' + name + ': registered test did not finish');
  if (!suiteFinished || unfinished.size || failed || !passed) process.exitCode = 1;
});
async function runTest(entry) {
  let timer;
  try {
    await Promise.race([entry.fn(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error('async test did not finish')), 2000);
    })]);
    passed++; console.log('PASS ' + entry.name);
  } catch (e) { failed++; console.error('FAIL ' + entry.name, e); }
  finally { clearTimeout(timer); unfinished.delete(entry); }
}
class Node {
  constructor(tag, cls = '', text = '') { this.tag = tag; this.className = cls; this.textContent = text; this.children = []; this.dataset = {}; this.attrs = {}; this.events = {}; this.value = ''; }
  append(...nodes) { for (const n of nodes) { if (n.parent) n.parent.children = n.parent.children.filter(x => x !== n); n.parent = this; this.children.push(n); } }
  appendChild(n) { this.append(n); return n; }
  replaceChildren(...nodes) { this.children.forEach(n => n.parent = null); this.children = []; this.append(...nodes); }
  setAttribute(k,v) { this.attrs[k] = v; }
  addEventListener(k,fn) { this.events[k] = fn; }
  focus() { this.focused = true; }
}
const all = n => [n, ...n.children.flatMap(all)];
const text = n => all(n).map(n => n.textContent).join('\n');
const event = () => ({preventDefault() {}});
const fresh = (extra = {}) => ({key: 'TM-1', kind: 'task', title: 'Full ticket', body: '<b>full body</b>', status: 'open', assignee: 'worker', priority: 'high', estimate: 3,
  acceptance: ['first', 'second', 'third'].map(text => ({text, done: false})), labels: ['ready'], blockedBy: ['TM-2'], evidence: ['proof'], commits: ['abc123'],
  comments: [{author: 'nick', ts: '2026-09-25', text: 'detail comment'}], links: [{type: 'related', id: 'TM-4'}], touches: ['file.js'], actor: 'nick', branch: 'main', worktree: '/work', jira_key: 'DEMO-1', ...extra});
const settled = async () => { for (let i=0;i<12;i++) await Promise.resolve(); };
function setup(initial = fresh(), options = {}) {
  const body = new Node('body'), root = new Node('div'), jira = new Node('input'), requests = [], posts = [];
  jira.value = options.base ?? 'https://example.atlassian.net/'; body.append(root);
  let entity = initial, ready, loader, reader = options.read, responder = options.respond;
  const getJSON = async path => {
    requests.push(path);
    if (reader) { const value = reader(path); if (value !== undefined) return value; }
    if (path === 'api/board/board') return {tasks: [entity]};
    if (path.startsWith('api/board/entity?')) return structuredClone(entity);
    if (path.startsWith('api/board/history?')) return {events: [{ts: '2026-09-25', actor: 'nick', event: 'edit', detail: {fields: ['body']}}]};
    if (path.startsWith('api/board/why?')) return {reasons: [{text: 'Waiting for proof'}]};
    if (path.startsWith('api/board/roster?')) return {members: [{agent_name: 'worker', role: 'worker', status: 'proposed'}]};
    throw Error('unexpected GET ' + path);
  };
  const ctx = {URL, document: {body, activeElement: new Node('button'), getElementById: id => id === 'jiraBase' ? jira : id === 'viewKanban' ? root : id === 'viewBoard' ? body : null},
    window: {events: {}, confirm: () => options.confirm !== false, addEventListener: (name,fn) => { if (name === 'ccc:ready') ready=fn; else ctx.window.events[name]=fn; }, CCC: {el: (...args)=>new Node(...args), getJSON, registerPanel: (a,b,fn)=>{loader=fn;}}},
    fetch: async (path, opts) => {
      const payload = JSON.parse(opts.body); posts.push({endpoint: path, ...payload});
      if (responder) return responder(path,payload);
      if (path.endsWith('/acceptance')) {
        if (payload.remove) entity.acceptance.splice(payload.index-1,1);
        else if (payload.text != null) entity.acceptance.push({text:payload.text,done:false});
        else entity.acceptance[payload.index-1].done = payload.done;
      }
      if (payload.patch) Object.assign(entity,payload.patch);
      return {ok:true,status:200,json:async()=>structuredClone(entity)};
    }};
  vm.runInNewContext(postSource+'\nwindow.CCC.post = post;',ctx);
  vm.runInNewContext(source,ctx);ready();
  const nodes = () => all(body);
  return {ctx, body, root, posts, requests, open: key => ctx.window.CCCOpenCard(key || entity.key, async()=>{}), load:()=>loader(),
    read:fn=>{reader=fn;}, respond:fn=>{responder=fn;}, entity:value=>{entity=value;},
    drawer:()=>nodes().find(n=>n.id==='cardDrawer'), form:name=>nodes().find(n=>n.dataset.field===name),
    section:name=>nodes().find(n=>n.dataset.section===name), criteria:()=>nodes().filter(n=>n.className==='drawer-criterion'),
    find:cls=>nodes().find(n=>n.className===cls)};
}
async function submit(p,field,values=[],remove=false) {
  const form=p.form(field);assert.ok(form,field+' editor exists');
  const inputs=all(form).filter(n=>n.tag==='input'||n.tag==='textarea');
  values.forEach((value,i)=>{inputs[i].value=value;});
  return remove ? form.children.at(-1).events.click() : form.events.submit(event());
}
function response(payload,status=200) { return {ok:status<400,status,json:async()=>payload}; }

test('kanban writes exclusively through api.post',async()=>{
  assert.doesNotMatch(source,/\bfetch\s*\(/);assert.doesNotMatch(source,/shell post helper discards/);
  const p=setup();await p.load();let called=false;
  p.ctx.window.CCC.post=async(path,body)=>{called=true;assert.equal(path,'api/board/status');assert.equal(body.status,'blocked');return {};};
  const col=all(p.root).find(n=>n.dataset.status==='blocked'&&n.className==='kanban-column');
  await col.events.drop({preventDefault(){},dataTransfer:{getData:()=> 'TM-1'}});assert.equal(called,true);
});
test('kanban bypass is announced through shared post',async()=>{
  const p=setup();await p.load();p.respond(()=>response({entity:fresh({status:'done'}),bypassed:{reason:'enforcement disabled'}}));
  const col=all(p.root).find(n=>n.dataset.status==='done'&&n.className==='kanban-column');
  await col.events.drop({preventDefault(){},dataTransfer:{getData:()=> 'TM-1'}});
  assert.ok(text(p.root).includes('Gate bypassed: enforcement disabled'));
});
(async()=>{
  for(const entry of tests)await runTest(entry);
  suiteFinished=true;console.log(`passed ${passed}, failed ${failed}`);process.exitCode=failed||!passed?1:0;
})();
JS
