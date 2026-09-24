#!/usr/bin/env bash
# Isolated palette/production applyTheme checks. No server or live state required.
set -uo pipefail
if ! command -v node >/dev/null 2>&1; then
  themes_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$themes_node_dir" ] || export PATH="$themes_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'FAIL: node is required'; echo 'passed 0, failed 1'; exit 1
fi
node <<'JS'
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
let passed = 0, failed = 0;
function test(name, fn) { try { fn(); passed++; console.log('PASS: '+name); } catch(e) { failed++; console.log('FAIL: '+name+' — '+e.message); } }
try {
const data = JSON.parse(fs.readFileSync('dashboard/themes.json','utf8'));
const app = fs.readFileSync('dashboard/app.js','utf8');
const surfaces = ['--bg','--panel','--panel-2','--surface-1','--surface-2'];
const foregrounds = ['--text','--muted','--accent','--accent-dim','--safe','--ok','--warn','--danger','--info', ...Array.from({length:6},(_,i)=>'--series-'+(i+1))];
function luminance(hex) {
  const linear = hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  return linear.reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
}
function contrast(a,b) { const x=luminance(a), y=luminance(b); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); }
test('eight unique themes, original IDs and complete declared vocabulary',()=>{
  assert.ok(data.themes.length>=8); assert.equal(new Set(data.themes.map(t=>t.id)).size,data.themes.length);
  for(const id of ['cc-dark','cc-light','classic-dark','high-contrast',data.default]) assert.ok(data.themes.some(t=>t.id===id));
  assert.equal(new Set(data.tokens).size,data.tokens.length);
  for(const token of [...surfaces,...foregrounds,'--border-subtle','--border-strong']) assert.ok(data.tokens.includes(token),token);
});
for(const theme of data.themes) {
  test(theme.id+' defines exactly the declared tokens as opaque colours',()=>{
    assert.deepEqual(Object.keys(theme.tokens).sort(),[...data.tokens].sort());
    Object.values(theme.tokens).forEach(v=>assert.match(v,/^#[a-f0-9]{6}$/i));
    assert.equal(theme.tokens['--ok'],theme.tokens['--safe']);
    assert.notEqual(theme.tokens['--surface-1'],theme.tokens['--surface-2']);
    assert.notEqual(theme.tokens['--border-subtle'],theme.tokens['--border-strong']);
    assert.equal(new Set(Array.from({length:6},(_,i)=>theme.tokens['--series-'+(i+1)])).size,6);
  });
  for(const surface of surfaces) test(theme.id+' foregrounds on '+surface,()=>{
    const minimum = theme.id==='high-contrast'?7:4.5;
    for(const token of foregrounds) assert.ok(contrast(theme.tokens[token],theme.tokens[surface])>=minimum,`${token}: ${contrast(theme.tokens[token],theme.tokens[surface]).toFixed(3)} < ${minimum}`);
    console.log('  minimum ratio '+Math.min(...foregrounds.map(t=>contrast(theme.tokens[t],theme.tokens[surface]))).toFixed(3));
  });
}
function page() {
  const style={setProperty(k,v){this[k]=v;}}, storage={}, term={options:{}}, calls=[];
  const context={document:{documentElement:{style,dataset:{}}},els:{themeSelect:{value:''},themeNote:{textContent:'',classList:{toggle(k,v){this[k]=v;}}}},localStorage:{setItem(k,v){storage[k]=v;}},panes:new Map([['fixture',{term}]]),xtermTheme(){return {background:style['--panel-2'],foreground:style['--text']};},renderSwatches(t){calls.push(t.id);}};
  vm.createContext(context);
  const start=app.indexOf('const THEME_KEY ='), end=app.indexOf('function renderSwatches(');
  assert.ok(start>=0 && end>start);
  vm.runInContext(app.slice(start,end),context);
  context.input=structuredClone(data);vm.runInContext('themeData = input;',context);
  return {context,style,storage,term,calls,apply:id=>context.applyTheme(id)};
}
test('all themes apply sequentially, update selector, persistence and terminal',()=>{
  const p=page();for(const theme of data.themes){p.apply(theme.id);for(const k of data.tokens)assert.equal(p.style[k],theme.tokens[k]);assert.equal(p.context.els.themeSelect.value,theme.id);assert.equal(p.storage['ccc.theme'],theme.id);assert.equal(p.style.colorScheme,theme.dark?'dark':'light');assert.equal(p.term.options.theme.background,theme.tokens['--panel-2']);assert.equal(p.context.els.themeNote.classList.warn,false);}
  p.apply('unknown');assert.equal(p.storage['ccc.theme'],data.themes[0].id);
});
for(const token of data.tokens) test('missing '+token+' is named and rejects the whole theme',()=>{
  const p=page();p.apply('high-contrast');const before=JSON.stringify(p.style);
  const broken=structuredClone(data.themes[0]);broken.id='incomplete-fixture';delete broken.tokens[token];p.context.input.themes.push(broken);p.context.els.themeSelect.value=broken.id;p.apply(broken.id);
  assert.ok(p.context.els.themeNote.textContent.includes('missing '+token));assert.ok(p.context.els.themeNote.textContent.includes(broken.id));assert.equal(p.context.els.themeNote.classList.warn,true);assert.equal(JSON.stringify(p.style),before);assert.equal(p.storage['ccc.theme'],'high-contrast');assert.equal(p.context.els.themeSelect.value,'high-contrast');assert.deepEqual(p.calls,['high-contrast']);
});
for(const [token,value] of [['--nav-w','#ffffff'],['--info','url(//example.invalid/pixel)'],['--series-1','image-set(url(x))']]) test('rejected '+token+' is named, cannot change layout or poison palette',()=>{
  const p=page();p.apply('cc-light');const before=JSON.stringify(p.style);const broken=structuredClone(data.themes[0]);broken.id='rejected-fixture';broken.tokens[token]=value;p.context.input.themes.push(broken);p.apply(broken.id);assert.ok(p.context.els.themeNote.textContent.includes('rejected '+token));assert.equal(JSON.stringify(p.style),before);assert.equal(p.storage['ccc.theme'],'cc-light');p.apply('high-contrast');assert.equal(p.context.els.themeNote.classList.warn,false);assert.equal(p.storage['ccc.theme'],'high-contrast');
});
test('incomplete first selection writes no partial palette',()=>{
 const p=page();delete p.context.input.themes[0].tokens['--info'];p.apply('cc-dark');assert.equal(p.style['--bg'],undefined);assert.equal(p.storage['ccc.theme'],undefined);assert.equal(p.context.els.themeSelect.value,'');
});
} catch(e) { failed++; console.log('FAIL: suite setup — '+e.stack); }
console.log(`passed ${passed}, failed ${failed}`);process.exitCode=failed?1:0;
JS
