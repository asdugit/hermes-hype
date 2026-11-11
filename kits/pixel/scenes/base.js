// base.js — shared plumbing for pixel-kit scenes: per-shot Screens (world + UI), params with defaults, layout
// helpers, text QA registration and presenting the index buffers to the shot surface through the camera.
//
// Two surface modes (both pixel-exact, palette-locked):
//   * game res   (shot res [480,270] / [270,480]): the runtime upscales x4 nearest; camera zoom floors to 1 or 2.
//   * hi-res     (shot res = film size, e.g. [1920,1080]): the kit upscales itself, so the camera can zoom through
//                every integer pixel size (4, 5, 6, 7, 8 px per game px at 1080p) and pan by output pixels.
// Scenes always see a game-resolution ctx (gameCtx): ctx.w/h/safe are game px.
import { Screen } from './../core/gfx.js';
import { drawText, fontInfo } from './../core/text.js';
import { frameCam } from './../core/camera.js';
import { NONE, themedWords } from './../core/palette.js';

const SCREENS = new WeakMap(), UIS = new WeakMap(), GAMES = new WeakMap(), COMP = new WeakMap(), CANV = new WeakMap();

/** Output px per game px for a surface: params.px, else 4 for a film-size surface, 1 for a game-res one. */
export function pixelScale(ctx) {
  const p = ctx && ctx.params && Number(ctx.params.px);
  if (p > 0) return Math.max(1, Math.round(p));
  return Math.max(1, Math.floor(Math.min(ctx.w, ctx.h) / 270 + 1e-6));
}

/**
 * Game-resolution view of an SDK ctx (cached per ctx): w/h/safe in game px, text QA boxes buffered until present()
 * maps them through the camera. On a game-res surface it is a thin wrapper with k = 1.
 */
export function gameCtx(ctx) {
  if (!ctx || ctx.__game) return ctx;
  const k = pixelScale(ctx);
  let G = GAMES.get(ctx);
  if (G && G.__k === k && G.__ow === ctx.w && G.__oh === ctx.h) return G;
  const sf = ctx.safe || {}, boxes = [];
  G = Object.create(ctx);
  const push = (b) => { boxes.push(b); };
  Object.defineProperties(G, {
    __game: { value: true }, __out: { value: ctx }, __k: { value: k }, __ow: { value: ctx.w }, __oh: { value: ctx.h }, __boxes: { value: boxes },
    w: { value: Math.floor(ctx.w / k) }, h: { value: Math.floor(ctx.h / k) },
    safe: { value: { l: (sf.l || 0) / k, r: (sf.r || 0) / k, t: (sf.t || 0) / k, b: (sf.b || 0) / k } },
    qaText: { value: push }, registerText: { value: push },
  });
  GAMES.set(ctx, G);
  return G;
}

/** The shot's game-resolution WORLD Screen (created once per ctx), cleared to ink every call (purity). */
export function screenOf(ctx) {
  let S = SCREENS.get(ctx);
  if (!S || S.w !== ctx.w || S.h !== ctx.h) { S = new Screen(ctx.w, ctx.h); SCREENS.set(ctx, S); }
  S.unclip();
  S.fill('ink');
  S.cam = null;
  if (ctx.__boxes) ctx.__boxes.length = 0;
  return S;
}

/** The shot's UI Screen (same size, transparent): windows/menus/messages that the camera must not zoom. */
export function uiOf(ctx) {
  let U = UIS.get(ctx);
  if (!U || U.w !== ctx.w || U.h !== ctx.h) { U = new Screen(ctx.w, ctx.h); UIS.set(ctx, U); }
  U.unclip();
  U.d.fill(NONE);
  return U;
}

/** Merge documented defaults (SDK params schema) under the given params. */
export function withDefaults(schema, p) {
  const out = {};
  for (const [k, v] of Object.entries(schema || {})) out[k] = v && typeof v === 'object' && 'default' in v ? structuredClone(v.default) : v;
  for (const [k, v] of Object.entries(p || {})) if (v !== undefined && v !== null) out[k] = v;
  return out;
}

/** True for portrait surfaces (9:16). */
export const isVertical = (ctx) => ctx.h > ctx.w;

/**
 * Draw readable text and register its box for layout QA. Uses the runtime's QA hook when present
 * (ctx.qaText / ctx.registerText), so QA sees bitmap text the same way it sees ctx.text().
 */
export function say(ctx, S, str, x, y, o = {}) {
  const box = drawText(S, str, x, y, o);
  const font = o.font || 'mono', glyph = fontInfo(font).size * (o.scale || 1);
  const hook = ctx && (ctx.qaText || ctx.registerText);
  if (typeof hook === 'function' && str) {
    const b = { x: box.x, y: box.y, w: box.w, h: box.h, text: String(str), glyph_px: glyph, font };
    if (ctx.__game) Object.defineProperty(b, 'screen', { value: S, enumerable: false });
    try { hook.call(ctx, b); } catch { /* QA is advisory */ }
  }
  return box;
}

/**
 * Show the WORLD Screen through the camera (o.cam or S.cam: {zoom, x, y}) and lay the UI Screen (o.ui) on top at
 * zoom 1. Text boxes registered during the frame are forwarded to the runtime in surface pixels.
 */
