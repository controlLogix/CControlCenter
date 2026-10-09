import test from 'node:test';
import assert from 'node:assert/strict';
import { renderScene } from './index.mjs';

const scene = {id:'test-scene',number:'01',phase:'P07',title:'Review',imageSrc:'data:image/png;base64,AAAA',alt:'Concept',summary:'Sample',preserves:'Existing view',enhancement:'Scoped view',limit:'Proposal only',question:'What is missing?'};
test('untrusted caption text cannot become active markup or attributes', () => {
  const html = renderScene({...scene,title:'<script>alert(1)</script>',alt:'" onload="alert(1)'});
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('alt="&quot; onload=&quot;alert(1)"'));
});
test('scene controls and notes keep an accessible name and stable target', () => {
  const html = renderScene(scene);
  assert.ok(html.includes('aria-labelledby="test-scene-title"'));
  assert.ok(html.includes('id="test-scene-title"'));
  assert.ok(html.includes('for="test-scene-note"'));
  assert.ok(html.includes('id="test-scene-note"'));
  assert.ok(html.includes('Proposed interface · fictional sample data'));
});
test('the presentation contract rejects external assets and unsafe anchors', () => {
  assert.throws(() => renderScene({...scene,imageSrc:'https://example.com/image.png'}));
  assert.throws(() => renderScene({...scene,id:'"><script>'}));
});
