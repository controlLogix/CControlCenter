/* agentmux field — the slow shader behind everything.
 *
 * Raw WebGL, no three.js. The 3D device view needs three; a background does
 * not, and adding 600 KB to every page load for a gradient would be a poor
 * trade in a product whose dependency policy is "installs from a clone".
 *
 * WHAT IT DRAWS. Domain-warped fractal noise, coloured from the token ramp,
 * drifting slowly and leaning very slightly toward the pointer. Same technique
 * as the reference's own shaders (u_warpScale / u_noiseOffset / u_seed /
 * u_mousePos / u_fadeIn are its uniform names, reused here deliberately so the
 * lineage is legible).
 *
 * WHAT IT MUST NEVER DO, and each of these is enforced below rather than
 * intended:
 *
 *   - Never block first paint. It compiles after the page is interactive and
 *     fades in. A shader that costs a frame on load has made the product feel
 *     slower in exchange for atmosphere.
 *   - Never fail loudly. No WebGL, a lost context, a compile error on some
 *     plant-floor Intel driver: the canvas is removed and the product is
 *     exactly as it was. This is decoration; it gets no error surface.
 *   - Never spin when nobody is looking. Paused on hidden tabs and when
 *     reduced motion is set. This runs on machines that sit on a line for
 *     weeks, and a full-screen fragment shader at 60fps forever is rude.
 *   - Never compete with data. It renders at a fraction of device resolution
 *     and at a capped frame rate, under a --field-opacity that starts low.
 */

const VERT = `#version 300 es
in vec2 a_pos;
out vec2 vUv;
void main() {
  vUv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

const FRAG = `#version 300 es
precision mediump float;

in vec2 vUv;
out vec4 fragColor;

uniform vec2  iResolution;
uniform float iTime;
uniform vec2  u_mousePos;
uniform float u_fadeIn;
uniform float u_warpScale;
uniform float u_noiseScale;
uniform vec3  u_seed;
uniform vec3  u_cool;     // the blue-grey complement
uniform vec3  u_accent;   // the warm end
uniform vec3  u_base;     // the surface it sits on

// Value noise. Cheap, and at this scale and opacity the difference between
// this and simplex is not visible - but the difference in cost on an
// integrated GPU is.
float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21) + u_seed.xy);
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);          // smoothstep
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
  float v = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 4; i++) {         // 4 octaves; 5 is not visible here
    v += amp * noise(p);
    p *= 2.02;                          // non-integer, so octaves do not align
    amp *= 0.5;
  }
  return v;
}

