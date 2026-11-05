// boss-battle.js — kit:pixel/boss-battle: the PRODUCT is the boss. A palette-quantised portrait of the product
// media (video plays inside a gold horned frame with name plate + HP bar) faces the party. The boss hurls a
// spinning blade that sweeps through the heroes (hit-stop, flashes, shake, damage numbers, HP drain), then the
// command menu opens and the cursor walks to the pick (BUY) and clicks it. Optional hero attacks first.
import { screenOf, withDefaults, isVertical, say, present, assetOf } from './base.js';
import { chamber } from './../bg/chamber.js';
import { heroFrames, idleCel, HERO_ANCHOR } from './../art/heroes.js';
import { blade, burst, slashArc, flash, sparkle, fade } from './../art/fx.js';
import { productSprite, bossFrame } from './../art/product.js';
import { win, bar, dialog, menu, damageNumber, cursorBob, COIN } from './../ui/ui.js';
import { drawText, measure, wrap } from './../core/text.js';
import { step, seg, ease, hop, clamp, lerp, shakeAt, hitstop, rand } from './../core/motion.js';
import { cue } from './../cues.js';

const PARAMS = {
  boss_media: { type: 'asset', default: null, doc: 'product media (image or video asset name) shown as the boss' },
  boss_name: { type: 'string', default: 'BOSS', doc: 'name plate text, <= 14 chars (e.g. "RED CAR")' },
  boss_level: { type: 'string', default: '99', doc: 'level shown after the name ("" to hide)' },
  party: { type: 'list', default: ['knight', 'mage', 'rogue'], doc: 'hero ids (front to back)' },
  party_hp: { type: 'list', default: [220, 140, 160], doc: 'max HP per hero' },
  attacks: { type: 'list', default: [{ by: 'boss', kind: 'blade', move: 'SPINNING BLADE', dmg: [48, 52, 61] }],
    doc: 'ordered beats. boss kinds: blade (dmg per hero). hero kinds: slash | spell (dmg: number or "MISS"); by = hero id' },
  menu: { type: 'list', default: ['FIGHT', 'ITEM', 'BUY', 'RUN'], doc: 'command menu items (<= 6 chars each)' },
  pick: { type: 'string', default: 'BUY', doc: 'menu item the cursor walks to and clicks' },
  pick_text: { type: 'string', default: 'Make it yours.', doc: 'help line shown while the cursor rests on the pick (sell line)' },
  cursor_path: { type: 'list', default: null, doc: 'menu items the cursor visits before the click (default: walk to the pick; overshoot + return when time allows)' },
  intro_text: { type: 'string', default: '{boss} blocks the way!', doc: 'first message ({boss} = boss_name)' },
  taunt: { type: 'string', default: 'Too powerful to beat...', doc: 'message after the boss attack' },
  prompt: { type: 'string', default: 'Command?', doc: 'message while the menu is open' },
  timings: { type: 'object', default: {}, doc: 'override beats in shot seconds: {drop, intro, menu, click}' },
  palette: { type: 'list', default: null, doc: 'sub-palette tokens for the product sprite (null = all 32 colours)' },
  dither: { type: 'number', default: 28, doc: 'ordered-dither strength for the product (0 = flat)' },
  fit: { type: 'string', default: 'cover', doc: 'product fit inside the portrait: cover | contain' },
  backdrop: { type: 'string', default: 'auto', doc: 'auto (lair backdrop behind the product cutout when the asset has one) | media (the media as filmed)' },
};

const LEN = { blade: 2.9, slash: 1.9, spell: 2.0 };

