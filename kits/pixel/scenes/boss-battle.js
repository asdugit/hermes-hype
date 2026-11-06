// boss-battle.js — kit:pixel/boss-battle: the PRODUCT is the boss. A palette-quantised portrait of the product
// media (video plays inside a gold horned frame with name plate + HP bar) faces the party. The boss revs, winds up
// and hurls a big spinning blade on a screen-wide arc through the heroes (anticipation, hit-stop, flashes, shake,
// damage numbers, HP drain), then the command menu opens and the cursor walks to the pick (BUY) and clicks it.
// A cinematic camera (close on the boss, whip to the party on the hits, wide for the menu, push in on the prize)
// moves the WORLD; the UI (messages, status, menu) sits on its own layer and is never zoomed.
import { screenOf, uiOf, withDefaults, isVertical, say, present, assetOf } from './base.js';
import { chamber } from './../bg/chamber.js';
import { heroFrames, idleCel, HERO_ANCHOR } from './../art/heroes.js';
import { blade, burst, slashArc, flash, sparkle, fade, puff } from './../art/fx.js';
import { productSprite, bossFrame } from './../art/product.js';
import { win, bar, dialog, menu, damageNumber, cursorBob, COIN } from './../ui/ui.js';
import { drawText, wrap } from './../core/text.js';
import { step, seg, ease, hop, clamp, lerp, shakeAt, hitstop, rand } from './../core/motion.js';
import { camAt, punch } from './../core/camera.js';
import { REMAP } from './../core/palette.js';
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
  camera: { type: 'string', default: 'cinematic', doc: 'cinematic (close on the boss, whip to the party on the hits, wide for the menu, push in on the prize) | static' },
  palette: { type: 'list', default: null, doc: 'sub-palette tokens for the product sprite (null = all 32 colours)' },
  dither: { type: 'number', default: 28, doc: 'ordered-dither strength for the product (0 = flat)' },
  fit: { type: 'string', default: 'cover', doc: 'product fit inside the portrait: cover | contain' },
  backdrop: { type: 'string', default: 'auto', doc: 'auto (lair backdrop behind the product cutout when the asset has one) | media (the media as filmed)' },
};

const LEN = { blade: 2.9, slash: 1.9, spell: 2.0 };
const HITSTOP = 5;   // frames frozen on every impact

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
  // impact times are authored in animation time (ta); each earlier impact's hit-stop pushes later ones back in
  // shot time (t), so the blade visibly arrives on every hero exactly when its hit lands
  const hits = [];
  for (const a of attacks) {
    if (a.kind === 'blade') {
      const n = (P.party || []).length;
      for (let i = 0; i < n; i++) hits.push({ ta: a.t0 + (1.55 + i * 0.14) * a.k, hero: i, dmg: (a.dmg || [])[i] ?? 40, a });
    } else hits.push({ ta: a.t0 + 1.0 * a.k, boss: true, dmg: a.dmg ?? 'MISS', a });
  }
  hits.sort((x, y) => x.ta - y.ta).forEach((h, i) => { h.t = h.ta + i * HITSTOP / 30; });
  return { dur, drop, land, intro, attacks, menuT, moves, click, pickIdx, hits };
}

