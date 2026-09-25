#!/usr/bin/env bash
# Isolated production-renderer tests. No HTTP writes or shared server restarts.
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  board_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$board_node_dir" ] || export PATH="$board_node_dir:$PATH"
fi
node <<'JS'
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const app = fs.readFileSync('dashboard/app.js', 'utf8');
const code = app.slice(app.indexOf('const EPIC_STATUSES ='), app.indexOf('const JOURNAL_KINDS ='));
let passed = 0, failed = 0;
async function test(name, fn) {
  try { await fn(); passed++; console.log('PASS ' + name); }
  catch (e) { failed++; console.error('FAIL ' + name, e); }
}
class Node {
  constructor(tag, cls = '', text = '') {
    this.tag = tag; this.className = cls; this.textContent = text;
    this.children = []; this.events = {};
    this.dataset = {}; this.style = {}; this.open = false;
    this.classList = {
      names: new Set(),
      toggle: (name, on) => { on ? this.classList.names.add(name) : this.classList.names.delete(name); },
      add: (name) => this.classList.names.add(name),
      remove: (name) => this.classList.names.delete(name),
      contains: (name) => this.classList.names.has(name),
    };
  }
  appendChild(n) { this.children.push(n); return n; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute() {}
  addEventListener(type, fn) { this.events[type] = fn; }
  // Only the selectors the renderer actually uses. A real matcher here would be a
  // second implementation of querySelectorAll to get wrong.
  querySelectorAll(selector) {
    const want = selector.includes('.task-row') ? 'task-row'
      : selector.includes('.epic') ? 'epic' : null;
    return nodes(this, '').filter(n => want && n.className.split(' ').includes(want));
  }
  querySelector(selector) {
    const key = /data-task="([^"]+)"/.exec(selector);
    const all = this.querySelectorAll(selector);
    return (key ? all.find(n => n.dataset.task === key[1]) : all[0]) || null;
  }
  contains() { return false; }
}
function nodes(root, cls) {
  return [root, ...root.children.flatMap(n => nodes(n, ''))].filter(n => !cls || n.className === cls);
}
function setup(seed) {
  let board = {epics: [{id:'EP-015', key:'EP-015', row:91, title:'Epic', status:'open'}], tasks:[
    {id:'TM-038', key:'TM-038', row:803, epic:'EP-015', title:'Task', status:'open', assignee:'worker'},
    {id:'TM-039', key:'TM-039', row:804, epic:null, title:'Unassigned', status:'backlog'}]};
  const requests = [], posts = [];
  // Seeded BEFORE the module body runs: the layout preferences are read once at
  // module scope, exactly as they are in the browser on a fresh page load.
  const store = new Map(Object.entries(seed || {}));
  const ctx = {document:{createElement:tag => new Node(tag)}, el:(...args)=>new Node(...args),
    els:{boardList:new Node('div'), boardStamp:new Node('span')},
    window:{confirm:()=>true}, say:(n,t)=>{ n.textContent=t; },
    // The epic card is a <details> now, so the renderer builds it through the
    // shared collapsible() helper rather than createElement.
    collapsible:(key, cls, open) => {
      const n = new Node('details', cls); n.open = open;
      n.dataset.collapseKey = key;      // as wireCollapsible does on the real one
      return n;
    },
    // Live-agent marking. The renderer tags names; a separate pass decorates them,
    // so the fixture only has to record the tag.
    liveAgents: new Map(),
    markAgent:(node, name) => { if (node && name) node.dataset.agent = name; return node; },
    refreshLiveMarks:() => {},
    rememberOpen:(key, open) => { store.set('open:' + key, open); },
    localStorage:{
      getItem:(k)=>store.has(k)?store.get(k):null,
      setItem:(k,v)=>store.set(k,v),
      removeItem:(k)=>store.delete(k),
    },
    CSS:{escape:(s)=>s},
    getJSON:async path=>{requests.push(path); assert.equal(path,'api/board/board'); return structuredClone(board);},
    post:async (path, payload)=>{
      posts.push([path, JSON.parse(JSON.stringify(payload))]);
      if (ctx.reject) throw Error('gate refused');
      const entity = [...board.epics,...board.tasks].find(e=>e.key===payload.id);
      if(path==='api/board/status') { assert.ok(entity); entity.status=payload.status; }
      else if(path==='api/board/delete') {
        assert.ok(entity); board.epics=board.epics.filter(e=>e.key!==payload.id);
        board.tasks=board.tasks.filter(t=>t.key!==payload.id && t.epic!==payload.id);
      } else if(path==='api/board/move') {
        assert.ok(entity); entity.epic=payload.epic;
      } else if(path==='api/tasks') { assert.equal(payload.epic_id,91); }
      else throw Error('unexpected endpoint '+path);
    }};
  vm.createContext(ctx); vm.runInContext(code,ctx);
  return {ctx, requests, posts, board, root:ctx.els.boardList, store};
}
// A drag, as the browser delivers it: a dataTransfer carrying the task key.
function transfer(key) {
  return {types:['text/plain'], dropEffect:'', effectAllowed:'',
          getData:()=>key, setData:()=>{}};
}
// A drop handler is synchronous - the browser gives it no way to be otherwise -
// so the refile it starts finishes after it returns. Let those turns run.
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
(async()=>{
await test('flat model groups tasks and displays all keys, including unassigned tasks',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  assert.deepEqual(nodes(s.root,'board-key').map(n=>n.textContent),['EP-015','TM-038','TM-039']);
  assert.equal(nodes(s.root,'epic').length,2);
  assert.equal(nodes(s.root,'t-agent')[0].textContent,'worker');
  assert.deepEqual(s.requests,['api/board/board']);
});
await test('both status menus preserve vocabulary and persist key-based changes after refresh',async()=>{
  for(const [index,key] of [[0,'EP-015'],[1,'TM-038']]) {
    const s=setup(); await s.ctx.loadBoard();
    const select=nodes(s.root).filter(n=>n.tag==='select')[index];
    assert.deepEqual(select.children.map(n=>n.value),['backlog','open','in_progress','blocked','parked','done']);
    select.value='parked'; await select.events.change();
    assert.deepEqual(s.posts[0],['api/board/status',{id:key,status:'parked',actor:'dashboard'}]);
    const refreshed=nodes(s.root).filter(n=>n.tag==='select')[index];
    assert.equal(refreshed.children.find(n=>n.selected).value,'parked');
  }
});
await test('delete task and epic use board keys and refresh the rendered list',async()=>{
  for(const [index,key] of [[0,'EP-015'],[1,'TM-038']]) {
    const s=setup(); await s.ctx.loadBoard();
    await nodes(s.root,'cbtn del')[index].events.click();
    assert.deepEqual(s.posts[0],['api/board/delete',{id:key,actor:'dashboard'}]);
    assert.ok(!nodes(s.root,'board-key').some(n=>n.textContent===key));
    if(index===0) assert.ok(!nodes(s.root,'board-key').some(n=>n.textContent==='TM-038'));
  }
});
await test('cancelled delete sends no request',async()=>{
  const s=setup(); s.ctx.window.confirm=()=>false; await s.ctx.loadBoard();
  await nodes(s.root,'cbtn del')[1].events.click(); assert.equal(s.posts.length,0);
});
await test('failed status resets selection and reports the backend refusal',async()=>{
  const s=setup(); await s.ctx.loadBoard(); s.ctx.reject=true;
  const select=nodes(s.root).find(n=>n.tag==='select'); select.value='done'; await select.events.change();
  assert.equal(select.value,'open'); assert.equal(select.disabled,false);
  assert.equal(s.ctx.els.boardStamp.textContent,'gate refused');
});
await test('failed delete leaves card available and reports error',async()=>{
  const s=setup(); await s.ctx.loadBoard(); s.ctx.reject=true;
  const btn=nodes(s.root,'cbtn del')[1]; await btn.events.click();
  assert.equal(btn.disabled,false); assert.equal(nodes(s.root,'board-key').length,3);
  assert.equal(s.ctx.els.boardStamp.textContent,'gate refused');
});
await test('add task retains the numeric row contract of the compatibility endpoint',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  const add=nodes(s.root,'row')[0]; add.children[0].value='New'; add.children[1].value='worker';
  await add.children[2].events.click();
  assert.deepEqual(s.posts[0],['api/tasks',{epic_id:91,title:'New',agent:'worker'}]);
});