void main() {
  // Aspect-correct, so the field does not stretch on a wide monitor.
  vec2 uv = vUv;
  vec2 p = (uv - 0.5) * vec2(iResolution.x / max(iResolution.y, 1.0), 1.0);

  float t = iTime * 0.022;              // slow. This should never read as motion.

  // Lean toward the pointer, very slightly. The clamp matters: without it a
  // mouse at the edge of an ultrawide drags the whole field off-centre.
  vec2 lean = clamp(u_mousePos - 0.5, -0.5, 0.5) * 0.14;

  // Domain warp: sample noise with coordinates that are themselves noise.
  // This is what stops it looking like clouds.
  vec2 q = vec2(fbm(p * u_noiseScale + t),
                fbm(p * u_noiseScale + vec2(5.2, 1.3) - t));
  vec2 r = vec2(fbm(p * u_noiseScale + u_warpScale * q + vec2(1.7, 9.2) + t * 0.7),
                fbm(p * u_noiseScale + u_warpScale * q + vec2(8.3, 2.8) - t * 0.6));
  float f = fbm(p * u_noiseScale + u_warpScale * r + lean);

  // Colour. Mostly the cool complement; the accent only shows in the top of
  // the range, so the field reads as instrumentation with a warm edge rather
  // than as an orange wash.
  vec3 col = mix(u_base, u_cool, smoothstep(0.25, 0.85, f));
  col = mix(col, u_accent, smoothstep(0.72, 1.0, f) * 0.55);

  // Vignette, so the centre - where the data is - stays quietest.
  float vig = 1.0 - smoothstep(0.35, 1.25, length(p));
  col *= mix(0.55, 1.0, vig);

  // Ordered dither. Banding is the failure mode of any smooth dark gradient on
  // an 8-bit panel, and it is very visible on the near-black surfaces here.
  float dither = (hash(gl_FragCoord.xy) - 0.5) / 255.0;
  col += dither;

  fragColor = vec4(col, u_fadeIn);
}`;

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    gl.deleteShader(sh);
    return null;      // deliberately silent: see the header
  }
  return sh;
}

function readToken(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  } catch (_) { return fallback; }
}

/** "#rrggbb" -> [r,g,b] in 0..1. Returns the fallback on anything unexpected. */
function hexToRgb(hex, fallback = [0, 0, 0]) {
  const m = /^#?([0-9a-f]{6})$/i.exec((hex || '').trim());
  if (!m) return fallback;
  const n = parseInt(m[1], 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

export function startField(options = {}) {
  const {
    maxFps = 30,        // half rate. Nobody can see 60fps in a 3% overlay.
    scale = 0.5,        // render at half resolution, upscale. Quarter the fill cost.
    warpScale = 3.4,
    noiseScale = 1.7,
  } = options;

  // Reduced motion is checked here AND expressed as --field-opacity: 0 in the
  // tokens. Two guards because this one stops the work, and that one stops the
  // pixels - and either alone leaves the other half happening.
  let reduced = false;
  try {
    reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
           || document.documentElement.dataset.motion === 'off';
  } catch (_) { /* ignore */ }
  if (reduced) return { stop() {} };

  const canvas = document.createElement('canvas');
  canvas.className = 'field-canvas';
  canvas.setAttribute('aria-hidden', 'true');

  const gl = canvas.getContext('webgl2', {
    alpha: true, antialias: false, depth: false, stencil: false,
    powerPreference: 'low-power',     // it is a background. Do not wake the dGPU.
    failIfMajorPerformanceCaveat: true,
  });
  if (!gl) return { stop() {} };      // software rendering: not worth it

  const vs = compile(gl, gl.VERTEX_SHADER, VERT);
  const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return { stop() {} };

  const prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return { stop() {} };
  gl.useProgram(prog);

  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'a_pos');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

  const U = (n) => gl.getUniformLocation(prog, n);
  const uRes = U('iResolution'), uTime = U('iTime'), uMouse = U('u_mousePos');
  const uFade = U('u_fadeIn'), uWarp = U('u_warpScale'), uNoise = U('u_noiseScale');
  const uSeed = U('u_seed'), uCool = U('u_cool'), uAccent = U('u_accent'), uBase = U('u_base');

  gl.uniform1f(uWarp, warpScale);
  gl.uniform1f(uNoise, noiseScale);
  gl.uniform3f(uSeed, Math.random(), Math.random(), Math.random());

  // Colours come from the tokens, so retheming the product rethemes the field.
  // A shader with its own hex literals is a second source of truth for the
  // palette, and it is the one nobody remembers to update.
  function syncColours() {
    const cool = hexToRgb(readToken('--cool-deep', '#6a819b'), [0.42, 0.51, 0.61]);
    const acc = hexToRgb(readToken('--accent', '#f6623e'), [0.96, 0.38, 0.24]);
    const base = hexToRgb(readToken('--surface-void', '#0d0d0f'), [0.05, 0.05, 0.06]);
    gl.uniform3fv(uCool, cool);
    gl.uniform3fv(uAccent, acc);
    gl.uniform3fv(uBase, base);
  }
  syncColours();

  let width = 0, height = 0;
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);   // capped: see header
    const w = Math.max(1, Math.floor(window.innerWidth * dpr * scale));
    const h = Math.max(1, Math.floor(window.innerHeight * dpr * scale));
    if (w === width && h === height) return;
    width = canvas.width = w;
    height = canvas.height = h;
    gl.viewport(0, 0, w, h);
    gl.uniform2f(uRes, w, h);
  }

  const mouse = { x: 0.5, y: 0.5 };
  const target = { x: 0.5, y: 0.5 };
  function onMove(e) {
    target.x = e.clientX / Math.max(window.innerWidth, 1);
    target.y = 1 - e.clientY / Math.max(window.innerHeight, 1);
  }

  let raf = 0, running = true, fade = 0, last = 0;
  const started = performance.now();
  const frameBudget = 1000 / maxFps;

  function frame(now) {
    if (!running) return;
    raf = requestAnimationFrame(frame);
    if (now - last < frameBudget) return;
    last = now;

    resize();
    // Ease the pointer rather than tracking it. A field that snaps to the
    // cursor reads as a cursor effect; one that lags reads as depth.
    mouse.x += (target.x - mouse.x) * 0.045;
    mouse.y += (target.y - mouse.y) * 0.045;

    fade = Math.min(1, fade + 0.02);
    gl.uniform1f(uTime, (now - started) / 1000);
    gl.uniform2f(uMouse, mouse.x, mouse.y);
    gl.uniform1f(uFade, fade);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function onVisibility() {
    if (document.hidden) {
      running = false;
      cancelAnimationFrame(raf);
    } else if (!running) {
      running = true;
      last = 0;
      raf = requestAnimationFrame(frame);
    }
  }

  // A lost context on a driver reset must not leave a black rectangle over the
  // product. Take the canvas out and stay out.
  function onLost(e) { e.preventDefault(); stop(); }

  function stop() {
    running = false;
    cancelAnimationFrame(raf);
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('resize', resize);
    document.removeEventListener('visibilitychange', onVisibility);
    canvas.removeEventListener('webglcontextlost', onLost);
    canvas.remove();
  }

  document.body.appendChild(canvas);
  resize();
  window.addEventListener('pointermove', onMove, { passive: true });
  window.addEventListener('resize', resize);
  document.addEventListener('visibilitychange', onVisibility);
  canvas.addEventListener('webglcontextlost', onLost);
  raf = requestAnimationFrame(frame);
  requestAnimationFrame(() => canvas.classList.add('is-ready'));

  return { stop, syncColours, canvas };
}
