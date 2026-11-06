// ui.js — 16-bit RPG interface blocks drawn at the 1-px grid: windows (9-slice in code), dialog box with
// typewriter, HP/MP bars with lag chunk, battle/command menu with hand cursor, damage numbers, banners.
import { Sprite } from './../core/gfx.js';
import { drawText, measure, wrap, typed, fontInfo } from './../core/text.js';
import { seg, step, hop, ease, blink } from './../core/motion.js';

const U = { k: 'ink', w: 'white', s: 'silver', i: 'ice', g: 'gold', a: 'amber', c: 'cream', r: 'red', l: 'lime', G: 'green', b: 'brown' };
export const CURSOR = Sprite.rows(['kkk......', 'kwwkkk...', 'kwiwwwkk.', 'kwiiiiwwk', 'kwiiiwkk.', 'kwwkkk...', 'kkk......'], U);
export const CURSOR_PRESS = Sprite.rows(['.........', 'kkkkkk...', 'kwiwwwkk.', 'kwiiiiwwk', 'kwwwwwkk.', 'kkkkkk...', '.........'], U);
export const COIN = [
  ['.kkkk.', 'kcggak', 'kcgcak', 'kcgcak', 'kcggak', '.kkkk.'],
  ['..kk..', '.kcgk.', '.kcak.', '.kcak.', '.kcgk.', '..kk..'],
  ['..kk..', '..kk..', '..kk..', '..kk..', '..kk..', '..kk..'],
  ['..kk..', '.kgak.', '.kgak.', '.kgak.', '.kgak.', '..kk..'],
].map(r => Sprite.rows(r, U));
export const HEART = { full: Sprite.rows(['.kk.kk.', 'kwrkrrk', 'krrrrrk', 'krrrrrk', '.krrrk.', '..krk..', '...k...'], U),
  empty: Sprite.rows(['.kk.kk.', 'k..k..k', 'k.....k', 'k.....k', '.k...k.', '..k.k..', '...k...'], U) };
export const CHECK = Sprite.rows(['......kk', '.....klk', 'kk..klk.', 'klkklk..', '.kllk...', '..kk....'], { ...U, l: 'lime' });
export const BOX = Sprite.rows(['kkkkkkk', 'k.....k', 'k.....k', 'k.....k', 'k.....k', 'k.....k', 'kkkkkkk'], { k: 'grey' });
export const ARROW_DOWN = Sprite.rows(['wwwww', '.www.', '..w..'], U);

const THEMES = {
  blue: { body: ['royal', 'navy', 'night'], rim: 'white', rim2: 'silver' },
  night: { body: ['navy', 'night', 'night'], rim: 'silver', rim2: 'grey' },
  red: { body: ['maroon', 'plumdk', 'ink'], rim: 'coral', rim2: 'red' },
  gold: { body: ['amber', 'brown', 'browndk'], rim: 'cream', rim2: 'gold' },
};

/** RPG window: ink outer line, bevel ring, ink hairline, banded body. `open` 0..1 grows it vertically in 4 steps. */
export function win(S, x, y, w, h, o = {}) {
  const th = THEMES[o.theme || 'blue'], open = o.open ?? 1;
  if (open <= 0) return null;
  if (open < 1) { const k = Math.max(1, Math.ceil(open * 4)) / 4, hh = Math.max(6, Math.round(h * k)); y = y + Math.round((h - hh) / 2); h = hh; }
  S.vbands(x + 2, y + 2, w - 4, h - 4, th.body, 3);
  S.rect(x + 1, y, w - 2, 1, 'ink'); S.rect(x + 1, y + h - 1, w - 2, 1, 'ink'); S.rect(x, y + 1, 1, h - 2, 'ink'); S.rect(x + w - 1, y + 1, 1, h - 2, 'ink');
  S.rect(x + 2, y + 1, w - 4, 1, th.rim); S.rect(x + 1, y + 2, 1, h - 4, th.rim);
  S.rect(x + 2, y + h - 2, w - 4, 1, th.rim2); S.rect(x + w - 2, y + 2, 1, h - 4, th.rim2);
  S.px(x + 1, y + 1, th.rim); S.px(x + w - 2, y + h - 2, th.rim2);
  S.rect(x + 2, y + 2, w - 4, 1, 'ink'); S.rect(x + 2, y + 2, 1, h - 4, 'ink'); S.rect(x + 2, y + h - 3, w - 4, 1, 'ink'); S.rect(x + w - 3, y + 2, 1, h - 4, 'ink');
  return open >= 1 ? { x: x + 8, y: y + 6, w: w - 16, h: h - 12 } : null;
}

