// quick.js — Quick-mode scene types for the pixel style: kit:pixel/<TYPE> for HOOK, TITLE, PROBLEM, PLAN, CODE, DIFF,
// TERMINAL, MONTAGE, SCREEN, STATS, BEFORE_AFTER, CALLOUT, END, FEATURE, SCROLL.
// Params: {data: TimelineScene.data (verbatim, research/wp-e-story.md §2), image: asset name for image types
// (or data.image.asset / data.hero.asset), media: product asset (optional), world: backdrop}.
import { screenOf, withDefaults, isVertical, say, present, assetOf } from './base.js';
import { REMAP } from './../core/palette.js';
import { wrap, fit } from './../core/text.js';
import { step, seg, ease, hop } from './../core/motion.js';
import { WORLDS } from './../bg/worlds.js';
import { heroFrames, idleCel, HERO_ANCHOR } from './../art/heroes.js';
import { monster } from './../art/monsters.js';
import { item } from './../art/items.js';
import { sparkle, burst, fade } from './../art/fx.js';
import { productSprite } from './../art/product.js';
import { win, dialog, ribbon, title as bigTitle, CURSOR, CURSOR_PRESS } from './../ui/ui.js';
import { questLog, tally, codeWindow, pictureWindow } from './../ui/panels.js';
import { titleScreen, insets } from './rpg.js';
import { cue } from './../cues.js';

const BASE_P = {
  data: { type: 'object', default: {}, doc: 'TimelineScene.data for this type (verbatim)' },
  image: { type: 'asset', default: null, doc: 'image asset for HOOK/FEATURE/SCREEN/SCROLL/BEFORE_AFTER(before) ' },
  image2: { type: 'asset', default: null, doc: 'second image (BEFORE_AFTER after)' },
  media: { type: 'asset', default: null, doc: 'product media (optional, used by HOOK/TITLE/END)' },
  world: { type: 'string', default: 'night', doc: 'backdrop: overworld | night | castle' },
};
const sayer = (ctx, S) => (str, x, y, o) => say(ctx, S, str, x, y, o);
const bg = (S, P, t) => (WORLDS[P.world] || WORLDS.night)(S, t, { camX: Math.round(t * 8) });
const imgAsset = (ctx, P, key = 'image') => assetOf(ctx, P[key] || P.data?.[key]?.asset || P.data?.hero?.asset || null);
const fadeIn = (S, t) => fade(S, 4 - Math.floor(seg(t, 0, 0.3) * 4.999));
/** Screenshot -> palette sprite fitting w x h (contain), stepped mosaic reveal when `mosaic` (1 = full res). */
function shot(ctx, a, w, h, t, mosaic = 1, crop = null) {
  if (!a) return null;
  if (mosaic <= 1) return productSprite(ctx, crop ? cropView(a, crop) : a, { w, h, t, fit: crop ? 'cover' : 'contain', dither: 16, pop: 0.25 });
  const k = Math.max(1, Math.round(mosaic)), small = productSprite(ctx, a, { w: Math.max(1, Math.round(w / k)), h: Math.max(1, Math.round(h / k)), t, fit: 'contain', dither: 0, pop: 0.25 });
  return small ? small.scaled(k) : null;
}
/** Asset view cropped to a normalised rect [x, y, w, h] (for scrolling tall captures). */
function cropView(a, [cx, cy, cw, ch]) {
  return { name: `${a.name || ''}#${cx.toFixed(3)},${cy.toFixed(3)},${cw.toFixed(3)},${ch.toFixed(3)}`, w: a.w * cw, h: a.h * ch, fps: a.fps,
    frame: (t, o) => { const f = a.frame ? a.frame(t, o) : a.image; return f ? { __crop: [cx, cy, cw, ch], src: f } : null; } };
}

const T = {};