/** Beat schedule (shot seconds). Pure function of (dur, params). */
export function schedule(dur, P) {
  const T = P.timings || {};
  const click = T.click ?? Math.max(3.5, dur - 0.6);
  const menuDefault = Math.max(2.0, click - 2.4);
  const drop = T.drop ?? 0.1, land = drop + 0.42, intro = T.intro ?? land + 0.2;
  const atks = (P.attacks || []).filter(a => a && LEN[a.kind || (a.by === 'boss' ? 'blade' : 'slash')]);
  const a0 = intro + 1.4, a1 = (T.menu ?? menuDefault) - 0.3;
  const lens = atks.map(a => LEN[a.kind || (a.by === 'boss' ? 'blade' : 'slash')]);
  const total = lens.reduce((x, y) => x + y, 0) || 1, k = clamp((a1 - a0) / total, 0.55, 1.15);
  let at = a0;
  const attacks = atks.map((a, i) => { const len = lens[i] * k, o = { ...a, kind: a.kind || (a.by === 'boss' ? 'blade' : 'slash'), t0: at, len, k }; at += len; return o; });
  const menuT = T.menu ?? Math.min(menuDefault, at + 0.6);
  const items = P.menu || [], n = items.length, idxOf = (v) => (typeof v === 'number' ? v : items.findIndex(m => String(m).toUpperCase() === String(v).toUpperCase()));
  const pickIdx = Math.max(0, idxOf(P.pick));
  // cursor path: explicit, or FIGHT -> ... -> pick; with spare time it overshoots to the last item and comes back
  // (a beat of hesitation before the decisive pick)
  const span = click - 0.9 - (menuT + 0.6);
  let path = Array.isArray(P.cursor_path) && P.cursor_path.length ? P.cursor_path.map(idxOf).filter(i => i >= 0 && i < n) : null;
  if (!path) {
    path = []; for (let i = 1; i <= pickIdx; i++) path.push(i);
    if (pickIdx < n - 1 && span >= 0.62 * (n - 1 + 1)) { path = []; for (let i = 1; i < n; i++) path.push(i); path.push(pickIdx); }
  }
  const gap = Math.min(0.75, span / Math.max(1, path.length));
  const moves = path.map((idx, i) => ({ t: menuT + 0.6 + i * gap, idx }));
  // hits (for hit-stop, shake, damage)
  const hits = [];
  for (const a of attacks) {
    if (a.kind === 'blade') {
      const n = (P.party || []).length;
      for (let i = 0; i < n; i++) hits.push({ t: a.t0 + (1.55 + i * 0.12) * a.k, hero: i, dmg: (a.dmg || [])[i] ?? 40, a });
    } else hits.push({ t: a.t0 + 1.0 * a.k, boss: true, dmg: a.dmg ?? 'MISS', a });
  }
  return { dur, drop, land, intro, attacks, menuT, moves, click, pickIdx, hits };
}

/** Safe-area-aware layout (text stays inside ctx.safe; art may bleed to the edges). */
export function layout(ctx) {
  const sf = ctx.safe || {}, W = ctx.w, H = ctx.h;
  const L = Math.max(4, Math.round(sf.l || 0)), T = Math.max(4, Math.round(sf.t || 0));
  const R = W - Math.max(4, Math.round(sf.r || 0)), B = H - Math.max(4, Math.round(sf.b || 0));
  if (isVertical(ctx)) {
    const pw = Math.min(200, W - 24), ph = Math.round(pw * 9 / 16), py = T + 70, px = Math.round((W - pw) / 2);
    const fy = py + ph + 34, cx = W / 2;
    return {
      V: true, floorY: py + ph + 6, msg: [L - 4, T - 3, R - L + 8, 40], pic: [px, py, pw, ph], braziers: [[16, py + ph + 10], [W - 16, py + ph + 10]],
      feet: [[cx - 30, fy + 2], [cx + 6, fy + 10], [cx + 42, fy + 18]], status: [L - 4, B - 58, R - L + 8, 58],
      menu: [L - 4, T - 3, 100], help: [L + 100, T - 3, R - L - 92, 58], enemy: null, rowH: 16, lh: 13,
    };
  }
  const uiY = B - 60, roomy = (uiY - 6) - (T + 32) >= 120;
  const pw = roomy ? 160 : 144, ph = roomy ? 90 : 81, floorY = T + 84;
  return {
    V: false, floorY, msg: [L - 4, T - 4, R - L + 8, 26], pic: [L + 12, T + 32, pw, ph], braziers: [[L + pw + 48, T + 50], [R + 8, T + 50]],
    feet: [[R - 126, floorY + 18], [R - 98, floorY + 36], [R - 70, floorY + 54]], status: [L + 124, uiY, R - L - 120, 62],
    menu: [L - 4, uiY, 124], help: null, enemy: [L - 4, uiY, 124, 62], rowH: 16, lh: 13,
  };
}

