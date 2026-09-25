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
    window: {events: {}, confirm: () => options.confirm !== false, addEventListener: (name,fn) => { if (name === 'agentmux:ready') ready=fn; else ctx.window.events[name]=fn; }, AGENTMUX: {el: (...args)=>new Node(...args), getJSON, registerPanel: (a,b,fn)=>{loader=fn;}}},
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
  vm.runInNewContext(postSource+'\nwindow.AGENTMUX.post = post;',ctx);
  vm.runInNewContext(source,ctx);ready();
  const nodes = () => all(body);
  return {ctx, body, root, posts, requests, open: key => ctx.window.AGENTMUXOpenCard(key || entity.key, options.after || (async()=>{})), load:()=>loader(),
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

test('post preserves 409 status payload and existing message',async()=>{
  const p=setup();const payload={error:'Gate refused',missing:[{field:'body',hint:'exact <hint>'}]};
  p.respond(()=>response(payload,409));
  await assert.rejects(p.ctx.window.AGENTMUX.post('api/board/status',{}),e=>e.status===409&&e.payload===payload&&e.message==='Gate refused');
  p.respond(()=>({ok:false,status:503,json:async()=>{throw Error('not json');}}));
  await assert.rejects(p.ctx.window.AGENTMUX.post('api/board/status',{}),e=>e.status===503&&e.message==='HTTP 503');
});
test('kanban writes exclusively through api.post',async()=>{
  assert.doesNotMatch(source,/\bfetch\s*\(/);assert.doesNotMatch(source,/shell post helper discards/);
  const p=setup();await p.load();let called=false;
  p.ctx.window.AGENTMUX.post=async(path,body)=>{called=true;assert.equal(path,'api/board/status');assert.equal(body.status,'blocked');return {};};
  const col=all(p.root).find(n=>n.dataset.status==='blocked'&&n.className==='kanban-column');
  await col.events.drop({preventDefault(){},dataTransfer:{getData:()=> 'TM-1'}});assert.equal(called,true);
});
test('both entry points are accessible without shifting task row nodes',async()=>{
  const p=setup();await p.load();await p.find('kanban-open').events.click();assert.equal(p.drawer().hidden,false);
  let opened; const r=new Node('div'),t=fresh();
  const start=shell.indexOf("const keyLink = el('span', 'board-key', t.key);");const end=shell.indexOf('r.appendChild(keyLink);',start)+'r.appendChild(keyLink);'.length;
  assert.ok(start>=0);vm.runInNewContext(shell.slice(start,end),{r,t,el:(...args)=>new Node(...args),loadBoard:()=>{},window:{AGENTMUXOpenCard:(key)=>{opened=key;}}});
  assert.equal(r.children.length,1);assert.equal(r.children[0].tag,'span');assert.equal(r.children[0].attrs.role,'button');
  r.children[0].events.click();assert.equal(opened,'TM-1');opened=null;
  r.children[0].events.keydown({key:'Enter',preventDefault(){}});assert.equal(opened,'TM-1');
});
test('entity renders before secondary reads and all sections load independently',async()=>{
  let resolve;const p=setup(fresh(),{read:path=>path.includes('/history?')?new Promise(r=>{resolve=r;}):undefined});
  await p.open();await settled();
  assert.equal(all(p.form('body')).find(n=>n.tag==='textarea').value,'<b>full body</b>');
  assert.ok(text(p.section('why')).includes('Waiting for proof'));assert.ok(text(p.section('roster')).includes('worker'));
  assert.deepEqual(p.requests,['api/board/entity?id=TM-1','api/board/history?id=TM-1&limit=200','api/board/why?id=TM-1','api/board/roster?id=TM-1']);
  resolve({events:[{ts:'today',actor:'me',event:'edit',detail:{fields:['body']}}]});await settled();assert.ok(text(p.section('history')).includes('body'));
});
for (const broken of ['history','why','roster']) test('secondary failure isolated: '+broken,async()=>{
  const p=setup(fresh(),{read:path=>path.includes('/'+broken+'?')?Promise.reject(Error('offline '+broken)):undefined});await p.open();await settled();
  assert.ok(text(p.section(broken)).includes('Could not load '+broken));assert.ok(p.form('title'));
  for(const name of ['history','why','roster'].filter(x=>x!==broken))assert.doesNotMatch(text(p.section(name)),/Could not load/);
});
test('epics skip task-only reads and fields',async()=>{
  const p=setup(fresh({key:'EP-1',kind:'epic'}));await p.open();await settled();
  assert.deepEqual(p.requests,['api/board/entity?id=EP-1','api/board/history?id=EP-1&limit=200']);
  assert.equal(p.form('deps'),undefined);assert.equal(p.form('assignee'),undefined);
});
test('acceptance uses one-based DOM indices and renumbers after remove then tick',async()=>{
  const p=setup();await p.open();
  let row=p.criteria()[0],tick=all(row).find(n=>n.type==='checkbox');tick.checked=true;await tick.events.change();assert.equal(p.posts.at(-1).index,1);
  await p.criteria()[1].children[1].events.click();assert.equal(p.posts.at(-1).index,2);assert.equal(p.posts.at(-1).remove,true);
  row=p.criteria()[1];assert.ok(text(row).includes('third'));assert.equal(row.dataset.index,'2');
  tick=all(row).find(n=>n.type==='checkbox');tick.checked=true;await tick.events.change();assert.equal(p.posts.at(-1).index,2);
  assert.equal(all(p.criteria()[1]).find(n=>n.type==='checkbox').checked,true);
  // Reading the DOM index at click time is intentional, not a captured forEach ordinal.
  row=p.criteria()[0];row.dataset.index='2';tick=all(row).find(n=>n.type==='checkbox');tick.checked=false;await tick.events.change();assert.equal(p.posts.at(-1).index,2);
});
const mappings=[
 ['body',['new body'],'update',{patch:{body:'new body'}}],
 ['title',['New title'],'update',{patch:{title:'New title'}}],
 ['assignee',['new-worker'],'update',{patch:{assignee:'new-worker'}}],
 ['priority',['low'],'update',{patch:{priority:'low'}}],
 ['estimate',['5.5'],'update',{patch:{estimate:5.5}}],
 ['status',['blocked','waiting for equipment'],'status',{status:'blocked',reason:'waiting for equipment'}],
 ['labels',['ready-for-agent'],'label',{label:'ready-for-agent',present:true}],
 ['deps',['TM-2'],'dep',{blockedBy:'TM-2',present:true}],
 ['evidence',['proof.log'],'evidence',{ref:'proof.log'}],
 ['commits',['abc1234'],'commit',{ref:'abc1234'}],
 ['comments',['read this'],'comment',{text:'read this'}],
 ['links',['related','TM-3'],'link',{type:'related',target:'TM-3',present:true}],
 ['touches',['src/file.js'],'touch',{path:'src/file.js'}],
 ['epic',['EP-2'],'move',{epic:'EP-2'}],
 ['acceptance',['new check'],'acceptance',{text:'new check'}],
];
for(const [field,values,op,payload] of mappings)test('field endpoint: '+field,async()=>{
  const p=setup();await p.open();await submit(p,field,values);
  assert.deepEqual(p.posts,[{endpoint:'api/board/'+op,id:'TM-1',...payload,actor:'dashboard'}]);
});
for(const [field,values,op,key] of [['labels',['ready'],'label','label'],['deps',['TM-2'],'dep','blockedBy'],['links',['related','TM-3'],'link','type']])test('remove endpoint: '+field,async()=>{
  const p=setup();await p.open();await submit(p,field,values,true);
  assert.equal(p.posts[0].endpoint,'api/board/'+op);assert.equal(p.posts[0].present,false);assert.equal(p.posts[0][key],values[0]);
});
test('writes normalize direct nested absent and deleted entity responses',async()=>{
  const p=setup();await p.open();
  p.respond(()=>response(fresh({title:'Direct'})));await submit(p,'title',['Direct']);assert.ok(text(p.drawer()).includes('Direct'));
  p.respond(()=>response({entity:fresh({title:'Nested'})}));await submit(p,'status',['open','']);assert.ok(text(p.drawer()).includes('Nested'));
  p.entity(fresh({title:'Fetched'}));p.respond(()=>response({changed:false}));await submit(p,'epic',['EP-1']);assert.ok(text(p.drawer()).includes('Fetched'));
  const reads=p.requests.length;p.respond(()=>response({deleted:'TM-1'}));await p.find('btn drawer-delete').events.click();
  assert.equal(p.posts.at(-1).endpoint,'api/board/delete');assert.equal(p.drawer().hidden,true);assert.equal(p.requests.length,reads);
});
test('409 renders every verbatim hint and message-only refusal; bypass is explicit',async()=>{
  const p=setup();await p.open();
  p.respond(()=>response({error:'Gate refused',missing:[{field:'body',hint:'exact --body <text>'},{field:'future',hint:'literal "future" remedy'}]},409));
  await submit(p,'status',['done','reason']);for(const str of ['Gate refused','body','future','exact --body <text>','literal "future" remedy'])assert.ok(text(p.find('drawer-notice')).includes(str),str);
  p.respond(()=>response({error:'No missing list'},409));await submit(p,'status',['done','']);assert.equal(text(p.find('drawer-notice')).trim(),'No missing list');
  p.respond(()=>response({entity:fresh({status:'done'}),bypassed:{reason:'operator override'}}));await submit(p,'status',['done','']);assert.ok(text(p.find('drawer-notice')).includes('Gate bypassed: operator override'));
});
test('drawer emits no data-agent because test_e2e.mjs page.$ is first-match',async()=>{
  const p=setup();await p.open();await settled();
  assert.equal(all(p.drawer()).some(n=>'agent' in n.dataset||'data-agent' in n.attrs),false,'test_e2e.mjs page.$ is first-match; a hidden drawer must not shadow live agent nodes');
  for(const s of ['proof','abc123','detail comment','2026-09-25','related: TM-4','main','/work'])assert.ok(text(p.drawer()).includes(s),s);
});
test('Jira link uses only validated HTTPS origin and key',async()=>{
  const p=setup();await p.open();const link=p.find('drawer-jira');assert.equal(link.href,'https://example.atlassian.net/browse/DEMO-1');assert.equal(link.rel,'noopener noreferrer');assert.equal(link.target,'_blank');
  for(const base of ['javascript:alert(1)','http://insecure.test','https://user:pass@example.com','https://example.com/path','https://example.com?next=x','https://example.com/#x']){
    const bad=setup(fresh(),{base});await bad.open();assert.equal(bad.find('drawer-jira'),undefined,base);
  }
  const bad=setup(fresh({jira_key:'../evil'}));await bad.open();assert.equal(bad.find('drawer-jira'),undefined);
});
test('late entity responses and close cannot reopen or replace the current card',async()=>{
  let resolve;const p=setup(fresh(),{read:path=>path==='api/board/entity?id=TM-1'?new Promise(r=>{resolve=r;}):undefined});
  const slow=p.open();p.entity(fresh({key:'TM-2',title:'Second'}));await p.open('TM-2');resolve(fresh());await slow;assert.ok(text(p.drawer()).includes('Second'));
  p.ctx.window.events.keydown({key:'Escape',preventDefault(){}});assert.equal(p.drawer().hidden,true);
  assert.equal(p.ctx.document.activeElement.focused,true);
});
test('write lock prevents duplicates and refusal keeps acceptance unchecked for retry',async()=>{
  const p=setup();await p.open();let resolve;
  p.respond(()=>new Promise(r=>{resolve=r;}));const first=submit(p,'title',['pending']);await submit(p,'title',['duplicate']);assert.equal(p.posts.length,1);
  resolve(response({error:'offline'},409));await first;
  p.respond(()=>response({error:'No tick'},409));const tick=all(p.criteria()[0]).find(n=>n.type==='checkbox');tick.checked=true;await tick.events.change();assert.equal(tick.checked,false);assert.equal(p.posts.length,2);
});
test('completed write unlocks before a slow board refresh',async()=>{
  let resolve;const refresh=new Promise(r=>{resolve=r;});
  const p=setup(fresh(),{after:()=>refresh});await p.open();
  const first=submit(p,'title',['saved']);await settled();
  const second=submit(p,'body',['next edit']);await settled();
  assert.equal(p.posts.length,2,'a saved entity must accept edits while the board refresh is pending');
  resolve();await Promise.all([first,second]);
});
test('entity load failure is visible and can be retried',async()=>{
  const p=setup(fresh(),{read:path=>path.includes('/entity?')?Promise.reject(Error('entity offline')):undefined});
  await p.open();assert.ok(text(p.drawer()).includes('Could not load TM-1: entity offline'));assert.equal(p.form('title'),undefined);
  p.read(()=>undefined);await p.open();assert.ok(p.form('title'));
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