/** Safe-area-aware layout (text stays inside ctx.safe; art may bleed to the edges). */
export function layout(ctx) {
  const sf = ctx.safe || {}, W = ctx.w, H = ctx.h;
  const L = Math.max(4, Math.round(sf.l || 0)), T = Math.max(4, Math.round(sf.t || 0));
  const R = W - Math.max(4, Math.round(sf.r || 0)), B = H - Math.max(4, Math.round(sf.b || 0));
  if (isVertical(ctx)) {
    const pw = Math.min(200, W - 24), ph = Math.round(pw * 9 / 16), py = T + 70, px = Math.round((W - pw) / 2);
    const fy = py + ph + 62, cx = W / 2;
    return {
      V: true, floorY: py + ph + 6, msg: [L - 4, T - 3, R - L + 8, 40], pic: [px, py, pw, ph], braziers: [[16, py + ph + 10], [W - 16, py + ph + 10]],
      feet: [[cx - 30, fy], [cx + 6, fy + 5], [cx + 42, fy + 10]], status: [L - 4, B - 58, R - L + 8, 58],
      menu: [L - 4, T - 3, 100], help: [L + 100, T - 3, R - L - 92, 58], enemy: null, rowH: 16, lh: 13, top: T + 40, zmax: 1.5,
    };
  }
  const uiY = B - 60, roomy = (uiY - 6) - (T + 32) >= 120;
  const pw = roomy ? 160 : 144, ph = roomy ? 90 : 81, floorY = T + 84;
  return {
    V: false, floorY, msg: [L - 4, T - 4, R - L + 8, 26], pic: [L + 12, T + 32, pw, ph], braziers: [[L + pw + 48, T + 50], [R + 8, T + 50]],
    feet: [[R - 126, floorY + 18], [R - 98, floorY + 36], [R - 70, floorY + 54]], status: [L + 124, uiY, R - L - 120, 62],
    menu: [L - 4, uiY, 124], help: null, enemy: [L - 4, uiY, 124, 62], rowH: 16, lh: 13, top: T + 24, zmax: 1.75,
  };
}

const fmt = (s, P) => String(s || '').replace(/\{boss\}/g, String(P.boss_name || 'BOSS').toUpperCase());