// ── the epic card collapses, and its state is the operator's ────────────────
await test('epics render as collapsible cards that open by default',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  const cards=nodes(s.root,'epic');
  assert.equal(cards.length,2);
  for(const card of cards) {
    assert.equal(card.tag,'details');
    assert.equal(card.open,true,'a board that opens collapsed hides the work');
    assert.match(card.dataset.collapseKey,/^board:epic:/);
  }
  assert.deepEqual(cards.map(c=>c.dataset.epic),['EP-015','']);
});
await test('expand and collapse all write every card back to the shared open store',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  s.ctx.setEpicsOpen(false);
  assert.deepEqual(nodes(s.root,'epic').map(c=>c.open),[false,false]);
  assert.equal(s.store.get('open:board:epic:EP-015'),false);
  s.ctx.setEpicsOpen(true);
  assert.equal(s.store.get('open:board:epic:EP-015'),true);
});

// ── dragging a task refiles it, and that is real state ──────────────────────
await test('dropping a task on another epic posts a move and re-reads the board',async()=>{
  const s=setup();
  s.board.epics.push({id:'EP-016', key:'EP-016', row:92, title:'Other', status:'open'});
  await s.ctx.loadBoard();
  const target=nodes(s.root,'epic').find(c=>c.dataset.epic==='EP-016');
  const row=nodes(s.root,'task-row')[0];
  assert.equal(row.draggable,true);
  assert.equal(row.dataset.task,'TM-038');
  let prevented=false;
  await target.events.drop({preventDefault:()=>{prevented=true;},dataTransfer:transfer('TM-038')});
  assert.ok(prevented,'the drop must be consumed or the browser navigates');
  assert.deepEqual(s.posts[0],['api/board/move',{id:'TM-038',epic:'EP-016',actor:'dashboard'}]);
});
await test('dropping a task back on its own epic sends nothing',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  const own=nodes(s.root,'epic').find(c=>c.dataset.epic==='EP-015');
  await own.events.drop({preventDefault:()=>{},dataTransfer:transfer('TM-038')});
  assert.equal(s.posts.length,0);
});
await test('the ungrouped pile is not a drop target',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  const pile=nodes(s.root,'epic').find(c=>c.dataset.epic==='');
  assert.equal(pile.events.drop,undefined,'"Tasks without an epic" is a grouping, not a destination');
});
await test('a refused move reports the reason instead of swallowing it',async()=>{
  const s=setup();
  s.board.epics.push({id:'EP-016', key:'EP-016', row:92, title:'Other', status:'open'});
  await s.ctx.loadBoard(); s.ctx.reject=true;
  const target=nodes(s.root,'epic').find(c=>c.dataset.epic==='EP-016');
  await target.events.drop({preventDefault:()=>{},dataTransfer:transfer('TM-038')});
  await settle();
  assert.equal(s.ctx.els.boardStamp.textContent,'TM-038 not moved: gate refused');
});

