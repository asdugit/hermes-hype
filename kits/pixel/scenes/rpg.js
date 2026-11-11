// rpg.js — story scenes: kit:pixel/title-screen, kit:pixel/item-get, kit:pixel/quest-log, kit:pixel/score-tally,
// kit:pixel/shop. All palette-locked 480x270 / 270x480 art with safe-area-aware text.
import { screenOf, withDefaults, isVertical, say, present, assetOf } from './base.js';
import { Sprite } from './../core/gfx.js';
import { REMAP, IDX } from './../core/palette.js';
import { drawText, measure, wrap, fit } from './../core/text.js';
import { step, seg, ease, hop, blink, rand, shakeAt } from './../core/motion.js';
import { WORLDS } from './../bg/worlds.js';
import { heroFrames, idleCel, HERO_ANCHOR } from './../art/heroes.js';
import { item, CHEST } from './../art/items.js';
import { sparkle, burst, fade, flash } from './../art/fx.js';
import { productSprite } from './../art/product.js';
import { win, dialog, menu, ribbon, title as bigTitle, COIN, cursorBob } from './../ui/ui.js';
import { questLog, tally, pressStart } from './../ui/panels.js';
import { cue } from './../cues.js';

/** Safe insets in game px (>= 4). */
export function insets(ctx) {
  const s = ctx.safe || {};
  return { L: Math.max(4, Math.round(s.l || 0)), T: Math.max(4, Math.round(s.t || 0)), R: ctx.w - Math.max(4, Math.round(s.r || 0)), B: ctx.h - Math.max(4, Math.round(s.b || 0)) };
}
const sayer = (ctx, S) => (str, x, y, o) => say(ctx, S, str, x, y, o);
const world = (S, name, t, camX = 0) => (WORLDS[name] || WORLDS.overworld)(S, t, { camX });

/** Product (or fallback item icon) as a sprite that fits w x h; cutout preferred. */
function productArt(ctx, P, w, h, t) {
  const a = assetOf(ctx, P.media);
  if (!a) return null;
  // a phone-shaped capture in a wide box shows the whole screen ('cover' cut a 390x844 capture down to a slice of
  // its timer ring in a real 9:16 E2E film)
  const tall = a.h > a.w * 1.15 && w > h;
  return a.cutout ? productSprite(ctx, a.cutout, { w, h, t, fit: 'contain', outline: 'ink', dither: P.dither ?? 24 })
    : productSprite(ctx, a, { w, h, t, fit: tall ? 'contain' : 'cover', dither: P.dither ?? 24 });
}

/** Largest caps scale (4..1) at which every word-wrapped line of `text` fits maxW, max `lines` lines. */
function logoFit(text, maxW, lines = 2) {
  for (const sc of [4, 3, 2, 1]) { const ls = wrap(text, maxW, 'caps', sc); if (ls.length <= lines && ls.every(l => measure(l, 'caps', sc) <= maxW)) return { scale: sc, lines: ls }; }
  return { scale: 1, lines: wrap(text, maxW, 'caps', 1).slice(0, lines) };
}
/** White diagonal shine sweeping across the gold logo pixels (remaps only gold-band colours). */
function shine(S, box, u) {
  if (u <= 0 || u >= 1) return;
  const x0 = box.x - 20 + (box.w + 40) * u;
  for (let y = box.y; y < box.y + box.h; y++) for (let x = Math.round(x0 - (y - box.y) * 0.5); x < x0 - (y - box.y) * 0.5 + 6; x++) {
    const c = S.get(x, y); if (c === IDX.cream || c === IDX.gold || c === IDX.amber) S.px(x, y, 'white');
  }
}