// HOOK — power-on line, the product artifact appears on a pedestal with a sting
T.HOOK = (ctx, S, t, P, sy) => {
  const I = insets(ctx), V = isVertical(ctx), cx = ctx.w / 2;
  S.fill('ink');
  const on = seg(t, 0.05, 0.35);
  if (on < 1) { const w = Math.round(ctx.w * ease.outCubic(on)); S.rect(cx - w / 2, ctx.h / 2 - 1, w, 2, 'white'); return; }
  bg(S, P, t); S.remap(REMAP.fade[1]);
  const a = imgAsset(ctx, P) || assetOf(ctx, P.media);
  const pw = V ? 220 : 280, ph = V ? 140 : 150, sp = a ? (a.cutout ? productSprite(ctx, a.cutout, { w: pw, h: ph, t, fit: 'contain', outline: 'ink' }) : shot(ctx, a, pw, ph, t)) : item('star').scaled(4);
  const y = Math.round(ctx.h / 2 - sp.h / 2 - (V ? 20 : 8) + Math.sin(t * 3) * 1.5);
  S.glow(cx, y + sp.h / 2, Math.max(sp.w, sp.h) * 0.75, REMAP.lighter, 0.8);
  S.blit(sp, Math.round(cx - sp.w / 2), y);
  if ((Math.floor(t * 3) & 1)) sparkle(S, cx + sp.w * 0.45, y + 8, 1);
  const label = P.data?.label || P.data?.hero?.page_title || '';
  if (label && t > 0.7) sy(fit(String(label), I.R - I.L, 'caps'), cx, Math.min(I.B - 14, y + sp.h + 12), { font: 'caps', color: 'gold', outline: 'ink', diag: true, align: 'center' });
};
T.HOOK.cues = () => [cue(0.05, 'power_up'), cue(0.4, 'item_get')];

// TITLE — delegates to the title screen with the TITLE data
T.TITLE = null;

// PROBLEM — the user's ask in a dialog with a silhouette portrait
T.PROBLEM = (ctx, S, t, P, sy) => {
  const I = insets(ctx), V = isVertical(ctx); bg(S, P, t);
  const w = I.R - I.L + 8, h = V ? 150 : 96, x = I.L - 4, y = V ? Math.round(ctx.h / 2 - h / 2) : I.B - h + 4;
  const open = seg(t, 0.1, 0.35);
  win(S, x, y, w, h, { open });
  if (open < 1) return;
  const px = x + 10, py = y + 10;
  S.rect(px, py, 32, 32, 'navy'); S.frame(px - 1, py - 1, 34, 34, 'ink');
  S.ellipse(px + 16, py + 12, 7, 8, 'greydk'); S.ellipse(px + 16, py + 32, 13, 10, 'greydk');           // silhouette bust
  sy('YOU', px + 16, py + 36, { font: 'caps', color: 'gold', align: 'center', shadow: [1, 1, 'ink'] });
  const tx = px + 42, lines = wrap(String(P.data?.text || ''), x + w - 10 - tx, 'mono').slice(0, V ? 9 : 5);
  const total = lines.reduce((a, l) => a + l.length, 0), n = Math.floor(seg(t, 0.45, 0.45 + total / 36) * total); let left = n;
  lines.forEach((l, i) => { const k = Math.max(0, Math.min(l.length, left)); left -= l.length; if (k) sy(l, tx, py + i * 14, { font: 'mono', color: 'white', shadow: [1, 1, 'ink'], chars: k }); });
};
T.PROBLEM.cues = (ctx, P) => { const n = String(P.data?.text || '').length, out = [cue(0.1, 'menu_open')]; for (let i = 2; i < Math.min(n, 200); i += 6) out.push(cue(0.45 + i / 36, 'blip')); return out; };

// PLAN — quest log
T.PLAN = (ctx, S, t, P, sy) => {
  const I = insets(ctx), V = isVertical(ctx); bg(S, P, t);
  const items = (P.data?.items || []).slice(0, V ? 12 : 9).map(it => ({ text: it.text, status: it.status === 'completed' ? 'done' : it.status === 'in_progress' ? 'active' : (it.status || 'todo') }));
  const w = Math.min(I.R - I.L + 8, 360), h = 26 + items.length * 16;
  questLog(S, Math.round(ctx.w / 2 - w / 2), Math.max(I.T - 4, Math.round(ctx.h / 2 - h / 2)), w, items, t, { open: seg(t, 0.1, 0.35), t0: 0.7, say: sy });
};
T.PLAN.cues = (ctx, P) => { let k = 0; const out = [cue(0.1, 'menu_open')]; (P.data?.items || []).forEach(it => { if (it.status === 'done' || it.status === 'completed') out.push(cue(0.7 + (k++) * 0.35, 'coin', -3)); }); return out; };