export function present(ctx, S, o = {}) {
  const out = ctx.__out || ctx, k = ctx.__k || 1, U = o.ui || null, cam = o.cam || S.cam || null;
  const F = frameCam(cam, S.w, S.h, out.w, out.h, k);
  if (k <= 1) {
    let C = S;
    if (F.ps > 1 || F.ox || F.oy || U) {
      C = COMP.get(ctx);
      if (!C || C.w !== S.w || C.h !== S.h) { C = new Screen(S.w, S.h); COMP.set(ctx, C); }
      for (let j = 0; j < C.h; j++) {
        const sy = Math.floor((j - F.oy) / F.ps), row = j * C.w;
        for (let i = 0; i < C.w; i++) {
          const sx = Math.floor((i - F.ox) / F.ps);
          C.d[row + i] = (sx < 0 || sy < 0 || sx >= S.w || sy >= S.h) ? S.d[0] : S.d[sy * S.w + sx];
        }
      }
      if (U) for (let i = 0; i < U.d.length; i++) if (U.d[i] !== NONE) C.d[i] = U.d[i];
    }
    C.present(out.g, themedWords(ctx.film && ctx.film.theme));
  } else {
    const g = out.g, cv = canvases(ctx, S.w, S.h);
    S.present(cv.wg, themedWords(ctx.film && ctx.film.theme));
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.imageSmoothingEnabled = false;
    g.fillStyle = '#0d0b1e';
    if (F.ox > 0 || F.oy > 0 || F.ox + S.w * F.ps < out.w || F.oy + S.h * F.ps < out.h) g.fillRect(0, 0, out.w, out.h);
    g.drawImage(cv.w, F.ox, F.oy, S.w * F.ps, S.h * F.ps);
    if (U) { U.present(cv.ug, themedWords(ctx.film && ctx.film.theme)); g.drawImage(cv.u, 0, 0, U.w * k, U.h * k); }
    g.restore();
    if (out.canvas && out.canvas.dataset) out.canvas.dataset.gp = String(k);
  }
  forwardText(ctx, out, U, F, k);
}

function canvases(ctx, w, h) {
  let c = CANV.get(ctx);
  if (!c || c.w.width !== w || c.w.height !== h) {
    const wc = new OffscreenCanvas(w, h), uc = new OffscreenCanvas(w, h);
    c = { w: wc, u: uc, wg: wc.getContext('2d'), ug: uc.getContext('2d') };
    CANV.set(ctx, c);
  }
  return c;
}

/**
 * Forward buffered QA boxes in surface px: world text through the camera, UI text at the base scale. While the camera
 * is moved in, world text the camera crops or a UI window covers is not on screen to be read, so it is not reported.
 */
function forwardText(ctx, out, U, F, k) {
  const boxes = ctx.__boxes;
  if (!boxes || !boxes.length) return;
  const hook = out.qaText || out.registerText, ow = k > 1 ? out.w : out.w * k, oh = k > 1 ? out.h : out.h * k;
  const moved = F.ps !== (k > 1 ? k : 1) || F.ox || F.oy;
  if (typeof hook === 'function') {
    for (const b of boxes) {
      const world = !U || b.screen !== U;
      const s = world ? F.ps : k, ox = world ? F.ox : 0, oy = world ? F.oy : 0;
      const r = { x: ox + b.x * s, y: oy + b.y * s, w: b.w * s, h: b.h * s };
      if (world && (moved || U)) {
        const inside = r.x >= 0 && r.y >= 0 && r.x + r.w <= ow && r.y + r.h <= oh;
        if ((moved && !inside) || (U && covered(U, r, k > 1 ? k : 1) > 0.5)) continue;
      }
      try { hook.call(out, { ...r, text: b.text, glyph_px: b.glyph_px * s, font: b.font }); } catch { /* advisory */ }
    }
  }
  boxes.length = 0;
}

/** Fraction of a surface-px rect covered by opaque UI pixels (UI is drawn at scale k). */
function covered(U, r, k) {
  const x0 = Math.max(0, Math.floor(r.x / k)), y0 = Math.max(0, Math.floor(r.y / k));
  const x1 = Math.min(U.w, Math.ceil((r.x + r.w) / k)), y1 = Math.min(U.h, Math.ceil((r.y + r.h) / k));
  let n = 0, on = 0;
  for (let j = y0; j < y1; j++) for (let i = x0; i < x1; i++) { n++; if (U.d[j * U.w + i] !== NONE) on++; }
  return n ? on / n : 0;
}

/** Resolve an asset name (or object) to the runtime asset handle, or null. */
export function assetOf(ctx, name) {
  if (!name) return null;
  if (typeof name === 'object') return name;
  try { return ctx.asset(name) || null; } catch { return null; }
}

/** Wrap a scene def so render/cues see the game-resolution ctx (both surface modes). */
export function gameScene(sc) {
  const d = sc.def;
  return { id: sc.id, def: { ...d, render: (ctx, t, p) => d.render(gameCtx(ctx), t, p), ...(d.cues ? { cues: (ctx, p) => d.cues(gameCtx(ctx), p) } : {}) } };
}