/** Stepped stone podium with a gold trim; top surface at y = top, centred on cx. */
export function podium(S, cx, top, w) {
  const x = Math.round(cx - w / 2);
  S.rect(x, top, w, 4, 'silver'); S.rect(x, top, w, 1, 'white'); S.rect(x, top + 4, w, 1, 'gold'); S.rect(x, top + 5, w, 1, 'amber');
  S.rect(x + 6, top + 6, w - 12, 6, 'grey'); S.rect(x + 6, top + 6, w - 12, 1, 'silver'); S.rect(x + 6, top + 11, w - 12, 1, 'greydk');
  S.rect(x - 4, top + 12, w + 8, 4, 'grey'); S.rect(x - 4, top + 12, w + 8, 1, 'silver'); S.rect(x - 4, top + 15, w + 8, 1, 'ink');
  for (let k = x + 12; k < x + w - 12; k += 16) S.rect(k, top + 7, 1, 4, 'greydk');
}

// ---------------------------------------------------------------------------------------------- title-screen
const TITLE_P = {
  title: { type: 'string', default: '', doc: 'logo text (default: film title)' },
  tagline: { type: 'string', default: '', doc: 'one line under the logo' },
  press: { type: 'string', default: 'PRESS START', doc: 'blinking prompt ("" to hide)' },
  world: { type: 'string', default: 'overworld', doc: 'overworld | night | castle' },
  media: { type: 'asset', default: null, doc: 'product shown on a pedestal under the logo' },
  party: { type: 'list', default: ['knight', 'mage', 'rogue'], doc: 'heroes on the hill when there is no media' },
  footer: { type: 'string', default: '', doc: 'tiny line at the bottom, e.g. "(C) 2026 ACME"' },
};
function titleRender(ctx, t, p) {
  const P = withDefaults(TITLE_P, p), S = screenOf(ctx), V = isVertical(ctx), I = insets(ctx), tq = step(t, 30), sy = sayer(ctx, S);
  world(S, P.world, tq, Math.round(tq * 12));
  const text = String(P.title || ctx.film?.title || 'HYPE').toUpperCase();
  const lf = logoFit(text, I.R - I.L - 8, V ? 3 : 2), lh = 8 * lf.scale + 6;
  const ly = I.T + (V ? 30 : 18), drop = ease.outBounce(seg(step(tq, 15), 0.15, 0.85)), dy = Math.round((1 - drop) * -(ly + lh * lf.lines.length + 20));
  let box = null;
  lf.lines.forEach((ln, i) => {
    const b = bigTitle(S, ln, ctx.w / 2, ly + dy + i * lh, { scale: lf.scale });
    if (ctx.qaText) ctx.qaText({ x: b.x, y: b.y, w: b.w, h: 8 * lf.scale, text: ln, glyph_px: 8 * lf.scale, font: 'caps' });
    box = box ? { x: Math.min(box.x, b.x), y: box.y, w: Math.max(box.w, b.w), h: b.y + b.h - box.y } : b;
  });
  if (box) shine(S, box, seg(tq, 1.3, 1.9));
  let y = ly + lh * lf.lines.length + 6;
  if (P.tagline && tq > 0.9) {
    const lines = wrap(P.tagline, I.R - I.L - 8, 'mono');
    const n = Math.floor(seg(tq, 0.95, 0.95 + P.tagline.length / 40) * P.tagline.length); let left = n;
    lines.forEach((ln, i) => { const k = Math.max(0, Math.min(ln.length, left)); left -= ln.length + 1; if (k) sy(ln, ctx.w / 2, y + i * 14, { font: 'mono', color: 'white', outline: 'ink', diag: true, align: 'center', chars: k }); });
    y += lines.length * 14 + 4;
  }
  // captions own the bottom band (Quick `_captions`): the prompt blinks under the tagline instead of under the
  // podium, where it sat on the caption line (real 9:16 E2E film)
  const pressHigh = !!P._captions && !!P.press;
  if (pressHigh) { if (tq > 1.6) pressStart(S, ctx.w / 2, y + 2, tq - 1.6, { text: P.press, say: sy, period: 0.9 }); y += 16; }
  const groundY = V ? I.B - 70 : I.B - 46;
  // the product fits between the text block and the podium (it used to be pushed down over the podium)
  const art = productArt(ctx, P, V ? 236 : 240, Math.max(40, Math.min(V ? 132 : 100, groundY - y - 4)), tq);
  podium(S, ctx.w / 2, groundY, V ? 92 : 112);
  if (art) {
    const bb = art.bounds() || { x: 0, y: 0, w: art.w, h: art.h };
    const ax = Math.round(ctx.w / 2 - bb.x - bb.w / 2), ay = Math.round(groundY - bb.y - bb.h + 1 - Math.max(0, Math.round(Math.sin(tq * 3) * 1.5)));
    S.ellipse(ctx.w / 2, groundY, bb.w * 0.4, 3, 'ink', 0.7);
    S.blit(art, ax, Math.max(y + 2 - bb.y, ay));
    if (Math.floor(tq * 2) % 3 === 0) sparkle(S, ax + bb.x + bb.w * 0.8, ay + bb.y + 4, 1);
  } else {
    (P.party || []).slice(0, 3).forEach((id, i) => { const x = ctx.w / 2 + (i - 1) * 26; S.blit(idleCel(id, tq, i * 0.5), x - HERO_ANCHOR.x, groundY - HERO_ANCHOR.y); });
  }
  if (P.press && !pressHigh && tq > 1.6) pressStart(S, ctx.w / 2, groundY + (V ? 30 : 20), tq - 1.6, { text: P.press, say: sy, period: 0.9 });
  if (P.footer) sy(fit(P.footer, I.R - I.L, 'tiny'), ctx.w / 2, I.B - 11, { font: 'tiny', color: 'silver', align: 'center', shadow: [1, 1, 'ink'] });
  fade(S, 4 - Math.floor(seg(tq, 0, 0.4) * 4.999));
  present(ctx, S);
}
export const titleScreen = {
  id: 'kit:pixel/title-screen',
  def: { layer: '2d', describe: '16-bit title screen: parallax world, banded gold logo that drops in with a bounce and a shine sweep, tagline, product on a pedestal (or the party), blinking PRESS START.',
    params: TITLE_P, render: titleRender,
    cues: (ctx, p) => { const P = withDefaults(TITLE_P, p); const out = [cue(0.55, 'stamp'), cue(1.3, 'coin')]; if (P.press) out.push(cue(1.6, 'press_start', -6)); return out; } },
};