/**
 * HP/MP bar with a lag chunk: `frac` is the current value, `lag` (>= frac) the value shown as a pale chunk that
 * drains after a hit. Colours switch to danger below 35 %.
 */
export function bar(S, x, y, w, frac, o = {}) {
  const h = o.h || 5, lag = Math.max(frac, o.lag ?? frac), danger = frac < 0.35;
  const fill = o.fill || (danger ? ['coral', 'red'] : ['lime', 'green']);
  S.rect(x, y, w, h, 'ink'); S.rect(x + 1, y + 1, w - 2, h - 2, o.empty || 'greydk');
  const n = Math.round((w - 2) * Math.max(0, Math.min(1, frac))), nl = Math.round((w - 2) * Math.min(1, lag));
  if (nl > n) S.rect(x + 1 + n, y + 1, nl - n, h - 2, o.lagColor || 'cream');
  if (n > 0) { S.rect(x + 1, y + 1, n, h - 2, fill[1]); S.rect(x + 1, y + 1, n, 1, fill[0]); }
  if (o.tick !== 0) for (let i = x + 1 + (o.tick || 8); i < x + w - 1; i += (o.tick || 8)) S.px(i, y + h - 2, 'ink');
}

/**
 * Message/dialog window with typewriter text. lines: string or [string|[[text, colour], ...]].
 * o: {t, t0 (typing start), cps, font, theme, more (show bobbing ▼ when done), open, say (QA text fn)}
 * Returns the time typing finishes.
 */
export function dialog(S, x, y, w, h, lines, o = {}) {
  const font = o.font || 'mono', lh = fontInfo(font).lh, inner = win(S, x, y, w, h, { theme: o.theme, open: o.open ?? 1 });
  const flat = (typeof lines === 'string' ? wrap(lines, w - 18, font) : lines).map(l => (typeof l === 'string' ? [[l, 'white']] : l));
  const total = flat.reduce((a, l) => a + l.reduce((b, [s]) => b + [...s].length, 0), 0);
  const t = o.t ?? 1e9, n = o.t0 === undefined ? total : typed(t, o.t0, total, o.cps || 30);
  if (!inner) return (o.t0 || 0) + total / (o.cps || 30);
  let left = n;
  const draw = o.say || ((str, xx, yy, oo) => drawText(S, str, xx, yy, oo));
  flat.forEach((segs, i) => {
    let cx = inner.x + 1;
    for (const [str, col] of segs) {
      const k = Math.max(0, Math.min([...str].length, left)); left -= k;
      if (k > 0) draw(str, cx, inner.y + i * lh, { font, color: col || 'white', shadow: [1, 1, 'ink'], chars: k });
      cx += measure(str, font);
    }
  });
  if (o.more && n >= total && blink(t, 0.5)) S.blit(ARROW_DOWN, x + w - 14, y + h - 9 + (Math.floor(t * 4) & 1));
  return (o.t0 || 0) + total / (o.cps || 30);
}

/**
 * Command menu (vertical list or grid). items: string[]; sel: index of the hovered item (cursor), or -1.
 * o: {cols, open, pressed (bool: cursor squash + item flash), flashOn, colors: {i: token}, say}
 * Returns item positions [{x, y, w}] (screen coords of each label) for effects.
 */