const fmt = (s, P) => String(s || '').replace(/\{boss\}/g, String(P.boss_name || 'BOSS').toUpperCase());

function render(ctx, t, p) {
  const P = withDefaults(PARAMS, p), S = screenOf(ctx), L = layout(ctx), B = schedule(ctx.dur, P);
  const tq = step(t, 30), hitTimes = B.hits.map(h => h.t), ta = hitstop(tq, hitTimes, 3), party = (P.party || []).slice(0, 3);
  const sayF = (str, x, y, o) => say(ctx, S, str, x, y, o);
  const boss = String(P.boss_name || 'BOSS').toUpperCase().slice(0, 16);

  // ---- boss motion: drop in with bounce, idle bob, windup/lunge per blade attack, recoil on hero hits
  const [px0, py0, pw, ph] = L.pic;
  let bx = px0, by = py0;
  const du = seg(ta, B.drop, B.land);
  by += Math.round(-(1 - ease.outBounce(du)) * (py0 + ph + 40));
  if (ta > B.land) by += (Math.floor(ta * 2) & 1);                                   // idle bob 1 px on a 0.5 s beat
  let bossFlash = false, bossHp = 1, bossLag = 1;
  for (const a of B.attacks) {
    const u = (ta - a.t0) / a.k;
    if (a.kind === 'blade') {
      if (u > 0.85 && u < 1.2) { by -= Math.round(3 * ease.outCubic(seg(u, 0.85, 1.05))); bx -= Math.round(2 * seg(u, 0.85, 1.05)); } // rear back
      if (u >= 1.2 && u < 1.5) bx += Math.round(8 * hop(seg(u, 1.2, 1.5), 1));                                                       // lunge
    }
  }
  for (const h of B.hits) if (h.boss) {
    const dt = ta - h.t;
    if (dt >= 0 && dt < 0.12) bossFlash = true;
    if (dt >= 0 && dt < 0.3) bx += (Math.floor(dt * 30) & 1) ? 2 : -2;
    if (typeof h.dmg === 'number') { bossHp -= 0.02 * stepSegSafe(tq, h.t + 0.1, h.t + 0.5); bossLag -= 0.02 * seg(tq, h.t + 0.6, h.t + 0.9); }
  }

  // ---- background + boss glow
  chamber(S, tq, { floorY: L.floorY, braziers: L.braziers, carpetX: L.V ? S.w / 2 : 270, glow: { x: bx + pw / 2, y: by + ph / 2, r: pw * 0.9, k: 0.75 } });

  // ---- product portrait
  const asset = assetOf(ctx, P.boss_media);
  const useCut = !!(asset && asset.cutout && P.backdrop !== 'media');
  const spr = !asset ? null : useCut
    ? productSprite(ctx, asset.cutout, { w: pw - 8, h: ph - 6, t: tq, palette: P.palette, dither: P.dither, fit: 'contain', outline: 'ink' })
    : productSprite(ctx, asset, { w: pw, h: ph, t: tq, palette: P.palette, dither: P.dither, fit: P.fit });
  const clicked = tq >= B.click;
  const gold = clicked ? (Math.floor((tq - B.click) * 10) & 1 ? 0.5 : 0.25) * (1 - seg(tq, B.click + 0.3, B.click + 0.6)) : 0;
  bossFrame(S, spr, bx, by, pw, ph, { lair: useCut, name: boss, level: P.boss_level === '' ? null : P.boss_level, hp: bossHp, hpLag: bossLag, t: tq, gold,
    remap: bossFlash ? whiteMap() : null, say: sayF });

  // ---- party (facing left), hurt reactions
  const hpMax = party.map((_, i) => (P.party_hp || [])[i] || 150);
  const hp = hpMax.map(m => ({ v: m, lag: m }));
  for (const h of B.hits) if (!h.boss && hp[h.hero]) {
    hp[h.hero].v -= h.dmg * stepSegSafe(tq, h.t + 0.08, h.t + 0.5);
    hp[h.hero].lag -= h.dmg * seg(tq, h.t + 0.7, h.t + 1.1);
  }
  const heroAttack = B.attacks.find(a => a.kind !== 'blade' && ta >= a.t0 && ta < a.t0 + a.len);
  party.forEach((id, i) => {
    const F = heroFrames(id); let [fx, fy] = L.feet[i] || [L.feet[0][0] + i * 30, L.feet[0][1]];
    let cel = idleCel(id, ta, i * 0.5), white = false;
    const myHits = B.hits.filter(h => h.hero === i);
    for (const h of myHits) {
      const dt = ta - h.t;
      if (dt >= 0 && dt < 0.5) { cel = F.hurt; fx += Math.round(4 * (1 - seg(dt, 0.15, 0.5))); white = dt < 0.07; }
    }
    if (heroAttack && heroAttack.by === id) {
      const u = (ta - heroAttack.t0) / heroAttack.k;
      const fwd = Math.round(18 * (u < 0.8 ? ease.outCubic(seg(u, 0.55, 0.8)) : 1 - ease.inOutQuad(seg(u, 1.25, 1.6))));
      fx -= fwd; cel = u < 0.55 ? F.ready : u < 0.9 ? F.windup : u < 1.25 ? F.strike : F.ready;
    }
    if (clicked && tq - B.click > 0.25) cel = (Math.floor(tq * 4) & 1) ? F.win0 : F.win1;
    S.ellipse(fx, fy + 1, 7, 2, 'ink', 0.7);
    S.blit(cel, fx - (HERO_ANCHOR.w - HERO_ANCHOR.x - 1), fy - HERO_ANCHOR.y, { flip: true, solid: white ? 'white' : null });
  });

  // ---- attack effects
  for (const a of B.attacks) {
    const u = (ta - a.t0) / a.k;
    if (a.kind === 'blade' && u >= 1.2 && u < 2.45) drawBlade(S, ta, a, L, bx, by, pw, ph, party.length);
    if (a.kind !== 'blade' && u >= 0.9 && u < 1.3) {
      const cx = bx + pw / 2, cy = by + ph / 2;
      if (a.kind === 'slash') slashArc(S, cx + 10, cy, 34, -2.2, -0.2, seg(u, 0.9, 1.15));
      else for (let k = 0; k < 6; k++) sparkle(S, cx + Math.cos(k + u * 9) * 30 * (1 - seg(u, 0.9, 1.2)), cy + Math.sin(k + u * 9) * 18, 1, 'white', 'teal');
    }
  }
  for (const h of B.hits) {
    const dt = ta - h.t;
    if (dt >= 0 && dt < 0.2) {
      const [fx, fy] = h.boss ? [bx + pw / 2, by + ph / 2] : (L.feet[h.hero] || L.feet[0]);
      burst(S, Math.round(fx), Math.round(h.boss ? fy : fy - 14), h.boss ? 16 : 11, Math.floor(dt * 20));
    }
  }
  for (const h of B.hits) {
    const [fx, fy] = h.boss ? [bx + pw / 2, by + 10] : (L.feet[h.hero] || L.feet[0]);
    damageNumber(S, Math.round(fx), Math.round(h.boss ? fy : fy - 40), h.boss ? h.dmg : h.dmg, tq - h.t - 0.05, { color: h.boss && typeof h.dmg !== 'number' ? 'ice' : 'white', life: 1.4 });
  }

  // ---- UI
  const msg = messageAt(tq, B, P, boss);
  const [mx, my, mw, mh] = L.msg;
  if (tq > B.land && !(L.V && tq >= B.menuT)) dialog(S, mx, my, mw, mh, msg.lines, { t: tq, t0: msg.t0, cps: 34, more: msg.more, say: sayF });

  const [sx, sy, sw, sh] = L.status;
  const inner = win(S, sx, sy, sw, sh);
  if (inner) party.forEach((id, i) => {
    const y = inner.y + i * L.rowH, cur = Math.max(0, Math.round(hp[i].v)), danger = cur / hpMax[i] < 0.35;
    const hurtNow = B.hits.some(h => h.hero === i && tq >= h.t && tq < h.t + 0.5);
    sayF(id.toUpperCase().slice(0, 6), inner.x + 2, y, { font: 'caps', color: hurtNow && (Math.floor(tq * 15) & 1) ? 'coral' : 'white', shadow: [1, 1, 'ink'] });
    const barX = inner.x + 56, barW = Math.max(40, inner.w - 56 - 14 - 64);
    drawText(S, 'HP', barX, y - 1, { font: 'tiny', color: 'ice', shadow: [1, 1, 'ink'] });
    bar(S, barX + 14, y, barW, hp[i].v / hpMax[i], { h: 6, lag: hp[i].lag / hpMax[i] });
    sayF(`${cur}/${hpMax[i]}`, inner.x + inner.w, y, { font: 'caps', color: danger ? 'coral' : 'white', shadow: [1, 1, 'ink'], align: 'right' });
  });

  const menuOpen = seg(tq, B.menuT, B.menuT + 0.2);
  if (L.enemy && menuOpen < 1) {
    const [ex, ey, ew, eh] = L.enemy, inr = win(S, ex, ey, ew, eh);
    if (inr) { sayF(boss.length > 14 ? boss.slice(0, 13) + '.' : boss, inr.x, inr.y + 2, { font: 'mono', color: 'white', shadow: [1, 1, 'ink'] }); drawText(S, 'x1', inr.x, inr.y + 18, { font: 'mono', color: 'silver', shadow: [1, 1, 'ink'] }); }
  }
  let menuPos = null, sel = 0;
  if (menuOpen > 0) {
    sel = 0; for (const m of B.moves) if (tq >= m.t) sel = m.idx;
    const pressed = tq >= B.click && tq < B.click + 0.3;
    const [nx, ny, nw] = L.menu;
    menuPos = menu(S, nx, ny, nw, (P.menu || []).map(s => String(s).toUpperCase().slice(0, 6)), sel, { lh: L.lh, open: menuOpen, pressed, flashOn: Math.floor(tq * 15) & 1,
      chosen: clicked ? B.pickIdx : -1, bob: pressed || clicked ? 0 : cursorBob(tq), colors: Object.fromEntries((P.menu || []).map((m, i) => [i, i === B.pickIdx ? 'cream' : 'white'])), say: sayF });
    const pk = menuPos[B.pickIdx];   // a coin next to the pick: the eye goes there before the cursor does
    if (menuOpen >= 1 && pk && !clicked) S.blit(COIN[Math.floor(tq * 8) & 3], pk.x + pk.w + 4, pk.y + 1);
    if (L.help && menuOpen >= 1) {
      const [hx, hy, hw, hh] = L.help, inr = win(S, hx, hy, hw, hh, { theme: 'night' });
      const text = sel === B.pickIdx ? P.pick_text : ({ FIGHT: 'Attack the boss.', ITEM: 'Use an item.', RUN: 'Try to escape.' }[String(P.menu[sel]).toUpperCase()] || '');
      if (inr && text) wrap(text, inr.w, 'mono').slice(0, 3).forEach((ln, k) => sayF(ln, inr.x, inr.y + k * 14, { font: 'mono', color: sel === B.pickIdx ? 'gold' : 'ice', shadow: [1, 1, 'ink'] }));
    }
  }
  // ---- the click: sparkles + coins burst from the picked item
  if (menuPos && clicked && menuPos[B.pickIdx]) {
    const it = menuPos[B.pickIdx], cx = it.x + Math.round(it.w / 2), cy = it.y + 4, dt = tq - B.click;
    if (dt < 0.25) burst(S, it.x - 14, cy, 8, Math.floor(dt * 16), ['white', 'cream', 'gold', 'amber']);   // at the cursor tip
    for (let k = 0; k < 7; k++) {
      const a = -Math.PI / 2 + (rand(5, k) - 0.5) * 2.2, v = 70 + rand(6, k) * 60, dtk = dt - k * 0.03;
      if (dtk < 0 || dtk > 0.9) continue;
      const x = cx + Math.cos(a) * v * dtk, y = cy + Math.sin(a) * v * dtk + 300 * dtk * dtk;
      S.blit(COIN[Math.floor(dtk * 16 + k) & 3], Math.round(x) - 3, Math.round(y) - 3);
    }
    if (dt > 0.05) for (let k = 0; k < 4; k++) sparkle(S, cx + Math.round(Math.cos(k * 1.57 + 0.78) * (22 + dt * 50)), cy + Math.round(Math.sin(k * 1.57 + 0.78) * (12 + dt * 26)), (Math.floor(dt * 15) + k) % 2, 'white', 'gold');
  }

  // ---- screen effects
  const shakes = B.hits.map(h => ({ t: h.t, amp: h.boss ? 2 : 3, dur: 0.3 })).concat([{ t: B.land, amp: 4, dur: 0.4 }]);
  const [dx, dy] = shakeAt(tq, shakes);
  if (dx || dy) S.shift(dx, dy, 'ink');
  const firstBossHit = B.hits.find(h => !h.boss);
  if (firstBossHit) {
    const dt = tq - firstBossHit.t;
    if (dt >= 0 && dt < 1 / 30) flash(S, 'white', 0.5);
    else if (dt >= 1 / 30 && dt < 4 / 30) flash(S, 'red', 0.5);
  }
  if (tq < 0.1) flash(S, 'white', 1 - tq * 10);                 // encounter flash
  else if (tq < B.drop) fade(S, 1);
  present(ctx, S);
}