// ------------------------------------------------------------------------------------------------- item-get
const ITEM_P = {
  media: { type: 'asset', default: null, doc: 'product presented as the legendary item' },
  name: { type: 'string', default: 'LEGENDARY ITEM', doc: 'item name (<= 16 chars)' },
  desc: { type: 'string', default: '', doc: 'one-line description (typed in the dialog)' },
  rarity: { type: 'string', default: 'LEGENDARY', doc: 'rarity label above the name' },
  banner: { type: 'string', default: 'ITEM GET!', doc: 'ribbon text' },
  hero: { type: 'string', default: 'knight', doc: 'hero celebrating at the side ("" for none)' },
  icon: { type: 'string', default: 'star', doc: 'fallback item icon when there is no media' },
};
function itemRender(ctx, t, p) {
  const P = withDefaults(ITEM_P, p), S = screenOf(ctx), V = isVertical(ctx), I = insets(ctx), tq = step(t, 30), sy = sayer(ctx, S);
  const W = ctx.w, H = ctx.h, cx = Math.round(W / 2), floorY = V ? Math.round(H * 0.56) : Math.round(H * 0.66);
  S.vbands(0, 0, W, H, ['ink', 'night', 'plumdk', 'night'], 5);
  // turning stepped light rays behind (after the chest opens)
  const open = tq >= 1.0, rise = ease.outCubic(seg(step(tq, 15), 1.05, 1.9));
  if (open) {
    const rot = Math.floor(tq * 8) / 8 * 0.2, R = Math.max(W, H);
    for (let k = 0; k < 12; k += 2) { const a0 = rot + k * Math.PI / 6, a1 = a0 + Math.PI / 12; S.poly([[cx, floorY - 40], [cx + Math.cos(a0) * R, floorY - 40 + Math.sin(a0) * R], [cx + Math.cos(a1) * R, floorY - 40 + Math.sin(a1) * R]], 'plum'); }
    S.glow(cx, floorY - 40, 110, REMAP.gold, 1.1 * Math.min(1, rise * 2), 0.9);
  }
  // pedestal + chest
  S.rect(cx - 30, floorY, 60, 6, 'grey'); S.rect(cx - 30, floorY, 60, 1, 'silver'); S.rect(cx - 26, floorY + 6, 52, 10, 'greydk'); S.rect(cx - 30, floorY + 16, 60, 3, 'grey');
  const shakeX = tq > 0.5 && tq < 1.0 ? ((Math.floor(tq * 20) & 1) ? 1 : -1) : 0, chestHop = tq > 0.6 && tq < 1.0 ? Math.round(hop(seg(tq, 0.6, 0.8), 3) + hop(seg(tq, 0.8, 1.0), 2)) : 0;
  S.blit(open ? CHEST.open : CHEST.closed, cx - 12 + shakeX, floorY - 17 - chestHop);
  if (open) { // beam
    const bw = Math.round(8 + rise * 14);
    S.remap(REMAP.lighter, cx - bw, 0, bw * 2, floorY - 12, 0.5); S.remap(REMAP.gold, cx - bw / 2, 0, bw, floorY - 12, 0.6);
  }
  // the item rises out of the chest and hovers
  const art = productArt(ctx, P, V ? 180 : 150, V ? 100 : 84, tq) || item(P.icon).scaled(3);
  if (open) {
    const ty = (V ? floorY - 64 - art.h : floorY - 40 - art.h), y = Math.round(floorY - 14 - (floorY - 14 - ty) * rise + (rise >= 1 ? Math.sin(tq * 3) * 2 : 0));
    S.blit(art, cx - Math.round(art.w / 2), y, { alpha: Math.min(1, rise * 3) });
    for (let k = 0; k < 6; k++) { const a = tq * 1.3 + k * 1.047, rr = art.w * 0.55; if ((Math.floor(tq * 8) + k) % 3) sparkle(S, cx + Math.cos(a) * rr, y + art.h / 2 + Math.sin(a) * art.h * 0.6, (k + Math.floor(tq * 6)) % 2, 'white', 'gold'); }
  }
  // hero celebrating at the side
  if (P.hero && heroFrames(P.hero)) { const F = heroFrames(P.hero), hx = V ? cx - 70 : cx - 110; S.blit(tq > 1.9 ? ((Math.floor(tq * 4) & 1) ? F.win0 : F.win1) : idleCel(P.hero, tq), hx - HERO_ANCHOR.x, floorY + 14 - HERO_ANCHOR.y); }
  // ribbon + dialog
  if (tq > 1.7) ribbon(S, String(P.banner).toUpperCase(), I.T + 6, seg(tq, 1.7, 2.1), { scale: V ? 2 : 2 });
  if (tq > 2.2) {
    const w = I.R - I.L + 8, h = V ? 70 : 52, x = I.L - 4, y = I.B - h + 4;
    const lines = [[[String(P.rarity).toUpperCase() + ' ', 'gold'], [String(P.name).toUpperCase().slice(0, 18), 'white']]];
    if (P.desc) wrap(P.desc, w - 18, 'mono').slice(0, V ? 3 : 2).forEach(l => lines.push([[l, 'ice']]));
    dialog(S, x, y, w, h, lines, { t: tq, t0: 2.25, cps: 36, say: sy, open: seg(tq, 2.2, 2.35) });
  }
  if (tq >= 1.0 && tq < 1.08) flash(S, 'white', 0.6);
  fade(S, 4 - Math.floor(seg(tq, 0, 0.3) * 4.999));
  present(ctx, S);
}
export const itemGet = {
  id: 'kit:pixel/item-get',
  def: { layer: '2d', describe: 'The product as a LEGENDARY ITEM: chest on a pedestal shakes, bursts open with a light beam, the product rises and hovers in sparkles; ITEM GET! ribbon + rarity/name/description dialog.',
    params: ITEM_P, render: itemRender,
    cues: () => [cue(0.62, 'tick'), cue(0.8, 'tick'), cue(1.0, 'power_up'), cue(1.4, 'item_get'), cue(1.75, 'whoosh'), cue(2.25, 'blip')] },
};