// ── free layout is a view preference and never leaves the browser ───────────
await test('free layout positions cards from local storage and tidy clears them',async()=>{
  const s=setup({'agentmux.boardFree':'1',
                 'agentmux.boardPlacements.v1':JSON.stringify({'EP-015':{x:40,y:80,w:300}})});
  await s.ctx.loadBoard();
  const card=nodes(s.root,'epic').find(c=>c.dataset.epic==='EP-015');
  assert.equal(card.style.left,'40px');
  assert.equal(card.style.top,'80px');
  assert.ok(s.root.classList.contains('free'));
  assert.ok(!s.posts.length,'a card position is never sent anywhere');
});
await test('empty board and read failures remain visible',async()=>{
  const s=setup(); s.board.epics=[]; s.board.tasks=[]; await s.ctx.loadBoard();
  assert.equal(nodes(s.root,'empty').length,1);
  s.ctx.getJSON=async()=>{throw Error('offline');}; await s.ctx.loadBoard();
  assert.equal(s.ctx.els.boardStamp.textContent,'board unavailable: offline');
});
await test('an assignee is tagged with its agent name, for the live pass to find',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  const tagged=nodes(s.root).filter(n=>n.dataset.agent);
  assert.deepEqual(tagged.map(n=>n.dataset.agent),['worker'],
                   'the task assignee must carry data-agent');
  assert.equal(tagged[0].className,'t-agent');
});
await test('an agent bound to a card from ITS side is shown too',async()=>{
  // The `.task` sidecar binds agent -> card without the card naming the agent
  // back. That is the normal shape during a run, so the board looks both ways.
  const s=setup();
  s.ctx.liveAgents.set('runner',{name:'runner',task:'TM-038',cli:'codex'});
  await s.ctx.loadBoard();
  const names=nodes(s.root).filter(n=>n.dataset.agent).map(n=>n.dataset.agent);
  assert.ok(names.includes('runner'),'an agent bound by sidecar was not shown: '+names);
  const epicCard=nodes(s.root,'epic')[0];
  assert.ok(epicCard.classList.contains('has-live'),
            'the epic containing a worked-on task must be marked');
});
await test('an epic with nothing running is not marked',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  assert.ok(!nodes(s.root,'epic')[0].classList.contains('has-live'));
});
await test('the stamp counts both epics and tasks',async()=>{
  const s=setup(); await s.ctx.loadBoard();
  assert.equal(s.ctx.els.boardStamp.textContent,'1 epic, 2 tasks');
});
console.log(`passed ${passed}, failed ${failed}`); process.exitCode=failed ? 1 : 0;
})().catch(e=>{console.error(e); console.log(`passed ${passed}, failed ${failed+1}`); process.exitCode=1;});
JS