function stepSegSafe(t, a, b) { return ease.outCubic(seg(step(t, 15), a, b)); }
let WHITE = null;
function whiteMap() { if (!WHITE) { WHITE = new Uint8Array(256); for (let i = 0; i < 256; i++) WHITE[i] = i < 32 ? 7 : i; } return WHITE; }

/** The spinning blade: launch arc -> sweep through each hero -> boomerang back. With a 2-frame afterimage trail. */
function drawBlade(S, ta, a, L, bx, by, pw, ph, n) {
  const k = a.k, start = [bx + pw + 4, by + ph * 0.5], heroes = L.feet.slice(0, n).map(([x, y]) => [x, y - 14]);
  const tLaunch = a.t0 + 1.2 * k, tFirst = a.t0 + 1.55 * k, tLast = tFirst + (n - 1) * 0.12 * k, tBack = a.t0 + 2.45 * k;
  const pos = (tt) => {
    if (tt < tFirst) { const u = ease.inQuad(seg(tt, tLaunch, tFirst)), [x1, y1] = heroes[0]; const cx = (start[0] + x1) / 2, cy = Math.min(start[1], y1) - 40;
      return [lerp(lerp(start[0], cx, u), lerp(cx, x1, u), u), lerp(lerp(start[1], cy, u), lerp(cy, y1, u), u)]; }
    if (tt < tLast) { const f = seg(tt, tFirst, tLast) * (n - 1), i = Math.min(n - 2, Math.floor(f)), u = f - i; return [lerp(heroes[i][0], heroes[i + 1][0], u), lerp(heroes[i][1], heroes[i + 1][1], u)]; }
    const u = ease.inOutQuad(seg(tt, tLast, tBack)), [x1, y1] = heroes[n - 1]; const cx = (start[0] + x1) / 2 + 30, cy = Math.max(start[1], y1) + 30;
    return [lerp(lerp(x1, cx, u), lerp(cx, start[0], u), u), lerp(lerp(y1, cy, u), lerp(cy, start[1], u), u)];
  };
  if (ta >= tBack) return;
  const ang = Math.floor(ta * 30);
  for (const [lag, al] of [[2 / 30, 0.3], [1 / 30, 0.6]]) { if (ta - lag < tLaunch) continue; const [x, y] = pos(ta - lag); blade(S, x, y, ang - (lag * 30), { alpha: al }); }
  const [x, y] = pos(ta); blade(S, x, y, ang);
}