// ------------------------------------------------------------------------------------------------ quest-log
const QUEST_P = {
  title: { type: 'string', default: 'QUEST LOG', doc: 'window title' },
  items: { type: 'list', default: [{ text: 'Find the boss', status: 'done' }, { text: 'Open the door', status: 'done' }, { text: 'Get the product', status: 'active' }], doc: '[{text, status: done|active|todo}] (PLAN data shape)' },
  world: { type: 'string', default: 'night', doc: 'backdrop: overworld | night | castle' },
};
function questRender(ctx, t, p) {
  const P = withDefaults(QUEST_P, p), S = screenOf(ctx), I = insets(ctx), tq = step(t, 30), V = isVertical(ctx);
  world(S, P.world, tq, Math.round(tq * 6));
  const items = (P.items || []).slice(0, V ? 12 : 9), w = Math.min(I.R - I.L + 8, V ? 260 : 340), h = 26 + items.length * 16;
  questLog(S, Math.round(ctx.w / 2 - w / 2), Math.max(I.T - 4, Math.round(ctx.h / 2 - h / 2)), w, items, tq, { title: String(P.title).toUpperCase(), open: seg(tq, 0.1, 0.35), t0: 0.7, say: sayer(ctx, S) });
  fade(S, 4 - Math.floor(seg(tq, 0, 0.3) * 4.999));
  present(ctx, S);
}
export const questLogScene = {
  id: 'kit:pixel/quest-log',
  def: { layer: '2d', describe: 'QUEST LOG window over a parallax world: items with boxes; done items get checks stamped in one by one (coin cue each), the active one pulses gold.',
    params: QUEST_P, render: questRender,
    cues: (ctx, p) => { const P = withDefaults(QUEST_P, p); const out = [cue(0.1, 'menu_open')]; let k = 0; (P.items || []).forEach(it => { if (it.status === 'done') out.push(cue(0.7 + (k++) * 0.35, 'coin', -3)); }); return out; } },
};

