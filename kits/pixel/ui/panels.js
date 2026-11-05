// panels.js — composite RPG panels: quest log, score tally, PRESS START, code/terminal windows, picture window.
import { win, bar, CHECK, BOX } from './ui.js';
import { Sprite } from './../core/gfx.js';

/** continuation-row marker (soft-wrapped code) */
const CONT = Sprite.rows(['g....', 'g....', 'g..g.', 'ggggg', '...g.'], { g: 'grey' });
import { drawText, measure, fit, wrap } from './../core/text.js';
import { seg, step, blink, hop, ease } from './../core/motion.js';

/**
 * Quest log: items [{text, status: 'done'|'active'|'todo'}]. Done items stamp their check in one at a time from
 * t0 (every `gap` s); the active one pulses gold. Returns check stamp times (for coin cues).
 */
export function questLog(S, x, y, w, items, t, o = {}) {
  const lh = 16, h = 26 + items.length * lh, draw = o.say || ((s, xx, yy, oo) => drawText(S, s, xx, yy, oo));
  const inner = win(S, x, y, w, h, { open: o.open ?? 1 });
  const stamps = [];
  let k = 0;
  items.forEach((it, i) => { if (it.status === 'done') stamps[i] = (o.t0 ?? 0.5) + (k++) * (o.gap ?? 0.35); });
  if (!inner) return stamps;
  draw(o.title || 'QUEST LOG', inner.x, inner.y - 1, { font: 'caps', color: 'gold', shadow: [1, 1, 'ink'] });
  items.forEach((it, i) => {
    const yy = inner.y + 14 + i * lh, appear = (o.t0 ?? 0.5) - 0.4 + i * 0.08;
    if (t < appear) return;
    S.blit(BOX, inner.x, yy + 1);
    const st = stamps[i], done = it.status === 'done' && t >= st;
    if (done) { const u = seg(t, st, st + 0.12); S.blit(CHECK, inner.x - 1, yy + 1 - Math.round(hop(u, 3))); }
    const active = it.status === 'active', col = done ? 'silver' : active ? ((Math.floor(t * 3) & 1) ? 'gold' : 'cream') : it.status === 'todo' ? 'grey' : 'white';
    draw(fit(it.text, inner.w - 14, 'mono'), inner.x + 12, yy - 1, { font: 'mono', color: col, shadow: [1, 1, 'ink'] });
    if (done) S.rect(inner.x + 12, yy + 5, Math.min(inner.w - 14, measure(fit(it.text, inner.w - 14, 'mono'), 'mono')), 1, 'grey');
  });
  return stamps;
}

/** Score tally rows [{label, value (number), display?}]: digits roll up in steps; last row flashes gold. */
export function tally(S, x, y, w, rows, t, o = {}) {
  const lh = 18, h = 30 + rows.length * lh, draw = o.say || ((s, xx, yy, oo) => drawText(S, s, xx, yy, oo));
  const inner = win(S, x, y, w, h, { open: o.open ?? 1 });
  const done = [];
  if (!inner) return done;
  draw(o.title || 'SCORE', inner.x + inner.w / 2, inner.y - 1, { font: 'caps', color: 'gold', shadow: [1, 1, 'ink'], align: 'center' });
  rows.forEach((r, i) => {
    const t0 = (o.t0 ?? 0.4) + i * (o.gap ?? 0.6), u = ease.outCubic(seg(step(t, 15), t0, t0 + 0.5)), yy = inner.y + 16 + i * lh;
    if (t < t0 - 0.2) return;
    done.push(t0 + 0.5);
    const v = Number(r.value) || 0, shown = u >= 1 ? (r.display ?? fmtNum(v)) : fmtNum(Math.round(v * u));
    const last = i === rows.length - 1, flashOn = last && u >= 1 && (Math.floor(t * 6) & 1);
    const label = fit(String(r.label).toUpperCase(), inner.w - measure(shown, 'caps') - 24, 'caps');
    draw(label, inner.x, yy, { font: 'caps', color: 'white', shadow: [1, 1, 'ink'] });
    const lx = inner.x + measure(label, 'caps') + 4, rx = inner.x + inner.w - measure(shown, 'caps') - 4;
    for (let dx = lx; dx < rx; dx += 4) S.px(dx, yy + 6, 'grey');                       // dotted leader
    draw(shown, inner.x + inner.w, yy, { font: 'caps', color: flashOn ? 'white' : last ? 'gold' : 'cream', shadow: [1, 1, 'ink'], align: 'right' });
  });
  return done;
}
export const fmtNum = (v) => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

/** Blinking PRESS START with a hand cursor. */
export function pressStart(S, cx, y, t, o = {}) {
  if (!blink(t, o.period || 1, 0.62)) return null;
  const draw = o.say || ((s, xx, yy, oo) => drawText(S, s, xx, yy, oo));
  return draw(o.text || 'PRESS START', cx, y, { font: 'caps', color: o.color || 'white', outline: 'ink', diag: true, align: 'center' });
}