export function menu(S, x, y, w, items, sel, o = {}) {
  const cols = o.cols || 1, rows = Math.ceil(items.length / cols), lh = o.lh || 14, h = rows * lh + 12;
  const inner = win(S, x, y, w, h, { open: o.open ?? 1, theme: o.theme });
  const pos = items.map((_, i) => ({ x: x + 20 + (i % cols) * Math.floor((w - 20) / cols), y: y + 8 + Math.floor(i / cols) * lh, w: measure(items[i], 'caps') }));
  if (!inner) return pos;
  const draw = o.say || ((str, xx, yy, oo) => drawText(S, str, xx, yy, oo));
  items.forEach((label, i) => {
    const on = i === sel, flashing = on && o.pressed && o.flashOn;
    if (o.chosen === i) { // selection bar behind the chosen item (inverted label)
      const bw = pos[i].w + 6, flick = o.pressed && o.flashOn;
      S.rect(pos[i].x - 3, pos[i].y - 2, bw, 12, flick ? 'white' : 'gold'); S.rect(pos[i].x - 3, pos[i].y - 2, bw, 1, flick ? 'white' : 'cream');
      S.rect(pos[i].x - 3, pos[i].y + 9, bw, 1, 'amber'); S.frame(pos[i].x - 4, pos[i].y - 3, bw + 2, 14, 'ink');
      draw(label, pos[i].x, pos[i].y, { font: 'caps', color: 'ink' });
      return;
    }
    const col = flashing ? 'white' : on ? 'gold' : (o.colors?.[i] || 'white');
    draw(label, pos[i].x, pos[i].y, { font: 'caps', color: col, shadow: [1, 1, 'ink'] });
  });
  if (sel >= 0 && sel < items.length) {
    const cx = pos[sel].x - 12 + (o.pressed ? 2 : 0) + (o.bob || 0);
    S.blit(o.pressed ? CURSOR_PRESS : CURSOR, cx, pos[sel].y);
  }
  return pos;
}

/** Cursor x-offset bob while hovering (1 px, on twos). */
export const cursorBob = (t) => (Math.floor(t * 4) & 1 ? -1 : 0);

/** Damage/heal number that hops up and settles, then blinks out. Returns false when finished. */
export function damageNumber(S, x, y, value, dt, o = {}) {
  if (dt < 0 || dt > (o.life || 1.3)) return false;
  const u = seg(dt, 0, 0.32), u2 = seg(dt, 0.32, 0.48);
  const yy = Math.round(y - hop(u, o.height || 10) - hop(u2, 3));
  if (dt > (o.life || 1.3) - 0.3 && !blink(dt, 0.1)) return true;
  const str = String(value);
  drawText(S, str, x, yy - ((o.scale || 1) - 1) * 8, { font: 'caps', scale: o.scale || 1, color: o.color || 'white', outline: 'ink', diag: true, align: 'center' });
  return true;
}

/** Big drawn title (caps x scale) with banded fill, 1-px outline, highlight and drop shadow. */
export function title(S, str, x, y, o = {}) {
  const scale = o.scale || 2;
  return drawText(S, str, x, y, { font: 'caps', scale, bands: o.bands || ['cream', 'gold', 'gold', 'amber'], outline: o.outline || 'browndk', outline2: o.outline2 || 'ink',
    highlight: o.highlight === undefined ? 'white' : o.highlight, shadow: o.shadow || [0, scale + 1, 'ink'], align: o.align || 'center' });
}

/** Banner ribbon (e.g. ITEM GET / LEVEL UP) sliding in from the left in steps; returns its rect. */
export function ribbon(S, text, cy, u, o = {}) {
  const tw = measure(text, 'caps', o.scale || 2), w = tw + 40, x = Math.round((S.w - w) / 2 - (1 - ease.outCubic(step(u, 15))) * (S.w));
  S.rect(x - 6, cy - 4, w + 12, 26 + (o.scale || 2) * 2, o.dark || 'maroon');
  S.rect(x - 6, cy - 4, w + 12, 1, o.light || 'red'); S.rect(x - 6, cy + 21 + (o.scale || 2) * 2, w + 12, 1, 'ink');
  for (const ex of [x - 6, x + w + 5]) for (let j = 0; j < 8; j++) { S.rect(ex - (ex < x ? j : -j), cy - 4 + j, 1, 26 + (o.scale || 2) * 2 - j * 2, o.dark || 'maroon'); }
  title(S, text, x + w / 2, cy + 2, { scale: o.scale || 2, bands: o.bands });
  return { x, y: cy - 4, w, h: 28 };
}