// ---------------------------------------------------------------------------------------------- score-tally
const TALLY_P = {
  title: { type: 'string', default: 'RESULTS', doc: 'window title' },
  rows: { type: 'list', default: [{ label: 'Monsters', value: 12 }, { label: 'Treasure', value: 3400 }, { label: 'Score', value: 99999 }], doc: '[{label, value, display?}] (STATS data shape: label/value/display)' },
  world: { type: 'string', default: 'castle', doc: 'backdrop' },
  stars: { type: 'number', default: 3, doc: 'stars awarded at the end (0-3)' },
};
function tallyRender(ctx, t, p) {
  const P = withDefaults(TALLY_P, p), S = screenOf(ctx), I = insets(ctx), tq = step(t, 30);
  world(S, P.world, tq, Math.round(tq * 6));
  const rows = (P.rows || []).slice(0, 6), w = Math.min(I.R - I.L + 8, 320), h = 30 + rows.length * 18;
  const x = Math.round(ctx.w / 2 - w / 2), y = Math.max(I.T - 4, Math.round(ctx.h / 2 - h / 2 - 10));
  tally(S, x, y, w, rows, tq, { title: String(P.title).toUpperCase(), open: seg(tq, 0.1, 0.3), t0: 0.45, gap: 0.6, say: sayer(ctx, S) });
  const tEnd = 0.45 + rows.length * 0.6 + 0.2;
  for (let k = 0; k < Math.min(3, P.stars | 0); k++) {
    const tk = tEnd + k * 0.2; if (tq < tk) continue;
    const s = item('star').scaled(2), u = seg(tq, tk, tk + 0.25);
    S.blit(s, Math.round(ctx.w / 2 + (k - 1) * 26 - s.w / 2), Math.round(y + h + 6 - hop(u, 8)));
  }
  fade(S, 4 - Math.floor(seg(tq, 0, 0.3) * 4.999));
  present(ctx, S);
}
export const scoreTally = {
  id: 'kit:pixel/score-tally',
  def: { layer: '2d', describe: 'Score tally screen: rows with dotted leaders whose numbers roll up in steps (tick cues), last row flashes gold, stars hop in.',
    params: TALLY_P, render: tallyRender,
    cues: (ctx, p) => { const P = withDefaults(TALLY_P, p), n = Math.min(6, (P.rows || []).length), out = []; for (let i = 0; i < n; i++) for (let k = 0; k < 4; k++) out.push(cue(0.45 + i * 0.6 + k * 0.12, 'tick')); const e = 0.45 + n * 0.6 + 0.2; for (let k = 0; k < Math.min(3, P.stars | 0); k++) out.push(cue(e + k * 0.2, 'coin')); return out; } },
};

