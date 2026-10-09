/**
 * Scene organism for the Agentmux visual review of October 9, 2026.
 *
 * Pure presentation: renderScene(scene) turns one scene's explicit props into
 * an HTML string. It performs no I/O and reads no page or feature state.
 * Every text prop is HTML-escaped. The image must be an embedded PNG data URI,
 * so the review page never loads a remote asset.
 *
 * Props: id, number ('01'..'06'), title, phase, summary, preserves,
 * enhancement, limit, question, imageSrc, alt.
 */

export const CONCEPT_LABEL = 'Proposed interface · fictional sample data';
export const SCENE_TOTAL = '06';
export const IMAGE_WIDTH = 1672;
export const IMAGE_HEIGHT = 941;

const SAFE_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SCENE_NUMBER = /^[0-9]{2}$/;
const PNG_PREFIX = 'data:image/png;base64,';
const BASE64_BODY = /^[A-Za-z0-9+\/]+={0,2}$/;
const TEXT_PROPS = ['title', 'phase', 'summary', 'preserves', 'enhancement', 'limit', 'question', 'alt'];
const ENTITIES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/** Escape a value for HTML text or a double-quoted attribute. */
export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ENTITIES[char]);
}

function readText(scene, prop) {
  const value = scene[prop];
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`Scene prop '${prop}' must be a non-empty string.`);
  }
  return escapeHtml(value);
}

function readImage(value) {
  if (typeof value !== 'string' || !value.startsWith(PNG_PREFIX) || !BASE64_BODY.test(value.slice(PNG_PREFIX.length))) {
    throw new Error('Scene image must be an embedded PNG data URI.');
  }
  return value;
}

/** Render one review scene. Throws if a prop is missing or unsafe. */
export function renderScene(scene) {
  if (!scene || typeof scene !== 'object') throw new Error('Scene props must be an object.');
  const id = String(scene.id ?? '');
  if (!SAFE_ID.test(id)) throw new Error('Scene ID must be a safe document anchor.');
  const number = String(scene.number ?? '');
  if (!SCENE_NUMBER.test(number)) throw new Error('Scene number must be two digits, such as 01.');
  const imageSrc = readImage(scene.imageSrc);
  const text = Object.fromEntries(TEXT_PROPS.map(prop => [prop, readText(scene, prop)]));
  const questionNumber = String(Number(number));

  return `<section class="scene" id="${id}" aria-labelledby="${id}-title" data-number="${number}" data-nav-section>
  <header class="scene__head">
    <p class="scene__num" aria-hidden="true">${number}</p>
    <div class="scene__heading">
      <p class="scene__kicker"><span>Scene ${number} of ${SCENE_TOTAL}</span><span class="scene__phase">Plan phases ${text.phase}</span></p>
      <h2 class="scene__title" id="${id}-title">${text.title}</h2>
    </div>
  </header>
  <figure class="scene__figure">
    <div class="scene__frame">
      <div class="scene__bar">
        <span class="concept-tag">${CONCEPT_LABEL}</span>
        <span class="scene__bar-hint">Dashboard on the left · illustrative AI terminal on the right</span>
        <button type="button" class="scene__enlarge" data-enlarge="${id}" hidden>Enlarge image<span class="vh"> for scene ${number}</span></button>
      </div>
      <img class="scene__image" id="${id}-image" src="${imageSrc}" width="${IMAGE_WIDTH}" height="${IMAGE_HEIGHT}" alt="${text.alt}" decoding="async">
    </div>
    <figcaption class="scene__caption"><span class="scene__caption-label">Figure ${number}</span><span class="scene__caption-text">${text.summary}</span></figcaption>
  </figure>
  <div class="scene__body">
    <dl class="scene__facts">
      <div class="scene__fact"><dt>Keeps</dt><dd>${text.preserves}</dd></div>
      <div class="scene__fact"><dt>Adds or extends</dt><dd>${text.enhancement}</dd></div>
      <div class="scene__fact scene__fact--limit"><dt>Limits of this concept</dt><dd>${text.limit}</dd></div>
    </dl>
    <div class="scene-note">
      <p class="scene-note__eyebrow">Review question ${questionNumber}</p>
      <label class="scene-note__question" for="${id}-note">${text.question}</label>
      <textarea class="scene-note__input" id="${id}-note" name="${id}-note" data-note="${id}" data-number="${number}" data-title="${text.title}" rows="6" maxlength="20000" aria-describedby="${id}-note-help" placeholder="A concern, a missing behavior or a suggested change"></textarea>
      <p class="scene-note__help" id="${id}-note-help">Feedback only. A note does not approve building or merging this design.</p>
      <div class="scene-note__print" data-print-for="${id}-note" aria-hidden="true"></div>
    </div>
  </div>
</section>`;
}