// CODE — the SPELLBOOK: lines stream in one per tick, focus band
T.CODE = (ctx, S, t, P, sy) => {
  const I = insets(ctx), d = P.data || {}; bg(S, P, t); S.remap(REMAP.fade[1]);
  const lines = (d.lines || []).map(l => ({ text: typeof l === 'string' ? l : String(l.text ?? l) }));
  const focus = d.focus ? [d.focus[0] - (d.start || 1), d.focus[1] - (d.start || 1)] : null;
  codeWindow(S, I.L - 4, I.T - 4, I.R - I.L + 8, I.B - I.T + 8, lines, t, { wrap: true, title: `SPELLBOOK  ${fit(String(d.path || ''), 200, 'caps')}`, numbers: d.start || 1, focus, reveal: Math.floor(seg(t, 0.2, 0.2 + lines.length / 15) * lines.length + 0.999), say: sy });
};
// DIFF — + rows as green blocks, - rows as maroon bricks, counters
T.DIFF = (ctx, S, t, P, sy) => {
  const I = insets(ctx), d = P.data || {}; bg(S, P, t); S.remap(REMAP.fade[1]);
  const rows = [];
  for (const h of d.hunks || []) { if (h.header) rows.push({ text: h.header, color: 'lilac' }); for (const [op, tx] of h.lines || []) rows.push({ text: `${op === '+' ? '+' : op === '-' ? '-' : ' '} ${tx}`, color: op === '+' ? 'lime' : op === '-' ? 'coral' : 'ice', bg: op === '+' ? 'forestdk' : op === '-' ? 'maroon' : null }); }
  codeWindow(S, I.L - 4, I.T - 4, I.R - I.L + 8, I.B - I.T + 8, rows, t, { wrap: true, title: fit(String(d.path || 'DIFF'), I.R - I.L - 90, 'caps'), reveal: Math.floor(seg(t, 0.2, 0.2 + rows.length / 15) * rows.length + 0.999), say: sy });
  const u = seg(t, 0.4, 1.2), a = Math.round((d.adds || 0) * u), r = Math.round((d.dels || 0) * u);
  sy(`+${a}`, I.R - 60, I.T, { font: 'caps', color: 'lime', shadow: [1, 1, 'ink'], align: 'right' }); sy(`-${r}`, I.R - 4, I.T, { font: 'caps', color: 'coral', shadow: [1, 1, 'ink'], align: 'right' });
};
// TERMINAL — command types, output streams, PASS!/FAIL banner; hero vs. a bug monster
T.TERMINAL = (ctx, S, t, P, sy) => {
  const I = insets(ctx), V = isVertical(ctx), d = P.data || {}; bg(S, P, t); S.remap(REMAP.fade[1]);
  const cmd = String(d.cmd || ''), out = (d.output || []).map(String), tc = 0.2 + cmd.length / 30;
  const lines = [{ text: `$ ${cmd.slice(0, Math.floor(seg(t, 0.2, tc) * cmd.length))}`, color: 'lime' }, ...out.slice(0, Math.floor(seg(t, tc + 0.1, tc + 0.1 + out.length / 12) * out.length)).map(s => ({ text: s, color: 'ice' }))];
  const h = V ? Math.round((I.B - I.T) * 0.62) : I.B - I.T - 20;
  codeWindow(S, I.L - 4, I.T - 4, V ? I.R - I.L + 8 : Math.round((I.R - I.L) * 0.68), h, lines, t, { wrap: true, title: 'TERMINAL', cursor: true, say: sy });
  const done = tc + 0.2 + out.length / 12, ok = d.ok !== false && (d.exit_code ?? 0) === 0;
  const hx = V ? ctx.w / 2 - 40 : I.R - 40, hy = V ? I.B - 30 : I.B - 40;
  S.blit(monster(ok ? 'bones' : 'golem', Math.floor(t * 2)), hx + (V ? 50 : -10), hy - 20, { alpha: ok && t > done + 0.3 ? Math.max(0, 1 - (t - done - 0.3) * 3) : 1 });
  const F = heroFrames('knight'); S.blit(t > done ? (ok ? F.win0 : F.hurt) : F.ready, hx - 30 - HERO_ANCHOR.x, hy - HERO_ANCHOR.y);
  if (t > done) bigTitle(S, ok ? 'PASS!' : 'FAIL', V ? ctx.w / 2 : I.R - 60, (V ? I.T + h + 4 : I.T + 30) - Math.round(hop(seg(t, done, done + 0.3), 6)), { scale: 2, bands: ok ? ['white', 'lime', 'lime', 'green'] : ['white', 'coral', 'red', 'maroon'] });
};
T.TERMINAL.cues = (ctx, P) => { const d = P.data || {}, cmd = String(d.cmd || ''), tc = 0.2 + cmd.length / 30, done = tc + 0.2 + (d.output || []).length / 12, out = []; for (let i = 2; i < cmd.length; i += 4) out.push(cue(0.2 + i / 30, 'blip')); out.push(cue(done, (d.ok !== false && (d.exit_code ?? 0) === 0) ? 'level_up' : 'error')); return out; };

