// dungeon-walk.js — kit:pixel/dungeon-walk: the party walks a torch-lit corridor to the sealed
// "LOCKED BOSS" door; it stops, the leader reacts, the chains snap and the door swings open.
import { screenOf, uiOf, withDefaults, isVertical, say, present } from './base.js';
import { wall, floor, torch, torchLights, DUNGEON_LEVELS, banner, chain, bones, bossDoor } from './../bg/dungeon.js';
import { heroFrames, walkCel, idleCel, HERO_ANCHOR } from './../art/heroes.js';
import { EMOTE, puff, fade, flash } from './../art/fx.js';
import { step, seg, ease, shakeAt, hop, clamp, lerp } from './../core/motion.js';
import { punch } from './../core/camera.js';
import { cue } from './../cues.js';

const PARAMS = {
  party: { type: 'list', default: ['knight', 'mage', 'rogue'], doc: 'hero ids in marching order (knight, mage, rogue)' },
  door_label: { type: 'string', default: 'LOCKED BOSS', doc: 'plaque text over the door (<= 16 chars)' },
  open: { type: 'bool', default: true, doc: 'end by breaking the chains and opening the door' },
  open_at: { type: 'number', default: null, doc: 'shot seconds when the door starts to rumble (default dur - 2.0)' },
  speed: { type: 'number', default: 44, doc: 'walk speed in game px per second' },
  caption: { type: 'string', default: '', doc: 'optional one-line message shown in a window while walking' },
  fade_in: { type: 'bool', default: true, doc: 'palette fade from black at the start' },
  camera: { type: 'string', default: 'follow', doc: 'follow (close on the party, pull back to reveal the door, push into it as it opens) | wide (locked off)' },
  zoom: { type: 'number', default: 2, doc: 'close-up zoom while following (2 = 8 px pixels at 1080p on a film-size surface; game-res surfaces floor to 1 or 2)' },
};

function timeline(ctx, P) {
  const dur = ctx.dur, openAt = P.open ? (P.open_at ?? Math.max(1.8, dur - 2.0)) : dur + 10;
  const arrive = Math.min(openAt - 0.9, dur - 0.5);
  return { dur, openAt, arrive, emote: arrive + 0.25, chainsAt: openAt + 0.45, doorT0: openAt + 0.6, doorT1: openAt + 1.4, ready: openAt + 0.7 };
}

function layout(ctx) {
  const V = isVertical(ctx);
  return V ? { V, top: 70, floorY: 330, feet: 372, doorScreenX: 180, leadStopX: 96, gap: 24, torchY: 150 }
    : { V, top: 26, floorY: 196, feet: 236, doorScreenX: 352, leadStopX: 232, gap: 26, torchY: 104 };
}

function render(ctx, t, p) {
  const P = withDefaults(PARAMS, p), S = screenOf(ctx), L = layout(ctx), T = timeline(ctx, P), tq = step(t, 30);
  // world: the door sits at world x = doorWX; the leader stops leadStop px before it
  const doorWX = 1000, stopWX = doorWX - (L.doorScreenX - L.leadStopX);
  const walkT = Math.min(tq, T.arrive), leadWX = Math.round(stopWX - P.speed * (T.arrive - walkT));
  const camEnd = doorWX - L.doorScreenX, camX = Math.round(Math.min(camEnd, leadWX - L.leadStopX));
  const [sx, sy] = shakeAt(tq, [{ t: T.openAt, amp: 2, dur: 0.6 }, { t: T.chainsAt, amp: 4, dur: 0.4 }, { t: T.doorT1, amp: 2, dur: 0.3 }]);

  wall(S, camX, { top: L.top, floorY: L.floorY, skip: (wx) => Math.abs(wx - doorWX) < 80 });
  if (L.V) { // tall vault: hanging chains in the upper space
    for (const wx of [camX - (camX % 70) + 20, camX - (camX % 70) + 90, camX - (camX % 70) + 160, camX - (camX % 70) + 230, camX - (camX % 70) + 300]) chain(S, camX, wx, 40 + (wx % 3) * 14, t);
  }
  floor(S, camX, { floorY: L.floorY });
  // torches every 128 px (not over the door), banners on the pilasters
  const torches = [];
  for (let wx = 0; wx < doorWX + 400; wx += 128) if (Math.abs(wx - doorWX) > 80) torches.push(wx);
  for (let wx = 64; wx < doorWX - 80; wx += 256) banner(S, camX, wx - 7, L.top + 16, { h: 44, sway: tq * 1.3 + wx });
  bones(S, camX, 412, L.floorY + 14); bones(S, camX, 803, L.floorY + 12);
  const openU = P.open ? ease.outCubic(seg(step(tq, 15), T.doorT0, T.doorT1)) : 0;
  const lights = torchLights(camX, torches, L.torchY - 4, tq, { floorY: L.floorY });
  lights.push({ x: doorWX - camX, y: L.floorY - 40, r: 96, k: 0.55 + openU * 0.2 });
  S.light(lights, DUNGEON_LEVELS, 0, 0, S.w, S.h);
  for (const wx of torches) torch(S, camX, wx, L.torchY, tq);

  // the door
  const chains = P.open ? 1 - seg(tq, T.chainsAt, T.chainsAt + 0.8) : 1;
  bossDoor(S, camX, doorWX, L.floorY, tq, { open: openU, chains: tq < T.chainsAt ? 1 : chains, label: P.door_label });

  // party: followers trail the leader along the same path (gap px behind), same cycle with a phase lag
  const party = (P.party || []).slice(0, 4);
  party.forEach((id, i) => {
    const lagT = i * 0.09, myT = Math.max(0, walkT - lagT);
    // followers keep walking a moment after the leader stops (accordion), then settle
    const settle = clamp((tq - T.arrive) / 0.25);
    const wxp = leadWX - i * L.gap + (i > 0 ? Math.round((1 - ease.outCubic(settle)) * -4) : 0);
    const x = wxp - camX, walking = tq < T.arrive + (i ? 0.12 * i : 0);
    let cel = walking ? walkCel(id, myT + i * 0.06, 8) : idleCel(id, tq, i * 0.5);
    if (tq >= T.ready) cel = heroFrames(id).ready;
    S.ellipse(x, L.feet + 1, 7, 2, 'ink', 0.7);
    S.blit(cel, x - HERO_ANCHOR.x, L.feet - HERO_ANCHOR.y);
    // dust at the stop
    if (!walking && tq - T.arrive < 0.3) puff(S, x - 6, L.feet - 1, Math.floor((tq - T.arrive - i * 0.12) * 14));
  });
  // leader's "!" emote (hop in, hold)
  if (party.length && tq >= T.emote && tq < T.openAt + 0.4) {
    const u = seg(tq, T.emote, T.emote + 0.2), lx = leadWX - camX;
    S.blit(EMOTE.bang, lx - 2, L.feet - 44 - Math.round(hop(u, 5)));
  }
  // optional caption window (UI layer: the camera never zooms it)
  const U = P.caption ? uiOf(ctx) : null;
  if (U) captionBox(ctx, U, P.caption, L, tq);

  // screen effects
  if (sx || sy) S.shift(sx, sy, 'ink');
  if (P.open && tq >= T.chainsAt && tq < T.chainsAt + 0.07) flash(S, 'white', 0.5);
  if (P.fade_in) fade(S, 4 - Math.floor(seg(tq, 0, 0.45) * 4.999));
  present(ctx, S, { ui: U, cam: P.camera === 'wide' ? null : walkCam(t, P, L, T, leadWX - camX, doorWX - camX, S.w, S.h) });
}