/**
 * Soft-wrap code lines to maxW px: breaks after a space/comma/operator (never mid-token unless unavoidable);
 * continuation rows carry `cont: true` (drawn with a ↪ in the gutter) and keep colour/bg. Keeps source indices in `src`.
 */
export function wrapCode(lines, maxW) {
  const out = [], cols = Math.max(8, Math.floor(maxW / 7));
  lines.forEach((L, i) => {
    let rest = String(L.text ?? ''), first = true;
    while (rest.length > cols) {
      let cut = -1;
      for (let k = cols; k > cols * 0.4; k--) if (/[\s,;(){}=+\-*/]/.test(rest[k - 1])) { cut = k; break; }
      if (cut < 0) cut = cols;
      out.push({ ...L, text: rest.slice(0, cut), cont: !first, src: i }); rest = '  ' + rest.slice(cut).trimStart(); first = false;
    }
    out.push({ ...L, text: rest, cont: !first, src: i });
  });
  return out;
}

/**
 * Code / terminal window: lines [{text, color?, bg?}] in mono 11 px with optional line numbers and a focus band.
 * o: {title, numbers: startLine|null, focus: [a, b] (indices), reveal (lines visible), cursor (bool), say}
 */
export function codeWindow(S, x, y, w, h, lines, t, o = {}) {
  const lh = 14, draw = o.say || ((s, xx, yy, oo) => drawText(S, s, xx, yy, oo));
  const inner = win(S, x, y, w, h, { theme: o.theme || 'night' });
  if (!inner) return;
  let top = inner.y;
  if (o.title) { draw(fit(o.title, inner.w, 'caps'), inner.x, top - 1, { font: 'caps', color: 'gold', shadow: [1, 1, 'ink'] }); top += 13; }
  const gutter = o.numbers != null ? 7 * String(o.numbers + lines.length).length + 6 : 0, rows = Math.floor((inner.y + inner.h - top) / lh);
  const reveal = o.reveal ?? lines.length;
  const vis = o.wrap ? wrapCode(lines.slice(0, reveal), inner.w - gutter) : lines.slice(0, reveal).map((L, i) => ({ ...L, src: i }));
  // keep the focus range on screen: scroll so the first focus row sits near the top third
  let first = 0;
  if (o.focus && vis.length > rows) { const fi = vis.findIndex(L => L.src >= o.focus[0]); first = Math.max(0, Math.min(vis.length - rows, fi - Math.floor(rows / 3))); }
  if (!o.focus && vis.length > rows) first = vis.length - rows;   // terminals: newest lines stay visible
  lines = vis.slice(first, first + rows);
  const n = lines.length;
  for (let i = 0; i < n; i++) {
    const L = lines[i], yy = top + i * lh;
    if (o.focus && L.src >= o.focus[0] && L.src <= o.focus[1]) S.rect(inner.x - 4, yy - 1, inner.w + 8, lh, 'navy');
    if (L.bg) S.rect(inner.x - 4, yy - 1, inner.w + 8, lh, L.bg);
    if (L.cont) S.blit(CONT, inner.x + (gutter ? gutter - 11 : -1), yy + 3);
    else if (gutter) draw(String(o.numbers + L.src), inner.x + gutter - 6, yy, { font: 'mono', color: 'grey', align: 'right' });
    draw(fit(L.text, inner.w - gutter, 'mono'), inner.x + gutter, yy, { font: 'mono', color: L.color || 'ice', shadow: [1, 1, 'ink'] });
  }
  if (o.cursor && blink(t, 0.5)) { const yy = top + Math.max(0, n - 1) * lh, cx = inner.x + gutter + measure(fit(lines[Math.max(0, n - 1)]?.text || '', inner.w - gutter, 'mono'), 'mono') + 1; S.rect(cx, yy, 6, 11, 'lime'); }
}

/** Picture window: a Sprite (e.g. productSprite of a screenshot) in a window with an optional caption bar. */
export function pictureWindow(S, x, y, w, h, sprite, o = {}) {
  const inner = win(S, x, y, w, h, { theme: o.theme || 'blue' });
  if (!inner) return null;
  const px = x + 6, py = y + 6, pw = w - 12, ph = h - 12 - (o.caption ? 16 : 0);
  S.rect(px - 1, py - 1, pw + 2, ph + 2, 'ink');
  if (sprite) S.blit(sprite, px + Math.round((pw - sprite.w) / 2), py + Math.round((ph - sprite.h) / 2));
  if (o.caption) (o.say || ((s, xx, yy, oo) => drawText(S, s, xx, yy, oo)))(fit(o.caption, pw, 'mono'), px + 2, py + ph + 3, { font: 'mono', color: 'white', shadow: [1, 1, 'ink'] });
  return { x: px, y: py, w: pw, h: ph };
}

export { bar, wrap };