// ------------------------------------------------------------------------------------------------------- shop
const MERCHANT = Sprite.rows([
  '.....kkkkkk.....',
  '....kVVVVVVk....',
  '...kVvvvvvvVk...',
  '..kVvvvvvvvvVk..',
  '..kkkkkkkkkkkk..',
  '..kssssssssssk..',
  '.ksswwsssswwssk.',
  '.kswkkwsswkkwsk.',
  '.ksswwsssswwssk.',
  '..ksssskkssssk..',
  '..kkhhhhhhhhkk..',
  '.khhhkhhhhkhhhk.',
  'kTTTTkhhhhkTTTTk',
  'kTyTTTkkkkTTTyTk',
  'kTTTTTTTTTTTTTTk',
  'kTTTTTTyyTTTTTTk',
], { k: 'ink', V: 'plum', v: 'violet', s: 'peach', w: 'white', h: 'silver', T: 'teal', y: 'gold' });
const SHOP_P = {
  media: { type: 'asset', default: null, doc: 'product on the counter' },
  name: { type: 'string', default: 'ITEM', doc: 'product name' },
  price: { type: 'string', default: '999 G', doc: 'price tag text (verbatim, e.g. "$29")' },
  line: { type: 'string', default: '{name}! Finest in the land. {price}.', doc: 'shopkeeper line ({name}, {price})' },
  menu: { type: 'list', default: ['BUY', 'SELL', 'EXIT'], doc: 'menu items' },
  pick: { type: 'string', default: 'BUY', doc: 'item the cursor clicks' },
  thanks: { type: 'string', default: 'Thank you! Come again!', doc: 'line after the purchase' },
};
function shopSchedule(dur) { const click = Math.max(2.5, dur - 1.1); return { line: 0.4, menu: Math.max(1.6, click - 1.3), click }; }
function shopRender(ctx, t, p) {
  const P = withDefaults(SHOP_P, p), S = screenOf(ctx), V = isVertical(ctx), I = insets(ctx), tq = step(t, 30), sy = sayer(ctx, S), B = shopSchedule(ctx.dur);
  const W = ctx.w, H = ctx.h, counterY = V ? Math.round(H * 0.52) : Math.round(H * 0.6);
  // back wall: wooden planks + shelves with item icons, warm lamp light
  S.fill('browndk');
  for (let x = 0; x < W; x += 12) { S.rect(x, 0, 1, counterY, 'ink'); S.rect(x + 1, 0, 1, counterY, 'brown'); }
  const icons = ['potion', 'ether', 'scroll', 'gem', 'shield', 'key', 'bomb', 'ring', 'sword', 'crown'];
  for (const sy0 of [I.T + 34, I.T + 70]) {
    S.rect(0, sy0, W, 4, 'tan'); S.rect(0, sy0, W, 1, 'peach'); S.rect(0, sy0 + 4, W, 1, 'ink');
    for (let k = 0; k * 34 + 10 < W; k++) { const ic = item(icons[(k * 3 + sy0) % icons.length]); S.blit(ic, k * 34 + 10, sy0 - ic.h); }
  }
  S.light([{ x: W / 2, y: I.T + 10, r: W * 0.6, sy: 0.8 }], [REMAP.fade[2], REMAP.fade[1], null, REMAP.warm2], 0, 0, W, H);
  // merchant behind the counter (bobs)
  S.blit(MERCHANT, Math.round(W / 2 + (V ? 40 : 70)), counterY - MERCHANT.h + ((Math.floor(tq * 2) & 1) ? 1 : 0));
  // counter
  S.rect(0, counterY, W, H - counterY, 'brown'); S.rect(0, counterY, W, 3, 'tan'); S.rect(0, counterY, W, 1, 'peach'); S.rect(0, counterY + 3, W, 1, 'ink');
  for (let x = 6; x < W; x += 40) S.rect(x, counterY + 8, 1, H - counterY - 8, 'browndk');
  // product on a velvet cushion with a price tag
  const art = productArt(ctx, P, V ? 150 : 120, V ? 84 : 66, tq);
  const px = Math.round(W / 2 - (V ? 30 : 40)), cy = counterY + 2;
  S.ellipse(px, cy, 46, 6, 'maroon'); S.ellipse(px, cy - 1, 42, 4, 'red');
  if (art) S.blit(art, px - Math.round(art.w / 2), cy - art.h - 2 + Math.round(Math.sin(tq * 2.5)));
  const tag = String(P.price), tw = measure(tag, 'caps') + 10, tx = px + 30, ty = cy - 18;
  S.line(tx - 6, ty + 2, tx, ty + 6, 'cream'); S.rect(tx, ty, tw, 13, 'cream'); S.frame(tx, ty, tw, 13, 'ink'); S.px(tx + 3, ty + 6, 'ink');
  sy(tag, tx + 7, ty + 3, { font: 'caps', color: 'maroon' });
  // dialog / menu
  const clicked = tq >= B.click, w = I.R - I.L + 8, dh = 40, dx = I.L - 4, dy = I.B - dh + 4;
  const fmtLine = (s) => String(s).replace(/\{name\}/g, String(P.name).toUpperCase()).replace(/\{price\}/g, String(P.price));
  dialog(S, dx, dy, w, dh, clicked && tq > B.click + 0.35 ? fmtLine(P.thanks) : fmtLine(P.line), { t: tq, t0: clicked && tq > B.click + 0.35 ? B.click + 0.35 : B.line, cps: 34, say: sy });
  if (tq >= B.menu) {
    const items = (P.menu || []).map(s => String(s).toUpperCase()), pk = Math.max(0, items.indexOf(String(P.pick).toUpperCase()));
    const mw = 80, mh = items.length * 13 + 12, mx = I.R - mw + 4, my = dy - mh - 2;
    const pos = menu(S, mx, my, mw, items, pk, { lh: 13, open: seg(tq, B.menu, B.menu + 0.2), pressed: clicked && tq < B.click + 0.3, flashOn: Math.floor(tq * 15) & 1, chosen: clicked ? pk : -1, bob: clicked ? 0 : cursorBob(tq), say: sy });
    if (clicked && pos[pk]) for (let k = 0; k < 8; k++) {
      const dt = tq - B.click - k * 0.05; if (dt < 0 || dt > 0.7) continue;
      const sx0 = pos[pk].x, sy0 = pos[pk].y, ex = px, ey = cy - 20, u = ease.inOutQuad(seg(dt, 0, 0.6));
      S.blit(COIN[Math.floor(dt * 16 + k) & 3], Math.round(sx0 + (ex - sx0) * u) - 3, Math.round(sy0 + (ey - sy0) * u - hop(u, 30)) - 3);
    }
  }
  if (clicked && tq < B.click + 0.6) for (let k = 0; k < 5; k++) sparkle(S, px + Math.cos(k * 1.26 + tq * 5) * 40, cy - 30 + Math.sin(k * 1.26 + tq * 5) * 20, k % 2, 'white', 'gold');
  fade(S, 4 - Math.floor(seg(tq, 0, 0.3) * 4.999));
  present(ctx, S);
}
export const shop = {
  id: 'kit:pixel/shop',
  def: { layer: '2d', describe: 'Item shop: the product on a velvet cushion on the counter with a price tag, a merchant, shelves of goods; shopkeeper line, BUY/SELL/EXIT menu, cursor clicks BUY, coins fly to the counter, "Thank you!".',
    params: SHOP_P, render: shopRender,
    cues: (ctx) => { const B = shopSchedule(ctx.dur); return [cue(B.line, 'blip'), cue(B.menu, 'menu_open'), cue(B.click, 'menu_select'), cue(B.click + 0.12, 'buy'), cue(B.click + 0.5, 'coin')]; } },
};