/** The message shown at time t: {lines, t0, more}. */
function messageAt(t, B, P, boss) {
  let m = { lines: fmt(P.intro_text, P), t0: B.intro, more: true };
  for (const a of B.attacks) {
    if (t >= a.t0) {
      const who = a.by === 'boss' ? boss : String(a.by).toUpperCase();
      m = { lines: [[[who, a.by === 'boss' ? 'coral' : 'gold'], [' used ', 'white'], [String(a.move || (a.kind === 'slash' ? 'SLASH' : 'SPELL')).toUpperCase(), 'teal'], ['!', 'white']]], t0: a.t0, more: false };
    }
    if (a.kind === 'blade' && t >= a.t0 + 2.3 * a.k) m = { lines: fmt(P.taunt, P), t0: a.t0 + 2.3 * a.k, more: true };
    if (a.kind !== 'blade' && t >= a.t0 + 1.35 * a.k) m = { lines: typeof a.dmg === 'number' ? `${boss} took ${a.dmg} damage.` : `${boss} is unfazed.`, t0: a.t0 + 1.35 * a.k, more: true };
  }
  if (t >= B.menuT) m = { lines: fmt(P.prompt, P), t0: B.menuT, more: false };
  const lastMove = B.moves.length ? B.moves[B.moves.length - 1].t : B.menuT + 0.3;
  if (t >= lastMove && P.pick_text) m = { lines: [[[String(P.pick).toUpperCase(), 'gold'], [': ', 'white'], [fmt(P.pick_text, P), 'white']]], t0: lastMove, more: false };
  return m;
}