// MONTAGE — INVENTORY grid of tool calls with a COMBO counter
const KIND_ICON = { edit: 'scroll', write: 'scroll', read: 'key', terminal: 'bomb', shell: 'bomb', search: 'gem', web: 'ring', browser: 'ring', test: 'shield', default: 'potion' };
T.MONTAGE = (ctx, S, t, P, sy) => {
  const I = insets(ctx), V = isVertical(ctx), items = (P.data?.items || []).slice(0, V ? 12 : 12); bg(S, P, t);
  const cols = V ? 2 : 3, cw = Math.floor((I.R - I.L) / cols), ch = 26, w = I.R - I.L + 8, h = 30 + Math.ceil(items.length / cols) * ch;
  const x0 = I.L - 4, y0 = Math.max(I.T - 4, Math.round(ctx.h / 2 - h / 2)), inner = win(S, x0, y0, w, h, { open: seg(t, 0.05, 0.25) });
  if (!inner) return;
  sy('INVENTORY', inner.x, inner.y - 1, { font: 'caps', color: 'gold', shadow: [1, 1, 'ink'] });
  const gap = Math.min(0.35, (ctx.dur - 1.2) / Math.max(1, items.length));
  let n = 0;
  items.forEach((it, i) => {
    const ti = 0.4 + i * gap; if (t < ti) return; n++;
    const x = inner.x + (i % cols) * cw, y = inner.y + 14 + Math.floor(i / cols) * ch, pop = Math.round(hop(seg(t, ti, ti + 0.15), 2));
    S.rect(x, y, 20, 20, 'night'); S.frame(x, y, 20, 20, 'royal');
    const ic = item(KIND_ICON[String(it.kind || it.tool || '').toLowerCase()] || KIND_ICON.default); S.blit(ic, x + 10 - Math.round(ic.w / 2), y + 10 - Math.round(ic.h / 2) - pop);
    sy(fit(String(it.tool || it.kind || ''), cw - 28, 'tiny'), x + 24, y + 1, { font: 'tiny', color: 'gold' });
    sy(fit(String(it.arg || ''), cw - 28, 'tiny'), x + 24, y + 11, { font: 'tiny', color: 'ice' });
  });
  if (n > 1) sy(`COMBO x${n}`, inner.x + inner.w, inner.y - 1 - (Math.floor(t * 6) & 1), { font: 'caps', color: 'coral', shadow: [1, 1, 'ink'], align: 'right' });
};
T.MONTAGE.cues = (ctx, P) => { const items = (P.data?.items || []).slice(0, 12), gap = Math.min(0.35, (ctx.dur - 1.2) / Math.max(1, items.length)); return items.map((_, i) => cue(0.4 + i * gap, 'coin', -6)); };

