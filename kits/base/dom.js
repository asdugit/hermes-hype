// Auteur kits/base — DOM helpers for 'dom' layer scenes (SDK §4): element builder, a cached style
// setter (writes only changed properties; the final DOM is still a pure function of t), the scene
// frame (reference-size layout + theme), word splitting and theme registry.

import { hash32 } from './motion.js';

/** Create an element: h('div', 'cls a', {style:..., text:...}, [children]). */
export function h(tag, cls = '', props = null, kids = null) {
  const el = document_ref().createElement(tag);
  if (cls) el.className = cls;
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v == null) continue;
      if (k === 'text') el.textContent = String(v);
      else if (k === 'html') el.innerHTML = v; // only ever used with our own static markup (icons)
      else if (k === 'style') el.style.cssText = v;
      else el.setAttribute(k, String(v));
    }
  }
  if (kids) for (const c of kids) if (c) el.appendChild(typeof c === 'string' ? document_ref().createTextNode(c) : c);
  return el;
}

// The scene root's ownerDocument: scenes build nodes only inside ctx.root, so we never touch the
// global document object directly (SDK §7).
let DOC = null;
export function bindDocument(root) { DOC = root.ownerDocument; }
function document_ref() { return DOC; }

/** Set style properties, skipping unchanged values. props: {opacity: '1', transform: '...', '--x': '3px'}. */
export function css(el, props) {
  const cache = el.__srs || (el.__srs = {});
  for (const k in props) {
    const v = props[k];
    if (cache[k] === v) continue;
    cache[k] = v;
    if (k.startsWith('--')) el.style.setProperty(k, v);
    else el.style[k] = v;
  }
}

/** Toggle a class (cached). */
export function cls(el, name, on) {
  const key = 'c:' + name;
  const cache = el.__srs || (el.__srs = {});
  if (cache[key] === on) return;
  cache[key] = on;
  el.classList.toggle(name, !!on);
}

/** Set text (cached). */
export function text(el, s) {
  if (el.__srt === s) return;
  el.__srt = s;
  el.textContent = s;
}

// ---------------------------------------------------------------- themes
const THEMES = new Map();

/** Register a theme: CSS text or a CSSStyleSheet (from `import x from './theme.css' with {type:'css'}`). */
export function registerTheme(name, sheetOrText) {
  const text = typeof sheetOrText === 'string' ? sheetOrText
    : Array.from(sheetOrText.cssRules, (r) => r.cssText).join('\n');
  THEMES.set(name, text);
}
export function themeCss(name) { return THEMES.get(name) || ''; }
export function themeNames() { return [...THEMES.keys()]; }

const injected = new WeakMap();
/** Inject CSS once per scene root (prefers the runtime's ctx.css, else a <style> inside ctx.root). */
export function injectCss(ctx, text) {
  if (!text) return;
  if (typeof ctx.css === 'function') { ctx.css(text); return; }
  let set = injected.get(ctx.root);
  if (!set) injected.set(ctx.root, (set = new Set()));
  const key = hash32(text);
  if (set.has(key)) return;
  set.add(key);
  const st = document_ref().createElement('style');
  st.textContent = text;
  ctx.root.appendChild(st);
}

// ---------------------------------------------------------------- scene frame
/**
 * Surface size in px. Defensive: some runtime builds expose a DOM builder as ctx.h on 'dom' layers,
 * so fall back to the root's size / the film size when ctx.h is not a number.
 */
export function surfaceSize(ctx) {
  const film = ctx.film || {};
  const w = typeof ctx.w === 'number' ? ctx.w : (parseFloat(ctx.root && ctx.root.style.width) || film.w || 1920);
  const hh = typeof ctx.h === 'number' ? ctx.h : (parseFloat(ctx.root && ctx.root.style.height) || film.h || 1080);
  return [w, hh];
}

/**
 * Build the standard scene frame inside ctx.root. Layout happens in reference pixels where the short
 * side is 1080 (1920x1080 or 1080x1920), scaled to the surface, so every size in the kits is "px at 1080p".
 * Returns {el, bg, cam, ov, W, H, k, portrait, square, safe, theme}.
 */
export function frame(ctx, p, kind, baseCss) {
  bindDocument(ctx.root);
  const theme = String((p && p.theme) || 'base');
  injectCss(ctx, baseCss);
  injectCss(ctx, themeCss(theme));
  const [sw, sh] = surfaceSize(ctx);
  const k = Math.min(sw, sh) / 1080;
  const W = Math.round(sw / k), H = Math.round(sh / k);
  const portrait = W < H * 0.9;
  const square = !portrait && W < H * 1.2;
  const el = h('div', `srb srb-${kind} sr-theme-${theme}${portrait ? ' srb-portrait' : ' srb-landscape'}`);
  el.style.cssText = `width:${W}px;height:${H}px;transform:scale(${k});transform-origin:0 0;` + accentVars(p && p.accent);
  const bg = h('div', 'srb-bg');
  const cam = h('div', 'srb-cam');
  const ov = h('div', 'srb-ov');
  el.append(bg, cam, ov);
  ctx.root.appendChild(el);
  // Safe area in reference px: render-tech C2 (16:9) and the 9:16 centre band (Shorts/TikTok UI).
  const safe = portrait ? { l: 120, r: 120, t: 220, b: 420 } : { l: 120, r: 120, t: 90, b: 120 };
  const fs = ctx.film && ctx.film.safe;
  if (fs && typeof fs === 'object') {
    for (const side of ['l', 'r', 't', 'b']) if (Number.isFinite(Number(fs[side]))) safe[side] = Math.max(safe[side], Math.round(Number(fs[side]) / k));
  }
  const caps = !!(p && p._captions);
  return { el, bg, cam, ov, W, H, k, portrait, square, safe, theme, caps };
}

