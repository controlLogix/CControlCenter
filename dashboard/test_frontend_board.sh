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
  constructor(tag, cls = '', text = '') { this.tag = tag; this.className = cls; this.textContent = text; this.children = []; this.events = {}; }
  appendChild(n) { this.children.push(n); return n; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute() {}
  addEventListener(type, fn) { this.events[type] = fn; }
}
function nodes(root, cls) {
  return [root, ...root.children.flatMap(n => nodes(n, ''))].filter(n => !cls || n.className === cls);
}
function setup() {
  let board = {epics: [{id:'EP-015', key:'EP-015', row:91, title:'Epic', status:'open'}], tasks:[
    {id:'TM-038', key:'TM-038', row:803, epic:'EP-015', title:'Task', status:'open', assignee:'worker'},
    {id:'TM-039', key:'TM-039', row:804, epic:null, title:'Unassigned', status:'backlog'}]};
  const requests = [], posts = [];
  const ctx = {document:{createElement:tag => new Node(tag)}, el:(...args)=>new Node(...args),
    els:{boardList:new Node('div'), boardStamp:new Node('span')},
    window:{confirm:()=>true}, say:(n,t)=>{ n.textContent=t; },
    getJSON:async path=>{requests.push(path); assert.equal(path,'api/board/board'); return structuredClone(board);},
    post:async (path, payload)=>{
      posts.push([path, JSON.parse(JSON.stringify(payload))]);
      if (ctx.reject) throw Error('gate refused');
      const entity = [...board.epics,...board.tasks].find(e=>e.key===payload.id);
      if(path==='api/board/status') { assert.ok(entity); entity.status=payload.status; }
      else if(path==='api/board/delete') {
        assert.ok(entity); board.epics=board.epics.filter(e=>e.key!==payload.id);
        board.tasks=board.tasks.filter(t=>t.key!==payload.id && t.epic!==payload.id);
      } else if(path==='api/tasks') { assert.equal(payload.epic_id,91); }
      else throw Error('unexpected endpoint '+path);
    }};
  vm.createContext(ctx); vm.runInContext(code,ctx);
  return {ctx, requests, posts, board, root:ctx.els.boardList};
}
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
await test('empty board and read failures remain visible',async()=>{
  const s=setup(); s.board.epics=[]; s.board.tasks=[]; await s.ctx.loadBoard();
  assert.equal(nodes(s.root,'empty').length,1);
  s.ctx.getJSON=async()=>{throw Error('offline');}; await s.ctx.loadBoard();
  assert.equal(s.ctx.els.boardStamp.textContent,'board unavailable: offline');
});
console.log(`passed ${passed}, failed ${failed}`); process.exitCode=failed ? 1 : 0;
})().catch(e=>{console.error(e); console.log(`passed ${passed}, failed ${failed+1}`); process.exitCode=1;});
JS