// SCREEN — mosaic reveal of a capture, focus brackets walk to the bbox
function brackets(S, x, y, w, h, c = 'gold') { const k = 8; for (const [bx, by, sx, sy2] of [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]]) { S.rect(sx > 0 ? bx : bx - k, by - (sy2 > 0 ? 0 : 1), k, 2, c); S.rect(bx - (sx > 0 ? 0 : 1), sy2 > 0 ? by : by - k, 2, k, c); } }
T.SCREEN = (ctx, S, t, P, sy) => {
  const I = insets(ctx), d = P.data || {}; bg(S, P, t); S.remap(REMAP.fade[2]);
  const w = I.R - I.L + 8, h = I.B - I.T + 8, steps = [16, 8, 4, 2, 1], k = steps[Math.min(4, Math.floor(seg(t, 0.15, 0.75) * 5))];
  const pic = pictureWindow(S, I.L - 4, I.T - 4, w, h, shot(ctx, imgAsset(ctx, P), w - 12, h - 12, t, k));
  const bb = d.bbox || [0.1, 0.1, 0.8, 0.8];
  if (pic && t > 0.8) { const u = ease.outCubic(seg(step(t, 15), 0.8, 1.4)); const bx = pic.x + pic.w * bb[0] * u, by = pic.y + pic.h * bb[1] * u, bw = pic.w * (1 - u + bb[2] * u), bh = pic.h * (1 - u + bb[3] * u); brackets(S, Math.round(bx), Math.round(by), Math.round(bw), Math.round(bh)); }
};
T.SCREEN.cues = () => [cue(0.15, 'whoosh'), cue(0.8, 'blip')];
// FEATURE — capture + brackets + cursor click + the feature line
T.FEATURE = (ctx, S, t, P, sy) => {
  T.SCREEN(ctx, S, t, P, sy);
  const I = insets(ctx), d = P.data || {}, w = I.R - I.L + 8, h = I.B - I.T + 8, px = I.L + 2, py = I.T + 2, pw = w - 12, ph = h - 12;
  const c = d.click || (d.bbox ? [d.bbox[0] + d.bbox[2] / 2, d.bbox[1] + d.bbox[3] / 2] : null);
  if (c && t > 1.2) { const u = ease.inOutQuad(seg(t, 1.2, 1.7)), x = Math.round(px + pw * (0.9 - (0.9 - c[0]) * u)), y = Math.round(py + ph * (0.95 - (0.95 - c[1]) * u)), pressed = t > 1.75 && t < 1.95;
    S.blit(pressed ? CURSOR_PRESS : CURSOR, x, y); if (pressed) burst(S, x, y, 8, Math.floor((t - 1.75) * 16)); }
  const feat = String(d.feature || '');
  // captions up (Quick mode `_captions`): lift the feature line clear of the caption band
  const yb = P._captions ? Math.min(I.B, Math.round(ctx.h * (isVertical(ctx) ? 0.68 : 0.76))) : I.B;
  if (feat && t > 0.6) dialog(S, I.L - 4, yb - 32, I.R - I.L + 8, 36, fit(feat, I.R - I.L - 10, 'mono'), { t, t0: 0.65, cps: 34, say: sy });
};
T.FEATURE.cues = () => [cue(0.15, 'whoosh'), cue(0.65, 'blip'), cue(1.75, 'menu_select')];
// SCROLL — the capture pans down a tall page in steps
T.SCROLL = (ctx, S, t, P, sy) => {
  const I = insets(ctx), d = P.data || {}, a = imgAsset(ctx, P); bg(S, P, t); S.remap(REMAP.fade[2]);
  const w = I.R - I.L + 8, h = I.B - I.T + 8, [f0, f1] = d.scroll || [0, 1];
  if (!a) { pictureWindow(S, I.L - 4, I.T - 4, w, h, null); return; }
  const viewH = Math.min(1, (a.w / a.h) * ((h - 12) / (w - 12))), u = ease.inOutQuad(seg(step(t, 15), 0.3, ctx.dur - 0.4)), top = (f0 + (f1 - f0) * u) * (1 - viewH);
  pictureWindow(S, I.L - 4, I.T - 4, w, h, shot(ctx, a, w - 12, h - 12, t, 1, [0, Math.round(top * 200) / 200, 1, viewH]));
};
// STATS — score tally
T.STATS = (ctx, S, t, P, sy) => {
  const I = insets(ctx); bg(S, P, t);
  const rows = (P.data?.stats || []).slice(0, 6).map(s => ({ label: s.label || s.key, value: Number(String(s.value).replace(/[^0-9.]/g, '')) || 0, display: s.display ?? String(s.value) }));
  const w = Math.min(I.R - I.L + 8, 340), h = 30 + rows.length * 18;
  tally(S, Math.round(ctx.w / 2 - w / 2), Math.max(I.T - 4, Math.round(ctx.h / 2 - h / 2)), w, rows, t, { title: 'SCORE', open: seg(t, 0.1, 0.3), t0: 0.45, gap: 0.6, say: sy });
};
T.STATS.cues = (ctx, P) => { const n = Math.min(6, (P.data?.stats || []).length), out = []; for (let i = 0; i < n; i++) out.push(cue(0.45 + i * 0.6, 'tick'), cue(0.45 + i * 0.6 + 0.5, 'coin', -4)); return out; };
// BEFORE_AFTER — LEVEL 1 (grey) -> LEVEL 2 (full palette) with a LEVEL UP! ribbon
T.BEFORE_AFTER = (ctx, S, t, P, sy) => {
  const I = insets(ctx), V = isVertical(ctx), d = P.data || {}; bg(S, P, t);
  const gap = 8, w = V ? I.R - I.L + 8 : Math.floor((I.R - I.L - gap) / 2) + 4, h = V ? Math.floor((I.B - I.T - gap - 30) / 2) : I.B - I.T - 30;
  const draw = (which, x, y, label, key) => {
    const a = imgAsset(ctx, P, key), side = d[which] || {};
    const pic = pictureWindow(S, x, y, w, h, a ? shot(ctx, a, w - 12, h - 12 - 16, t) : null, { caption: label, say: sy });
    if (!a && pic) { const ls = [side.cmd ? `$ ${side.cmd}` : '', ...(side.output || side.lines || []).map(String)].filter(Boolean).slice(0, Math.floor(pic.h / 14)); ls.forEach((l, i) => sy(fit(l, pic.w - 4, 'mono'), pic.x + 2, pic.y + 2 + i * 14, { font: 'mono', color: which === 'before' ? 'coral' : 'lime' })); }
    return pic;
  };
  const b = draw('before', I.L - 4, I.T + 26, 'LEVEL 1', 'image');
  if (b) S.remap(REMAP.grey, b.x, b.y, b.w, b.h);
  if (t > 0.9) draw('after', V ? I.L - 4 : I.L - 4 + w + gap, V ? I.T + 26 + h + gap : I.T + 26, 'LEVEL 2', 'image2');
  if (t > 1.3) ribbon(S, 'LEVEL UP!', I.T - 4, seg(t, 1.3, 1.6), { scale: 2, bands: ['white', 'lime', 'lime', 'green'], dark: 'forestdk', light: 'green' });
};
T.BEFORE_AFTER.cues = () => [cue(0.9, 'whoosh'), cue(1.3, 'level_up')];
// CALLOUT — a hero's speech box, the quote streams word by word
T.CALLOUT = (ctx, S, t, P, sy) => {
  const I = insets(ctx), V = isVertical(ctx), d = P.data || {}; bg(S, P, t);
  const hx = I.L + 24, hy = V ? Math.round(ctx.h * 0.62) : I.B - 10;
  S.blit(idleCel('mage', t), hx - HERO_ANCHOR.x, hy - HERO_ANCHOR.y);
  const words = String(d.text || '').split(/\s+/), n = Math.floor(seg(t, 0.4, 0.4 + words.length / 4) * words.length + 0.999);
  const w = I.R - I.L - 30, lines = wrap(words.slice(0, Math.max(1, n)).join(' '), w - 18, 'mono'), full = wrap(String(d.text || ''), w - 18, 'mono').slice(0, V ? 10 : 6);
  const bh = full.length * 14 + 26, bx = I.L + 30, by = Math.max(I.T - 4, hy - 30 - bh);
  const inner = win(S, bx, by, w, bh, { open: seg(t, 0.1, 0.3) });
  if (!inner) return;
  S.poly([[bx + 10, by + bh - 2], [hx + 4, hy - 26], [bx + 24, by + bh - 2]], 'navy');
  lines.slice(0, full.length).forEach((l, i) => sy(l, inner.x, inner.y + i * 14, { font: 'mono', color: 'white', shadow: [1, 1, 'ink'] }));
  if (d.who) sy(`- ${fit(String(d.who), w - 30, 'caps')}`, inner.x + inner.w, inner.y + full.length * 14 + 1, { font: 'caps', color: 'gold', shadow: [1, 1, 'ink'], align: 'right' });
};
T.CALLOUT.cues = (ctx, P) => { const words = String(P.data?.text || '').split(/\s+/).length, out = [cue(0.1, 'menu_open')]; for (let i = 0; i < words; i += 2) out.push(cue(0.4 + i / 4, 'blip')); return out; };
// END — THANKS FOR PLAYING, the CTA in a command window, URL, credit; the party waves
T.END = (ctx, S, t, P, sy) => {
  const I = insets(ctx), V = isVertical(ctx), d = P.data || {}; (WORLDS.castle)(S, t, { camX: Math.round(t * 6) });
  bigTitle(S, V ? 'THANKS' : 'THANKS FOR PLAYING', ctx.w / 2, I.T + 6, { scale: 2 });
  if (V) bigTitle(S, 'FOR PLAYING', ctx.w / 2, I.T + 30, { scale: 2 });
  if (ctx.qaText) ctx.qaText({ x: I.L, y: I.T + 6, w: I.R - I.L, h: 16, text: 'THANKS FOR PLAYING', glyph_px: 16, font: 'caps' });
  let y = I.T + (V ? 64 : 40);
  if (d.title) { sy(fit(String(d.title).toUpperCase(), I.R - I.L, 'caps'), ctx.w / 2, y, { font: 'caps', color: 'white', outline: 'ink', diag: true, align: 'center' }); y += 18; }
  if (d.pb_display) { sy(`PB ${d.pb_display}`, ctx.w / 2, y, { font: 'caps', color: 'lime', outline: 'ink', diag: true, align: 'center' }); y += 18; }
  if (d.cta) { const lines = wrap(String(d.cta), I.R - I.L - 18, 'mono').slice(0, 3); codeWindow(S, I.L - 4, y, I.R - I.L + 8, 30 + lines.length * 14 - 14, lines.map((l, i) => ({ text: i ? l : `> ${l}`, color: 'lime' })), t, { cursor: true, say: sy }); y += 30 + lines.length * 14; }
  if (d.url) { sy(fit(String(d.url), I.R - I.L, 'mono'), ctx.w / 2, y, { font: 'mono', color: 'sky', outline: 'ink', diag: true, align: 'center' }); y += 16; }
  // the credit sits in the bottom band, or right under the stack when captions own the bottom band
  if (d.credit) sy(fit(String(d.credit), I.R - I.L, 'tiny'), ctx.w / 2, P._captions ? y + 2 : I.B - 10, { font: 'tiny', color: 'silver', align: 'center', shadow: [1, 1, 'ink'] });
  ['knight', 'mage', 'rogue'].forEach((id, i) => { const F = heroFrames(id); S.blit((Math.floor(t * 3 + i) & 1) ? F.win0 : F.win1, ctx.w / 2 + (i - 1) * 26 - HERO_ANCHOR.x, I.B - 16 - HERO_ANCHOR.y); });
};
T.END.cues = () => [cue(0.2, 'level_up')];