/**
 * Follow camera: close on the party (lead room ahead), pull back as the door scrolls in, lean toward the door on the
 * rumble, punch on the chain snap, then push into the opening doorway (the battle swirl takes over from there).
 */
function walkCam(t, P, L, T, leadX, doorX, W, H) {
  const tq = step(t, 15), Z = Math.max(1, P.zoom || 2);
  const party = [leadX - L.gap + (L.V ? 10 : 36), L.feet - (L.V ? 70 : 44)];
  const wide = [W / 2, H / 2], door = [doorX, L.floorY - (L.V ? 70 : 52)];
  const mid = [(party[0] + door[0]) / 2, (party[1] + door[1]) / 2];
  const r = ease.inOutCubic(seg(t, T.arrive - 1.2, T.arrive + 0.15));          // reveal
  const lean = ease.inOutCubic(seg(t, T.openAt - 0.15, T.openAt + 0.45));      // toward the door
  const dive = ease.inCubic(seg(t, T.doorT0, T.doorT1 + 0.5));                 // into the doorway
  let zoom = lerp(Z, 1, r);
  zoom = lerp(zoom, 1.25, lean);
  zoom = lerp(zoom, 2.25, dive);
  zoom += punch(tq, [T.chainsAt], 0.25, 0.3);
  let x = lerp(party[0], wide[0], r), y = lerp(party[1], wide[1], r);
  x = lerp(x, mid[0], lean); y = lerp(y, mid[1], lean);
  x = lerp(x, door[0], dive); y = lerp(y, door[1], dive);
  return { zoom: Math.round(zoom * 4) / 4, x, y };
}

function captionBox(ctx, S, text, L, t) {
  const sf = ctx.safe || {}, w = Math.min(L.V ? 220 : 300, S.w - 2 * Math.max(4, sf.l || 0) + 8), x = Math.round((S.w - w) / 2), y = Math.max(4, Math.round(sf.t || 0)) - 4;
  S.rect(x, y, w, 22, 'night'); S.frame(x, y, w, 22, 'ink'); S.frame(x + 1, y + 1, w - 2, 20, 'silver');
  const n = Math.floor(seg(t, 0.4, 0.4 + text.length / 30) * text.length);
  say(ctx, S, text, x + 10, y + 5, { font: 'mono', color: 'white', chars: n });
}

function cues(ctx, p) {
  const P = withDefaults(PARAMS, p), T = timeline(ctx, P), out = [];
  for (let k = 0, tt = 0.25; tt < T.arrive; k++, tt += 0.25) out.push(cue(tt, 'footstep', k & 1 ? -3 : 0));
  if (P.party?.length) out.push(cue(T.emote, 'emote'));
  if (P.open) { out.push(cue(T.openAt, 'door_rumble'), cue(T.chainsAt, 'chains'), cue(T.doorT0, 'door_open')); }
  return out;
}

export const dungeonWalk = {
  id: 'kit:pixel/dungeon-walk',
  def: {
    layer: '2d',
    describe: '16-bit party (knight, mage, rogue) walks a torch-lit dungeon to a sealed door marked LOCKED BOSS; chains snap and the door opens. Use res [480,270] (or [270,480]).',
    params: PARAMS,
    render,
    cues,
  },
};