function cues(ctx, p) {
  const P = withDefaults(PARAMS, p), B = schedule(ctx.dur, P), out = [cue(B.land, 'boss_appear')];
  const blips = (t0, n) => { for (let i = 2; i < n; i += 4) out.push(cue(t0 + i / 34, 'blip')); };
  blips(B.intro, fmt(P.intro_text, P).length);
  for (const a of B.attacks) {
    blips(a.t0, 20);
    if (a.kind === 'blade') { out.push(cue(a.t0 + 1.2 * a.k, 'throw')); }
    else out.push(cue(a.t0 + 0.9 * a.k, 'slash'));
  }
  for (const h of B.hits) out.push(cue(h.t, h.boss ? 'hit' : (h === B.hits.find(x => !x.boss) ? 'hit' : 'damage')));
  out.push(cue(B.menuT, 'menu_open'));
  for (const m of B.moves) out.push(cue(m.t, 'menu_move'));
  out.push(cue(B.click, 'menu_select'), cue(B.click + 0.12, 'buy'));
  return out.sort((a, b) => a.t - b.t);
}

/** Where the picked menu item sits (0..1 of the surface) — use as petal-bloom `origin`. */
export function pickOrigin(aspect = '16:9', P = {}, safe = null) {
  const V = aspect === '9:16', W = V ? 270 : 480, H = V ? 480 : 270;
  const sf = safe || (V ? { l: 30, r: 30, t: 55, b: 105 } : { l: 24, r: 24, t: 16, b: 30 });
  const L = layout({ w: W, h: H, safe: sf });
  const items = P.menu || PARAMS.menu.default, i = Math.max(0, items.findIndex(m => String(m).toUpperCase() === String(P.pick || 'BUY').toUpperCase()));
  const [mx, my] = L.menu;
  return [(mx + 20 + 12) / W, (my + 8 + i * L.lh + 4) / H];
}

export const bossBattle = {
  id: 'kit:pixel/boss-battle',
  def: {
    layer: '2d',
    describe: 'Pixel boss battle where the PRODUCT is the boss (its media, palette-quantised, in a horned gold frame with name plate + HP bar). The boss hurls a spinning blade through the party (hit-stop, shake, flashes, damage numbers, HP drain); the command menu opens and the cursor clicks the pick (BUY). res [480,270] or [270,480].',
    params: PARAMS,
    render,
    cues,
  },
};