/**
 * Inline custom properties for a per-project accent (#RGB/#RRGGBB): --sr-accent plus derived ink (text on
 * the accent), highlighter tint and glow. Empty string when the value is not a hex colour.
 */
export function accentVars(hex) {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(hex || '').trim());
  if (!m) return '';
  let s = m[1];
  if (s.length === 3) s = s.split('').map((c) => c + c).join('');
  const r = parseInt(s.slice(0, 2), 16), g = parseInt(s.slice(2, 4), 16), b = parseInt(s.slice(4, 6), 16);
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const mix = (c, w) => Math.round(c + (255 - c) * w);
  const ink = L > 0.36 ? '#11130F' : '#FFFFFF';
  return `--sr-accent:#${s};--sr-accent-ink:${ink};--sr-accent-hl:rgb(${mix(r, 0.62)},${mix(g, 0.62)},${mix(b, 0.62)});` +
    `--sr-accent-glow:rgba(${r},${g},${b},.34);`;
}

/** Split text into masked word spans: returns [{outer, inner, word, i}] (inner gets the motion). */
export function words(parent, str, { emphasis = -1, emClass = 'srb-em' } = {}) {
  const out = [];
  const parts = String(str).split(/(\s+)/);
  let i = 0;
  for (const part of parts) {
    if (!part) continue;
    if (/^\s+$/.test(part)) { parent.appendChild(document_ref().createTextNode(' ')); continue; }
    const outer = h('span', 'srb-mask');
    const inner = h('span', 'srb-wi' + (i === emphasis ? ' ' + emClass : ''), { text: part });
    outer.appendChild(inner);
    parent.appendChild(outer);
    out.push({ outer, inner, word: part, i });
    i++;
  }
  return out;
}

/** Index of the word to emphasise: the last word of >= 4 letters (punctuation ignored), else last. */
export function pickEmphasis(str) {
  const ws = String(str).trim().split(/\s+/).filter(Boolean);
  for (let i = ws.length - 1; i >= 0; i--) if (ws[i].replace(/[^\p{L}\p{N}]/gu, '').length >= 4) return i;
  return ws.length - 1;
}

/** Fit a font size so `str` (rough char-width model) fits `lines` lines of `width` px. */
export function fitSize(str, width, lines, max, min, charW = 0.52) {
  const n = Math.max(1, String(str).length);
  for (let s = max; s >= min; s -= 2) {
    const perLine = Math.floor(width / (s * charW));
    if (Math.ceil(n / Math.max(1, perLine)) <= lines) return s;
  }
  return min;
}

export const ICONS = {
  file: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 2.5h6.5L16 7v10.5H5z"/><path d="M11.5 2.5V7H16"/></svg>',
  term: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M6 8l2.5 2L6 12M10.5 12.5H14"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  cross: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>',
  lock: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="4.5" y="9" width="11" height="8" rx="2"/><path d="M7 9V6.8a3 3 0 0 1 6 0V9"/></svg>',
  search: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="8.5" cy="8.5" r="5"/><path d="M12.5 12.5L17 17"/></svg>',
  globe: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="10" cy="10" r="7.5"/><path d="M2.5 10h15M10 2.5c2.2 2.3 2.2 12.7 0 15M10 2.5c-2.2 2.3-2.2 12.7 0 15"/></svg>',
  pen: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M13.5 3.5l3 3L7 16H4v-3z"/></svg>',
  diff: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 4v6M3 7h6M11 15h6"/></svg>',
  read: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M2.5 10s3-5.5 7.5-5.5S17.5 10 17.5 10s-3 5.5-7.5 5.5S2.5 10 2.5 10z"/><circle cx="10" cy="10" r="2.3"/></svg>',
  camera: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 6.5h3l1.5-2h5l1.5 2h3v9H3z"/><circle cx="10" cy="10.8" r="2.8"/></svg>',
  list: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M7.5 5.5h9M7.5 10h9M7.5 14.5h9"/><path d="M3.5 5.5l.8.8 1.4-1.6M3.5 10l.8.8 1.4-1.6M3.5 14.5h2"/></svg>',
  fork: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="5" cy="4.5" r="1.8"/><circle cx="15" cy="4.5" r="1.8"/><circle cx="10" cy="15.5" r="1.8"/><path d="M5 6.3c0 4 5 3.5 5 7.4M15 6.3c0 4-5 3.5-5 7.4"/></svg>',
  spark: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M10 2.5l1.8 5.7 5.7 1.8-5.7 1.8L10 17.5l-1.8-5.7L2.5 10l5.7-1.8z"/></svg>',
  chat: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 4.5h14v9H8l-4 3v-3H3z"/></svg>',
  cursor: '<svg viewBox="0 0 28 34" width="28" height="34"><path d="M3 2.5v24.2l6.4-6 4.3 10.2 4.3-1.9-4.3-10h8.9z" fill="#fff" stroke="#111" stroke-width="2" stroke-linejoin="round"/></svg>',
};

/** Icon for an event kind (MONTAGE cards). */
export function kindIcon(kind) {
  return ({
    terminal: ICONS.term, file_write: ICONS.pen, file_patch: ICONS.diff, file_read: ICONS.read,
    web_search: ICONS.search, web_extract: ICONS.globe, browser_nav: ICONS.globe, screenshot: ICONS.camera,
    product_capture: ICONS.camera, image_generated: ICONS.spark, todo: ICONS.list, delegate: ICONS.fork,
    user_prompt: ICONS.chat, assistant_note: ICONS.chat, final_answer: ICONS.chat, artifact: ICONS.file,
  })[kind] || ICONS.spark;
}

/** "m:ss" session clock. */
export function clock(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return hh ? `${hh}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : `${mm}:${String(ss).padStart(2, '0')}`;
}
