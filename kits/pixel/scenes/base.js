// base.js — shared plumbing for pixel-kit scenes: per-shot Screen, params with defaults, layout helpers,
// text QA registration and presenting the index buffer to ctx.g.
import { Screen } from './../core/gfx.js';
import { drawText, fontInfo } from './../core/text.js';

const SCREENS = new WeakMap();

/** The shot's game-resolution Screen (created once per ctx, sized ctx.w x ctx.h), cleared to ink every call so a
 *  render never sees the previous frame (purity). */
export function screenOf(ctx) {
  let S = SCREENS.get(ctx);
  if (!S || S.w !== ctx.w || S.h !== ctx.h) { S = new Screen(ctx.w, ctx.h); SCREENS.set(ctx, S); }
  S.unclip();
  S.fill('ink');
  return S;
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
    try { hook.call(ctx, { x: box.x, y: box.y, w: box.w, h: box.h, text: String(str), glyph_px: glyph, font }); } catch { /* QA is advisory */ }
  }
  return box;
}

/** Copy the Screen to the shot surface. */
export function present(ctx, S) { S.present(ctx.g); }

/** Resolve an asset name (or object) to the runtime asset handle, or null. */
export function assetOf(ctx, name) {
  if (!name) return null;
  if (typeof name === 'object') return name;
  try { return ctx.asset(name) || null; } catch { return null; }
}