function makeQuick(type) {
  if (type === 'TITLE') {
    return { id: 'kit:pixel/TITLE', def: { ...titleScreen.def, describe: 'Quick TITLE: title screen fed by TimelineScene.data {title, tagline, product, one_liner}.', params: { ...BASE_P },
      render: (ctx, t, p) => { const d = (p && p.data) || {}; titleScreen.def.render(ctx, t, { title: d.title || d.product, tagline: d.tagline || d.one_liner, media: p?.media || null, world: p?.world || 'overworld' }); },
      cues: (ctx, p) => titleScreen.def.cues(ctx, {}) } };
  }
  const fn = T[type];
  return { id: `kit:pixel/${type}`, def: {
    layer: '2d', describe: `Quick ${type} in the pixel style (TimelineScene.data shape from wp-e-story §2).`, params: BASE_P,
    render(ctx, t, p) { const P = withDefaults(BASE_P, p), S = screenOf(ctx), tq = step(t, 30); S.fill('ink'); fn(ctx, S, tq, P, sayer(ctx, S)); fadeIn(S, tq); present(ctx, S); },
    cues: fn.cues ? (ctx, p) => fn.cues(ctx, withDefaults(BASE_P, p)) : undefined,
  } };
}
export const QUICK_TYPES = ['HOOK', 'TITLE', 'PROBLEM', 'PLAN', 'CODE', 'DIFF', 'TERMINAL', 'MONTAGE', 'SCREEN', 'STATS', 'BEFORE_AFTER', 'CALLOUT', 'END', 'FEATURE', 'SCROLL'];
export const QUICK = QUICK_TYPES.map(makeQuick);
