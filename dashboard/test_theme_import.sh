#!/usr/bin/env bash
# Isolated production theme code with a DOM/storage harness. Never touches a server.
set -uo pipefail
if ! command -v node >/dev/null 2>&1; then
  theme_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$theme_node_dir" ] || export PATH="$theme_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'FAIL: node is required'; echo 'passed 0, failed 1'; exit 1
fi
node <<'JS'
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let passed=0,failed=0;
async function test(name,fn){try{await fn();passed++;console.log('PASS: '+name);}catch(e){failed++;console.log('FAIL: '+name+' — '+e.stack);}}
const app=fs.readFileSync('dashboard/app.js','utf8'), data=JSON.parse(fs.readFileSync('dashboard/themes.json','utf8'));
const source=app.slice(app.indexOf('const THEME_KEY ='),app.indexOf('// ════════════════════════════════════════════════════════════ data helpers'));
function element(){return {value:'',textContent:'',children:[],listeners:{},style:{setProperty(k,v){this[k]=v;}},dataset:{},classList:{toggle(k,v){this[k]=v;},add(k){this[k]=true;}},replaceChildren(){this.children=[];},appendChild(c){this.children.push(c);},addEventListener(k,fn){this.listeners[k]=fn;},click(){if(this.listeners.click)this.listeners.click();}};}
async function page(storage={},blocked=false){
 const ids={};for(const id of ['themeSelect','themeNote','swatches','themeJSON','themeImport','themeFile','themeExport','themeImportStatus'])ids[id]=element();
 const root=element(),term={options:{}},blobs=[];
 const c={document:{documentElement:root,getElementById:id=>ids[id],createElement:()=>element()},els:ids,panes:new Map([['p',{term}]]),xtermTheme:()=>({background:root.style['--bg']}),el:(tag,cls,text)=>Object.assign(element(),{textContent:text}),getJSON:async()=>structuredClone(data),localStorage:{getItem(k){if(blocked)throw Error('blocked');return storage[k]||null;},setItem(k,v){if(blocked)throw Error('blocked');storage[k]=v;}},Blob,URL:{createObjectURL(blob){blobs.push(blob);return 'blob:test';},revokeObjectURL(){}},setTimeout:fn=>fn()};
 vm.createContext(c);vm.runInContext(source,c);await c.loadThemes();return {c,ids,root,term,storage,blobs};
}
function theme(id='imported'){const t=structuredClone(data.themes[0]);t.id=id;t.name='<img src=x onerror=alert(1)>';t.tokens['--bg']='  #123456  ';return t;}
function snapshot(p){return JSON.stringify([p.root.style,p.root.dataset,p.storage,p.ids.themeSelect.children.map(x=>x.value),p.term]);}
(async()=>{
await test('paste handler applies immediately, updates terminal and persists; reload restores',async()=>{
 const p=await page(),t=theme();p.ids.themeJSON.value=JSON.stringify(t);p.ids.themeImport.listeners.click();assert.equal(p.root.dataset.theme,t.id);assert.equal(p.root.style['--bg'],'#123456');assert.equal(p.term.options.theme.background,'#123456');assert.deepEqual(JSON.parse(p.storage['agentmux.importedThemes']),[t]);assert.equal(p.ids.themeSelect.children.at(-1).textContent,t.name);
 const reloaded=await page(p.storage);assert.equal(reloaded.root.dataset.theme,t.id);assert.equal(reloaded.root.style['--bg'],'#123456');
});
await test('file handler imports JSON and resets file input',async()=>{const p=await page(),t=theme('file');const target={files:[{text:async()=>JSON.stringify(t)}],value:'theme.json'};await p.ids.themeFile.listeners.change({target});assert.equal(p.root.dataset.theme,t.id);assert.equal(target.value,'');});
await test('file read failure is visible without applying',async()=>{const p=await page(),before=snapshot(p);await p.ids.themeFile.listeners.change({target:{files:[{text:async()=>{throw Error('unreadable');}}]}});assert.equal(snapshot(p),before);assert.match(p.ids.themeImportStatus.textContent,/unreadable/);});
for(const token of data.tokens)await test('missing '+token+' rejected atomically',async()=>{const p=await page(),before=snapshot(p),t=theme();delete t.tokens[token];assert.equal(p.c.importTheme(JSON.stringify(t)),false);assert.equal(snapshot(p),before);assert.ok(p.ids.themeImportStatus.textContent.includes(token));});
for(const [key,value] of [['--font','serif'],['--bg','url(//host/pixel)'],['--bg','image-set(url(x))'],['--bg','var(--font)'],['--bg','@font-face'],['--bg',null],['--bg',{}]])await test('reject unsafe '+key+' '+JSON.stringify(value),async()=>{const p=await page(),before=snapshot(p),t=theme();t.tokens[key]=value;assert.equal(p.c.importTheme(JSON.stringify(t)),false);assert.equal(snapshot(p),before);assert.ok(p.ids.themeImportStatus.textContent.includes(key));});
for(const [key,value] of [['dark','yes'],['id',''],['name',{}],['note',[]],['tokens',[]],['font','https://host/font']])await test('invalid metadata '+key+' is named',async()=>{const p=await page(),before=snapshot(p),t=theme();t[key]=value;assert.equal(p.c.importTheme(JSON.stringify(t)),false);assert.equal(snapshot(p),before);assert.ok(p.ids.themeImportStatus.textContent.includes(key));});
for(const raw of ['{','null','[]'])await test('malformed document '+raw,async()=>{const p=await page(),before=snapshot(p);assert.equal(p.c.importTheme(raw),false);assert.equal(snapshot(p),before);});
await test('all rejected and missing keys are reported together',async()=>{const p=await page(),t=theme();t.dark='invalid';delete t.tokens['--accent'];t.tokens['--bg']='url(x)';t.tokens['--font']='serif';p.c.importTheme(JSON.stringify(t));for(const k of ['dark','--accent','--bg','--font'])assert.ok(p.ids.themeImportStatus.textContent.includes(k));});
await test('built-in collision refuses changed palette without overwriting',async()=>{const p=await page(),before=snapshot(p),t=theme(data.themes[0].id);assert.equal(p.c.importTheme(JSON.stringify(t)),false);assert.match(p.ids.themeImportStatus.textContent,/built-in/);assert.equal(snapshot(p),before);});
await test('imported collision refuses changed palette',async()=>{const p=await page(),t=theme();p.c.importTheme(JSON.stringify(t));const before=snapshot(p);t.tokens['--bg']='#ffffff';assert.equal(p.c.importTheme(JSON.stringify(t)),false);assert.equal(snapshot(p),before);});
await test('export download and pasted JSON round-trip exactly including whitespace',async()=>{const p=await page(),t=theme();p.c.importTheme(JSON.stringify(t));p.ids.themeExport.listeners.click();const exported=await p.blobs[0].text();assert.equal(exported,p.ids.themeJSON.value);assert.deepEqual(JSON.parse(exported),t);const fresh=await page();assert.equal(fresh.c.importTheme(exported),true);fresh.c.exportTheme();assert.equal(await fresh.blobs[0].text(),exported);});
await test('built-in export round-trips unchanged without duplicating or persisting as imported',async()=>{const p=await page();p.c.exportTheme();const exported=await p.blobs[0].text();assert.equal(p.c.importTheme(exported),true);p.c.exportTheme();assert.equal(await p.blobs[1].text(),exported);assert.equal(p.ids.themeSelect.children.length,data.themes.length);assert.deepEqual(JSON.parse(p.storage['agentmux.importedThemes']),[]);});
await test('blocked storage renders built-ins and permits session import/export',async()=>{const p=await page({},true);assert.equal(p.root.dataset.theme,data.default);assert.equal(p.c.importTheme(JSON.stringify(theme())),true);assert.equal(p.root.dataset.theme,'imported');assert.match(p.ids.themeImportStatus.textContent,/this session/);p.c.exportTheme();assert.deepEqual(JSON.parse(await p.blobs[0].text()),theme());});
await test('corrupt saved JSON leaves built-ins usable',async()=>{const p=await page({'agentmux.importedThemes':'{'});assert.equal(p.root.dataset.theme,data.default);assert.match(p.ids.themeImportStatus.textContent,/Could not restore/);});
await test('stored unsafe or colliding themes rejected before swatches; valid entries recover',async()=>{const bad=theme('unsafe');bad.tokens['--bg']='url(//host)';const p=await page({'agentmux.importedThemes':JSON.stringify([bad,theme(data.default),theme('good')]),'agentmux.theme':'good'});assert.equal(p.root.dataset.theme,'good');assert.equal(p.ids.themeSelect.children.length,data.themes.length+1);assert.match(p.ids.themeImportStatus.textContent,/--bg/);assert.match(p.ids.themeImportStatus.textContent,/built-in/);});
await test('transfer markup is accessible and production theme code has no HTML injection sink',()=>{const html=fs.readFileSync('dashboard/index.html','utf8');for(const id of ['themeJSON','themeFile','themeImport','themeExport','themeImportStatus'])assert.ok(html.includes('id="'+id+'"'));assert.match(html,/id="themeImportStatus"[^>]*role="status"/);assert.ok(!source.includes('innerHTML'));});
})().catch(e=>{failed++;console.log('FAIL: setup '+e.stack);}).finally(()=>{console.log(`passed ${passed}, failed ${failed}`);process.exitCode=failed?1:0;});
JS