function render(ctx, t, p) {
  const P = withDefaults(PARAMS, p), S = screenOf(ctx), U = uiOf(ctx), L = layout(ctx), B = schedule(ctx.dur, P);
  const tq = step(t, 30), hitTimes = B.hits.map(h => h.t), ta = hitstop(tq, hitTimes, HITSTOP), party = (P.party || []).slice(0, 3);
  const sayW = (str, x, y, o) => say(ctx, S, str, x, y, o), sayU = (str, x, y, o) => say(ctx, U, str, x, y, o);
  const boss = String(P.boss_name || 'BOSS').toUpperCase().slice(0, 16);
  const blades = B.attacks.filter(a => a.kind === 'blade');

  // ---- boss motion: drop in with bounce, engine rev, windup/lunge per blade attack, recoil on hero hits
  const [px0, py0, pw, ph] = L.pic;
  let bx = px0, by = py0;
  const du = seg(ta, B.drop, B.land);
  by += Math.round(-(1 - ease.outBounce(du)) * (py0 + ph + 40));
  if (ta > B.land) by += (Math.floor(ta * 2) & 1);                                   // idle bob 1 px on a 0.5 s beat
  const revving = revAt(ta, B);
  let charge = 0;
  for (const a of blades) {
    const u = (ta - a.t0) / a.k;
    if (u > 0.25 && u < 1.2) charge = Math.max(charge, seg(u, 0.25, 1.15));
    if (u > 0.85 && u < 1.2) { by -= Math.round(4 * ease.outCubic(seg(u, 0.85, 1.05))); bx -= Math.round(3 * seg(u, 0.85, 1.05)); } // rear back
    if (u >= 1.2 && u < 1.5) bx += Math.round(12 * hop(seg(u, 1.2, 1.5), 1));                                                    // lunge
  }
  let bossFlash = false, bossHp = 1, bossLag = 1;
  for (const h of B.hits) if (h.boss) {
    const dt = tq - h.t;
    if (dt >= 0 && dt < 0.12) bossFlash = true;
    if (dt >= 0 && dt < 0.3) bx += (Math.floor(dt * 30) & 1) ? 2 : -2;
    if (typeof h.dmg === 'number') { bossHp -= 0.02 * stepSegSafe(tq, h.t + 0.1, h.t + 0.5); bossLag -= 0.02 * seg(tq, h.t + 0.6, h.t + 0.9); }
  }
  const rev = revving > 0 ? ((Math.floor(tq * 15) & 1) ? 1 : 0) * Math.round(revving) : 0;   // engine shudder (whole px)

  // ---- background + boss glow (the glow swells while the boss charges)
  chamber(S, tq, { floorY: L.floorY, braziers: L.braziers, carpetX: L.V ? S.w / 2 : 270,
    glow: { x: bx + pw / 2, y: by + ph / 2, r: pw * (0.9 + 0.5 * charge), k: 0.75 + 0.25 * charge } });
  if (charge > 0.2) S.glow(bx + pw / 2, by + ph / 2, pw * (0.75 + 0.45 * charge), REMAP.ember, 0.6 + charge, 0.7);

  // ---- product portrait
  const asset = assetOf(ctx, P.boss_media);
  const useCut = !!(asset && asset.cutout && P.backdrop !== 'media');
  const spr = !asset ? null : useCut
    ? productSprite(ctx, asset.cutout, { w: pw - 8, h: ph - 6, t: tq, palette: P.palette, dither: P.dither, fit: 'contain', outline: 'ink' })
    : productSprite(ctx, asset, { w: pw, h: ph, t: tq, palette: P.palette, dither: P.dither, fit: P.fit });
  const clicked = tq >= B.click;
  const gold = clicked ? (Math.floor((tq - B.click) * 10) & 1 ? 0.5 : 0.25) * (1 - seg(tq, B.click + 0.3, B.click + 0.6)) : 0;
  bossFrame(S, spr, bx, by - rev, pw, ph, { lair: useCut, name: boss, level: P.boss_level === '' ? null : P.boss_level, hp: bossHp, hpLag: bossLag, t: tq, gold,
    aura: 1 + charge, remap: bossFlash ? whiteMap() : null, say: sayW });
  // engine rev: exhaust puffs from the car's tail + a headlight glint
  if (revving > 0 && useCut) {
    S.clip(bx, by, pw, ph);
    for (let k = 0; k < 3; k++) { const f = Math.floor((tq * 15 + k * 5) % 15) / 3; if (f < 4) puff(S, bx + 18 - f * 4, by + ph * 0.66 - f * 2, Math.floor(f)); }
    S.unclip();
    if (Math.floor(tq * 6) & 1) sparkle(S, bx + Math.round(pw * 0.83), by + Math.round(ph * 0.56) - rev, 1, 'white', 'cream');
  }
  if (charge > 0.35 && Math.floor(tq * 10) & 1) for (let k = 0; k < 4; k++) {     // charge sparks converging on the frame
    const a = rand(31, k, Math.floor(tq * 10)) * 6.283, r = (1 - charge) * 60 + 18;
    sparkle(S, bx + pw / 2 + Math.cos(a) * r * 1.4, by + ph / 2 + Math.sin(a) * r * 0.8, 0, 'gold', 'amber');
  }

  // ---- party (facing left), hurt reactions
  const hpMax = party.map((_, i) => (P.party_hp || [])[i] || 150);
  const hp = hpMax.map(m => ({ v: m, lag: m }));
  for (const h of B.hits) if (!h.boss && hp[h.hero]) {
    hp[h.hero].v -= h.dmg * stepSegSafe(tq, h.t + 0.08, h.t + 0.5);
    hp[h.hero].lag -= h.dmg * seg(tq, h.t + 0.9, h.t + 1.3);
  }
  const heroAttack = B.attacks.find(a => a.kind !== 'blade' && ta >= a.t0 && ta < a.t0 + a.len);
  party.forEach((id, i) => {
    const F = heroFrames(id); let [fx, fy] = L.feet[i] || [L.feet[0][0] + i * 30, L.feet[0][1]];
    let cel = idleCel(id, ta, i * 0.5), white = false;
    for (const a of blades) { const u = (ta - a.t0) / a.k; if (u > 0.5 && u < 1.55) cel = F.ready; }  // brace for it
    const myHits = B.hits.filter(h => h.hero === i);
    for (const h of myHits) {
      const dt = tq - h.t;
      if (dt >= 0 && dt < 0.6) { cel = F.hurt; fx += Math.round(7 * (1 - seg(dt, 0.15, 0.6))); white = dt < 0.1; }
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
  let bladeAt = null;
  for (const a of B.attacks) {
    const u = (ta - a.t0) / a.k;
    if (a.kind === 'blade' && u >= 1.2 && u < 2.55) bladeAt = drawBlade(S, ta, a, L, bx, by, pw, ph, party.length);
    if (a.kind !== 'blade' && u >= 0.9 && u < 1.3) {
      const cx = bx + pw / 2, cy = by + ph / 2;
      if (a.kind === 'slash') slashArc(S, cx + 10, cy, 34, -2.2, -0.2, seg(u, 0.9, 1.15));
      else for (let k = 0; k < 6; k++) sparkle(S, cx + Math.cos(k + u * 9) * 30 * (1 - seg(u, 0.9, 1.2)), cy + Math.sin(k + u * 9) * 18, 1, 'white', 'teal');
    }
  }
  for (const h of B.hits) {
    const dt = tq - h.t;
    if (dt >= 0 && dt < 0.2) {
      const [fx, fy] = h.boss ? [bx + pw / 2, by + ph / 2] : (L.feet[h.hero] || L.feet[0]);
      burst(S, Math.round(fx), Math.round(h.boss ? fy : fy - 16), h.boss ? 16 : 15, Math.floor(dt * 20));
    }
  }
  for (const h of B.hits) {
    const [fx, fy] = h.boss ? [bx + pw / 2, by + 10] : (L.feet[h.hero] || L.feet[0]);
    damageNumber(S, Math.round(fx), Math.round(h.boss ? fy : L.V ? Math.max(L.pic[1] + L.pic[3] + 36, fy - 46) : fy - 46), h.dmg, tq - h.t - 0.05,
      { color: h.boss && typeof h.dmg !== 'number' ? 'ice' : 'white', life: 1.5, scale: 2, height: 14 });
  }

  // ---- camera (world only)
  const cam = P.camera === 'static' ? null : bossCam(tq, B, L, S, party.length, bladeAt);

  // ---- UI layer
  const msg = messageAt(tq, B, P, boss);
  const [mx, my, mw, mh] = L.msg;
  if (tq > B.land && !(L.V && tq >= B.menuT)) dialog(U, mx, my, mw, mh, msg.lines, { t: tq, t0: msg.t0, cps: 34, more: msg.more, say: sayU });
  // the bottom windows step away while the camera is in close (cinematic), and step back when it pulls out
  const uiOpen = cam ? uiOpenAt(tq, B, L) : 1;
  const [sx, sy, sw, sh] = L.status;
  const inner = win(U, sx, sy, sw, sh, { open: uiOpen });
  if (inner) party.forEach((id, i) => {
    const y = inner.y + i * L.rowH, cur = Math.max(0, Math.round(hp[i].v)), danger = cur / hpMax[i] < 0.35;
    const hurtNow = B.hits.some(h => h.hero === i && tq >= h.t && tq < h.t + 0.5);
    sayU(id.toUpperCase().slice(0, 6), inner.x + 2, y, { font: 'caps', color: hurtNow && (Math.floor(tq * 15) & 1) ? 'coral' : 'white', shadow: [1, 1, 'ink'] });
    const barX = inner.x + 56, barW = Math.max(40, inner.w - 56 - 14 - 64);
    drawText(U, 'HP', barX, y - 1, { font: 'tiny', color: 'ice', shadow: [1, 1, 'ink'] });
    bar(U, barX + 14, y, barW, hp[i].v / hpMax[i], { h: 6, lag: hp[i].lag / hpMax[i] });
    sayU(`${cur}/${hpMax[i]}`, inner.x + inner.w, y, { font: 'caps', color: danger ? 'coral' : 'white', shadow: [1, 1, 'ink'], align: 'right' });
  });

  const menuOpen = seg(tq, B.menuT, B.menuT + 0.2);
  if (L.enemy && menuOpen < 1) {
    const [ex, ey, ew, eh] = L.enemy, inr = win(U, ex, ey, ew, eh, { open: uiOpen });
    if (inr) { sayU(boss.length > 14 ? boss.slice(0, 13) + '.' : boss, inr.x, inr.y + 2, { font: 'mono', color: 'white', shadow: [1, 1, 'ink'] }); drawText(U, 'x1', inr.x, inr.y + 18, { font: 'mono', color: 'silver', shadow: [1, 1, 'ink'] }); }
  }
  let menuPos = null, sel = 0;
  if (menuOpen > 0) {
    sel = 0; for (const m of B.moves) if (tq >= m.t) sel = m.idx;
    const pressed = tq >= B.click && tq < B.click + 0.3;
    const [nx, ny, nw] = L.menu;
    menuPos = menu(U, nx, ny, nw, (P.menu || []).map(s => String(s).toUpperCase().slice(0, 6)), sel, { lh: L.lh, open: menuOpen, pressed, flashOn: Math.floor(tq * 15) & 1,
      chosen: clicked ? B.pickIdx : -1, bob: pressed || clicked ? 0 : cursorBob(tq), colors: Object.fromEntries((P.menu || []).map((m, i) => [i, i === B.pickIdx ? 'cream' : 'white'])), say: sayU });
    const pk = menuPos[B.pickIdx];   // a coin next to the pick: the eye goes there before the cursor does
    if (menuOpen >= 1 && pk && !clicked) U.blit(COIN[Math.floor(tq * 8) & 3], pk.x + pk.w + 4, pk.y + 1);
    if (L.help && menuOpen >= 1) {
      const [hx, hy, hw, hh] = L.help, inr = win(U, hx, hy, hw, hh, { theme: 'night' });
      const text = sel === B.pickIdx ? P.pick_text : ({ FIGHT: 'Attack the boss.', ITEM: 'Use an item.', RUN: 'Try to escape.' }[String(P.menu[sel]).toUpperCase()] || '');
      if (inr && text) wrap(text, inr.w, 'mono').slice(0, 3).forEach((ln, k) => sayU(ln, inr.x, inr.y + k * 14, { font: 'mono', color: sel === B.pickIdx ? 'gold' : 'ice', shadow: [1, 1, 'ink'] }));
    }
  }
  // ---- the click: sparkles + coins burst from the picked item
  if (menuPos && clicked && menuPos[B.pickIdx]) {
    const it = menuPos[B.pickIdx], cx = it.x + Math.round(it.w / 2), cy = it.y + 4, dt = tq - B.click;
    if (dt < 0.25) burst(U, it.x - 14, cy, 10, Math.floor(dt * 16), ['white', 'cream', 'gold', 'amber']);   // at the cursor tip
    for (let k = 0; k < 10; k++) {
      const a = -Math.PI / 2 + (rand(5, k) - 0.5) * 2.4, v = 80 + rand(6, k) * 80, dtk = dt - k * 0.03;
      if (dtk < 0 || dtk > 1.0) continue;
      const x = cx + Math.cos(a) * v * dtk, y = cy + Math.sin(a) * v * dtk + 300 * dtk * dtk;
      U.blit(COIN[Math.floor(dtk * 16 + k) & 3], Math.round(x) - 3, Math.round(y) - 3);
    }
    if (dt > 0.05) for (let k = 0; k < 6; k++) sparkle(U, cx + Math.round(Math.cos(k * 1.047 + 0.5) * (22 + dt * 60)), cy + Math.round(Math.sin(k * 1.047 + 0.5) * (12 + dt * 30)), (Math.floor(dt * 15) + k) % 2, 'white', 'gold');
  }

  // ---- screen effects (impacts shake the whole screen; flashes hit the world)
  const shakes = B.hits.map(h => ({ t: h.t, amp: h.boss ? 2 : 4, dur: 0.35 })).concat([{ t: B.land, amp: 5, dur: 0.45 }]);
  const [dx, dy] = shakeAt(tq, shakes);
  if (dx || dy) { S.shift(dx, dy, 'ink'); U.shift(dx, dy, null); }
  for (const h of B.hits) if (!h.boss) {
    const dt = tq - h.t;
    if (dt >= 0 && dt < 1 / 30) flash(S, 'white', 0.5);
    else if (h === B.hits.find(x => !x.boss) && dt >= 1 / 30 && dt < 4 / 30) flash(S, 'red', 0.5);
  }
  if (charge > 0.5) fadeEdges(S, bx, by, pw, ph, charge);
  if (tq < 0.1) flash(S, 'white', 1 - tq * 10);                 // encounter flash
  else if (tq < B.drop) fade(S, 1);
  present(ctx, S, { ui: U, cam });
}

/** Engine rev strength (0/1/2 px shudder) — while the boss growls in and during the windup. */
function revAt(t, B) {
  if (t > B.land + 0.1 && t < B.intro + 1.1) return 1;
  for (const a of B.attacks) if (a.kind === 'blade') { const u = (t - a.t0) / a.k; if (u > 0.35 && u < 1.15) return u > 0.8 ? 2 : 1; }
  return 0;
}

/** While the boss charges, the room darkens toward the edges (dithered) so the eye locks onto the boss. */
function fadeEdges(S, bx, by, pw, ph, charge) {
  const level = charge > 0.85 ? 2 : 1, map = REMAP.fade[level];
  const cx = bx + pw / 2, cy = by + ph / 2, r = Math.max(pw, ph) * 1.25;
  for (let j = 0; j < S.h; j++) for (let i = 0; i < S.w; i++) {
    const d = Math.hypot((i - cx) / r, (j - cy) / (r * 0.8));
    if (d > 1 && ((i + j) & 1 || d > 1.35)) { const q = j * S.w + i; S.d[q] = map[S.d[q]]; }
  }
}

/** World rect of the boss frame at rest (horns, crest, plate, HP bar) and of the party incl. damage numbers. */
function bossRect(L) { const [x, y, w, h] = L.pic; return { x: x - 22, y: y - 13, w: w + 44, h: h + 13 + 6 + 3 + 17 + 8 }; }
function partyRect(L, n) {
  const ft = L.feet.slice(0, Math.max(1, n)), xs = ft.map(f => f[0]), ys = ft.map(f => f[1]);
  const x0 = Math.min(...xs) - 18, x1 = Math.max(...xs) + 18, y0 = Math.min(...ys) - 60, y1 = Math.max(...ys) + 6;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}
/** Camera that frames world rect `r` inside the screen band [top, bottom] (game px), zoom <= zmax, quarter steps. */
function fit(r, S, L, o = {}) {
  const top = o.top ?? L.top, bottom = o.bottom ?? S.h, zmax = o.zmax ?? L.zmax;
  let z = Math.min(S.w / (r.w * 1.12), (bottom - top) / (r.h * 1.08), zmax);
  z = Math.max(1, Math.floor(z * 4 + 1e-6) / 4);
  const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
  return { zoom: z, x: cx, y: cy - ((top + bottom) / 2 - S.h / 2) / z };
}

/**
 * The battle camera: close on the boss for its entrance and engine rev, pull out for the line-up, push in as it
 * winds up, whip with the blade to the party for the hits (punch on each), pull out for the menu, push in on the
 * prize while the cursor rests on the pick, punch on the click.
 */
function bossCam(t, B, L, S, n, bladeAt) {
  const boss = fit(bossRect(L), S, L), party = fit(partyRect(L, n), S, L, { zmax: L.zmax + 0.25 }), wide = { zoom: 1, x: S.w / 2, y: S.h / 2 };
  // the prize: the product picture framed in the band between the message and the menu windows (plate goes under)
  const [px0, py0, pw, ph] = L.pic, uiTop = L.V ? S.h : L.status[1];
  const prize = fit({ x: px0 - 10, y: py0 - 6, w: pw + 20, h: ph + 12 }, S, L, { bottom: uiTop, zmax: 1.5 });
  const ks = [[0, boss], [B.intro + 0.9, boss], [B.intro + 1.4, wide]];
  for (const a of B.attacks) {
    const k = a.k, t0 = a.t0;
    if (a.kind === 'blade') {
      const pushed = { ...boss, zoom: Math.min(L.zmax + 0.25, boss.zoom + 0.25) };
      ks.push([t0 + 0.2 * k, wide], [t0 + 1.15 * k, pushed], [t0 + 1.2 * k, pushed]);
      ks.push([t0 + 1.5 * k, { ...party, ease: ease.outCubic }], [t0 + 2.05 * k, party], [t0 + 2.6 * k, wide]);
    } else {
      ks.push([t0 + 0.4 * k, wide], [t0 + 0.9 * k, { ...boss, zoom: Math.max(1, boss.zoom - 0.25) }], [t0 + 1.6 * k, wide]);
    }
  }
  const lastMove = B.moves.length ? B.moves[B.moves.length - 1].t : B.menuT + 0.6;
  const leanIn = { ...prize, zoom: Math.max(1, prize.zoom - 0.25), ease: ease.linear };
  ks.push([Math.max(B.menuT, ks[ks.length - 1][0] + 0.1), wide], [B.menuT + 0.8, wide], [lastMove, leanIn], [Math.min(B.click - 0.1, lastMove + 0.8), prize], [B.click + 2, prize]);
  ks.sort((a, b) => a[0] - b[0]);
  const c = camAt(t, ks);
  // ride the blade a little while it flies between the boss and the party
  if (bladeAt) { c.x = lerp(c.x, bladeAt[0], 0.25); c.y = lerp(c.y, bladeAt[1], 0.15); }
  c.zoom = Math.round((c.zoom + punch(t, B.hits.map(h => h.t), 0.25, 0.22) + punch(t, [B.click], 0.25, 0.3)) * 4) / 4;
  return c;
}

/** Bottom windows: open when the camera is wide, stepped closed during close-ups. */
function uiOpenAt(t, B, L) {
  if (L.V) return 1;                                                   // 9:16: the status window sits clear of the action
  const spans = [[0, B.intro + 1.2]];
  for (const a of B.attacks) if (a.kind === 'blade') spans.push([a.t0 + 0.6 * a.k, a.t0 + 2.3 * a.k]);
  let o = 1;
  for (const [a, b] of spans) {
    if (t >= a && t < b) o = Math.min(o, 1 - seg(t, a, a + 0.2));
    if (t >= b && t < b + 0.25) o = Math.min(o, seg(t, b, b + 0.25));
  }
  return Math.floor(o * 4 + 1e-6) / 4;
}

function stepSegSafe(t, a, b) { return ease.outCubic(seg(step(t, 15), a, b)); }
let WHITE = null;
function whiteMap() { if (!WHITE) { WHITE = new Uint8Array(256); for (let i = 0; i < 256; i++) WHITE[i] = i < 32 ? 7 : i; } return WHITE; }

/** Catmull-Rom through points at parameter u in [0, 1] (uniform knots). */
function spline(pts, u) {
  const n = pts.length, s = clamp(u) * (n - 1), i = Math.min(n - 2, Math.floor(s)), f = s - i;
  const P = (k) => pts[Math.max(0, Math.min(n - 1, k))];
  const p0 = P(i - 1), p1 = P(i), p2 = P(i + 1), p3 = P(i + 2), f2 = f * f, f3 = f2 * f;
  return [0, 1].map(k => 0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * f + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * f2 + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * f3));
}

/**
 * The spinning blade (double size) on a screen-wide arc: launch up and over, swoop down through each hero, swing out
 * past the party and boomerang back along the floor — with a fading ribbon trail and afterimages. Returns its position.
 */
function drawBlade(S, ta, a, L, bx, by, pw, ph, n) {
  const k = a.k, heroes = L.feet.slice(0, n).map(([x, y]) => [x, y - 16]);
  const tLaunch = a.t0 + 1.2 * k, tFirst = a.t0 + 1.55 * k, tLast = tFirst + (n - 1) * 0.14 * k, tBack = a.t0 + 2.55 * k;
  const start = L.V ? [bx + pw / 2, by + ph + 8] : [bx + pw + 6, by + ph * 0.45];
  const last = heroes[n - 1], first = heroes[0];
  const apex = L.V ? [Math.max(14, first[0] - 70), (start[1] + first[1]) / 2 - 10] : [(start[0] + first[0]) / 2 + 30, Math.max(L.top + 8, first[1] - 74)];
  const out = L.V ? [Math.min(S.w - 12, last[0] + 50), last[1] + 34] : [Math.min(S.w - 10, last[0] + 44), last[1] + 40];
  const under = L.V ? [S.w / 2, (start[1] + first[1]) / 2 + 26] : [(start[0] + first[0]) / 2, Math.min(S.h - 30, L.floorY + 110)];
  const pos = (tt) => {
    if (tt < tFirst) return spline([start, apex, first], ease.inQuad(seg(tt, tLaunch, tFirst)) * 0.999 + 0.0005);
    if (tt < tLast) { const f = seg(tt, tFirst, tLast) * (n - 1), i = Math.min(n - 2, Math.floor(f)), u = f - i; return [lerp(heroes[i][0], heroes[i + 1][0], u), lerp(heroes[i][1], heroes[i + 1][1], u)]; }
    return spline([last, out, under, start], ease.inOutQuad(seg(tt, tLast, tBack)));
  };
  if (ta >= tBack) return null;
  // swoosh trail: a tapering arc along the last 0.22 s of the path (sky -> ice -> white toward the blade)
  for (let i = 13; i >= 1; i--) {
    const t1 = ta - (i - 1) / 60, t0 = ta - i / 60; if (t0 < tLaunch) continue;
    const [x0, y0] = pos(t0), [x1, y1] = pos(t1), th = Math.max(1, Math.round(6 - i * 0.42));
    S.line(x0, y0, x1, y1, i < 4 ? 'white' : i < 8 ? 'ice' : 'sky', th);
  }
  const ang = Math.floor(ta * 30);
  for (const [lag, al] of [[2 / 30, 0.3], [1 / 30, 0.6]]) { if (ta - lag < tLaunch) continue; const [x, y] = pos(ta - lag); bigBlade(S, x, y, ang - lag * 30, al); }
  const [x, y] = pos(ta); bigBlade(S, x, y, ang, 1);
  return [x, y];
}
/** The blade cel at double size, centred on (x, y) (blade() offsets by 8 for its 16 px cel; 32 px needs 16). */
function bigBlade(S, x, y, ang, alpha) { blade(S, Math.round(x) - 8, Math.round(y) - 8, Math.round(ang), { alpha, scale: 2 }); }

/** The message shown at time t: {lines, t0, more}. */
function messageAt(t, B, P, boss) {
  let m = { lines: fmt(P.intro_text, P), t0: B.intro, more: true };
  for (const a of B.attacks) {
    if (t >= a.t0) {
      const who = a.by === 'boss' ? boss : String(a.by).toUpperCase();
      m = { lines: [[[who, a.by === 'boss' ? 'coral' : 'gold'], [' used ', 'white'], [String(a.move || (a.kind === 'slash' ? 'SLASH' : 'SPELL')).toUpperCase(), 'teal'], ['!', 'white']]], t0: a.t0, more: false };
    }
    if (a.kind === 'blade' && t >= a.t0 + 2.4 * a.k) m = { lines: fmt(P.taunt, P), t0: a.t0 + 2.4 * a.k, more: true };
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
    if (a.kind === 'blade') { out.push(cue(a.t0 + 0.4 * a.k, 'charge'), cue(a.t0 + 1.2 * a.k, 'throw')); }
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
    describe: 'Pixel boss battle where the PRODUCT is the boss (its media, palette-quantised, in a horned gold frame with name plate + HP bar). The boss revs, winds up and hurls a big spinning blade on a screen-wide arc through the party (hit-stop, shake, flashes, damage numbers, HP drain); a cinematic camera pushes in and whips to the hits; the command menu opens and the cursor clicks the pick (BUY). res [480,270]/[270,480], or the film size for the full camera.',
    params: PARAMS,
    render,
    cues,
  },
};
