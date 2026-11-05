// heroes.js — the party: three ORIGINAL 16x24 heroes (knight, mage, rogue), hand-authored as string rows.
// Poses are composed from parts (head / torso / legs + weapon overlay) into 32x36 cels whose foot anchor
// is (16, 35), so weapons may swing outside the 16 px body. All frames face RIGHT; flip for left.
import { Sprite } from './../core/gfx.js';

const ANCHOR_X = 16, ANCHOR_Y = 35, CEL_W = 32, CEL_H = 36;
export const HERO_ANCHOR = { x: ANCHOR_X, y: ANCHOR_Y, w: CEL_W, h: CEL_H };

// ---- KNIGHT: round steel helm with a red crest, blue tabard with gold trim, round red shield, broadsword
const K = { k: 'ink', w: 'white', S: 'silver', G: 'grey', D: 'greydk', R: 'red', r: 'maroon', C: 'coral', s: 'peach', t: 'tan',
  B: 'blue', b: 'royal', N: 'navy', Y: 'gold', A: 'amber', h: 'brown', H: 'browndk', i: 'ice' };
const KNIGHT = {
  map: K,
  head: [
    '......kkk.......',
    '.....kCRRk......',
    '....kCRRrk......',
    '...kkkRrkkkkk...',
    '..kSSSkkSSSSSk..',
    '.kSwwSSSSSSSSSk.',
    '.kSwSSSSSSSSSGk.',
    '.kSSSSSDkkkkkGk.',
    '.kGSSSDsssssskk.',
    '.kGSSSDssksskk..',
    '.kGGSSDsssssk...',
    '..kkGGDkttkk....',
  ],
  torso: {
    idle: [
      '..kkSSkBBBBkk...',
      '.kSwSkBBYBBBSk..',
      'kRRRkkBBYBBbkSk.',
      'kRYRrkBBYBBbkSk.',
      'kRRRrkhhAhhhkGk.',
      '.krrkkNBYBBbk...',
    ],
    raise: [
      '..kkSSkBBBBkk...',
      '.kSwSkBBYBBBk...',
      'kRRRkkBBYBBbk...',
      'kRYRrkBBYBBbk...',
      'kRRRrkhhAhhhk...',
      '.krrkkNBYBBbk...',
    ],
    hurt: [
      '...kSSkBBBBkk...',
      '..kSwSkBBYBBk...',
      '.kRRRkBBYBBbkk..',
      '.kRYRkBBYBBbkSk.',
      '.kRRRkhhAhhhkGk.',
      '..krrkNBYBBbk...',
    ],
  },
  legs: {
    stand: ['....kNNkkbbk....', '....kNNk.kbk....', '....kSGk.kGSk...', '...kHhhk.khhHk..', '...kkkkk.kkkkk..'],
    a: ['....kNNkkbbk....', '...kNNk..kbbk...', '..kSGk....kSGk..', '.kHhhk....kHhhk.', '.kkkkk....kkkkk.'],
    b: ['....kNNkkbbk....', '.....kNkkbk.....', '.....kSGSGk.....', '....kHhkhhHk....', '....kkkkkkkk....'],
  },
  weapon: {
    // broadsword, hilt at the bottom; drawn with its grip point at (2, 13)
    up: ['..kk..', '.kwSk.', '.kwSk.', '.kwSk.', '.kwSk.', '.kwSk.', '.kwSk.', '.kwSk.', '.kwSk.', 'kkkkkk', 'kYAAYk', 'kkhhkk', '..kHk.', '..kk..'],
  },
  grip: { idle: [13, 15], raise: [11, 9], hurt: [13, 16], windup: [9, 4] },
};

// ---- MAGE: tall violet hat with a crooked tip and gold band, rose braid, teal robe, staff with a teal orb
const M = { k: 'ink', w: 'white', v: 'violet', V: 'plum', p: 'plumdk', l: 'lilac', Y: 'gold', A: 'amber', o: 'rose', O: 'lilac',
  s: 'peach', t: 'tan', T: 'teal', d: 'tealdk', i: 'ice', h: 'brown', H: 'browndk', c: 'cream', n: 'night' };
const MAGE = {
  map: M,
  head: [
    '..........kk....',
    '.........kvk....',
    '........kvVk....',
    '.......kvvVk....',
    '......kvlvVk....',
    '.....kvlvvVVk...',
    '...kkkYYYYYYkkk.',
    '..kVvvvvvvvvvVk.',
    '...kkookkkkkkk..',
    '...kooksssskk...',
    '...kookssksk....',
    '..kooOkssssk....',
  ],
  torso: {
    idle: [
      '..koOkkTTTTkk...',
      '..kOkTTiTTTTTk..',
      '...kTTTiTTTddk..',
      '...kTTTiTTsTdk..',
      '...kdTTYTTskdk..',
      '..kdTTTiTTTTdk..',
    ],
    raise: [
      '..koOkkTTTTkksk.',
      '..kOkTTiTTTkksk.',
      '...kTTTiTTTddk..',
      '...kTTTiTTTTdk..',
      '...kdTTYTTTTdk..',
      '..kdTTTiTTTTdk..',
    ],
    hurt: [
      '...koOkTTTTkk...',
      '...kOkTTiTTTTk..',
      '...kTTTiTTTddk..',
      '...kTTTiTTsTdk..',
      '...kdTTYTTskdk..',
      '..kdTTTiTTTTdk..',
    ],
  },
  legs: {
    stand: ['..kdTTTiTTTTdk..', '.kdTTTTiTTTTTdk.', '.kddddddddddddk.', '..kkkhhkkhhkkk..', '...khhHk.khhHk..', '...kkkkk.kkkkk..'],
    a: ['..kdTTTiTTTTdk..', '.kdTTTTiTTTTTdk.', '.kdddddddddddddk', '.kkhhkkkkkhhHkk.', '.khhHk....khhHk.', '.kkkkk....kkkkk.'],
    b: ['..kdTTTiTTTTdk..', '..kdTTTiTTTTdk..', '..kddddddddddk..', '...kkkhhhhkkk...', '....khhHkhhk....', '....kkkkkkkk....'],
  },
  weapon: {
    // staff: teal orb in a gold claw on a long brown shaft, grip at (2, 13)
    up: ['.kkk.', 'kTiTk', 'kdTTk', 'kYdYk', '.kYk.', '.khk.', '.khk.', '.khk.', '.khk.', '.khk.', '.khk.', '.khk.', '.khk.', '.khk.', '.khk.', '.khk.', '.khk.', '.kHk.', '.kk..'],
  },
  grip: { idle: [13, 14], raise: [13, 9], hurt: [13, 15], windup: [12, 7] },
};

// ---- ROGUE: forest-green hood with a peak, amber scarf trailing behind, leather vest, twin daggers
const R = { k: 'ink', w: 'white', f: 'forestdk', F: 'forest', g: 'green', L: 'lime', a: 'amber', A: 'gold', c: 'coral', s: 'peach', t: 'tan',
  h: 'brown', H: 'browndk', S: 'silver', G: 'grey', D: 'greydk', n: 'night', N: 'navy' };
const ROGUE = {
  map: R,
  head: [
    '................',
    '................',
    '.......kkkk.....',
    '.....kkFgggk....',
    '....kFFgLggFk...',
    '...kFFgggggFk...',
    '...kFFgFFFFFk...',
    '..kfFFkHHHHHHk..',
    '..kfFkHssssssk..',
    '..kfFkskssksk...',
    '..kfFkfFFFFFk...',
    '..kaaaAAAaaak...',
  ],
  torso: {
    idle: [
      '.kaakkhhhhkk....',
      'kaak.khthhhkk...',
      'kak.kHhhhhtksk..',
      '.k..kHhAhhhkkk..',
      '....kfFFFFFk....',
      '....kfFFFFFk....',
    ],
    raise: [
      '.kaakkhhhhkk.k..',
      'kaak.khthhhkskk.',
      'kak.kHhhhhhkkk..',
      '.k..kHhAhhhk....',
      '....kfFFFFFk....',
      '....kfFFFFFk....',
    ],
    hurt: [
      '..kaakkhhhhkk...',
      '.kaak.khthhhkk..',
      '.kak.kHhhhhtksk.',
      '..k..kHhAhhhkkk.',
      '.....kfFFFFFk...',
      '.....kfFFFFFk...',
    ],
  },
  legs: {
    stand: ['....kNNkkNNk....', '....kNNk.kNk....', '....knNk.kNk....', '...kHhhk.khHk...', '...kkkkk.kkkk...'],
    a: ['....kNNkkNNk....', '...kNNk..kNNk...', '..knNk....kNnk..', '.kHhhk....kHhhk.', '.kkkkk....kkkkk.'],
    b: ['....kNNkkNNk....', '.....kNkkNk.....', '.....knNNnk.....', '....kHhkhhHk....', '....kkkkkkkk....'],
  },
  weapon: {
    // dagger, grip at (1, 6)
    up: ['.k.', 'kwk', 'kSk', 'kSk', 'kkk', 'kAk', 'khk', '.k.'],
  },
  grip: { idle: [12, 15], raise: [12, 9], hurt: [13, 16], windup: [11, 6] },
};

export const HEROES = { knight: KNIGHT, mage: MAGE, rogue: ROGUE };
export const HERO_IDS = Object.keys(HEROES);

/**
 * Compose one cel. opts: {torso='idle', legs='stand', bob=0 (px, negative = up), lean=0 (px x-shift of upper body),
 * weapon='up'|null, weaponAt=[x,y] override (body coords), weaponRot=0..3 (quarter turns), weaponFlip}
 */
function compose(H, o) {
  const cel = new Sprite(CEL_W, CEL_H), bx = ANCHOR_X - 8;
  const head = Sprite.rows(H.head, H.map), torso = Sprite.rows(H.torso[o.torso || 'idle'], H.map), legs = Sprite.rows(H.legs[o.legs || 'stand'], H.map);
  const up = o.bob || 0, lean = o.lean || 0;
  // stack bottom-up: soles on the anchor row, torso on the legs, head on the torso
  const ly = ANCHOR_Y - legs.h + 1, ty = ly - torso.h, by = ty - head.h;
  cel.paste(legs, bx, ly);
  // a raised upper body stretches the hips instead of leaving a gap row
  for (let g = 1; g <= -up; g++) cel.paste(Sprite.rows([H.legs[o.legs || 'stand'][0]], H.map), bx, ly - g);
  cel.paste(torso, bx + lean, ty + up);
  cel.paste(head, bx + lean, by + up);
  if (o.weapon !== null && H.weapon) {
    let w = Sprite.rows(H.weapon[o.weapon || 'up'], H.map);
    let gx = 2, gy = w.h - 1 - 1;
    for (let r = 0; r < (o.weaponRot || 0); r++) { const nx = w.h - 1 - gy, ny = gx; w = w.rot90(); gx = nx; gy = ny; }
    if (o.weaponFlip) { w = w.flipX(); gx = w.w - 1 - gx; }
    const [px, py] = o.weaponAt || H.grip[o.torso || 'idle'] || [13, 15];
    const back = o.weaponBehind;
    if (back) { const c2 = new Sprite(CEL_W, CEL_H); c2.paste(w, bx + lean + px - gx, by + up + py - gy); c2.paste(cel, 0, 0); return c2; }
    cel.paste(w, bx + lean + px - gx, by + up + py - gy);
  }
  return cel;
}

const CACHE = new Map();
/**
 * All animation cels of a hero, facing right, cached. Keys:
 * idle0/idle1 (breathing), walk0..3, ready, windup, strike, hurt, win0/win1, cast0/cast1.
 */
export function heroFrames(id) {
  if (CACHE.has(id)) return CACHE.get(id);
  const H = HEROES[id]; if (!H) throw new Error(`pixel kit: unknown hero "${id}" (have ${HERO_IDS.join(', ')})`);
  const F = {
    idle0: compose(H, {}),
    idle1: compose(H, { bob: 1 }),
    walk0: compose(H, { legs: 'a' }),
    walk1: compose(H, { legs: 'b', bob: -1 }),
    walk2: compose(H, { legs: 'a', bob: 0 }),
    walk3: compose(H, { legs: 'b', bob: -1 }),
    ready: compose(H, { legs: 'a', bob: 1, lean: -1 }),
    windup: compose(H, { torso: 'raise', legs: 'a', lean: -1, bob: 1, weaponAt: H.grip.windup || [11, 5], weaponBehind: true }),
    strike: compose(H, { torso: 'idle', legs: 'a', lean: 2, bob: 1, weaponRot: 1, weaponAt: [14, 14] }),
    hurt: compose(H, { torso: 'hurt', legs: 'stand', lean: -2, bob: 1 }),
    win0: compose(H, { torso: 'raise', legs: 'stand' }),
    win1: compose(H, { torso: 'raise', legs: 'stand', bob: -2 }),
    cast0: compose(H, { torso: 'raise', legs: 'stand', bob: 0 }),
    cast1: compose(H, { torso: 'raise', legs: 'stand', bob: -1 }),
  };
  // walk2 mirrors the stride (swap legs) for a 4-beat cycle
  F.walk2 = mirrorLegs(F.walk2, H.legs.a.length);
  CACHE.set(id, F);
  return F;
}
function mirrorLegs(cel, n) {
  // flip only the leg rows (bottom n rows ending on the anchor) around the body centre column
  const o = cel.clone(), y0 = ANCHOR_Y - n + 1, cx = ANCHOR_X - 8;
  for (let y = y0; y <= ANCHOR_Y; y++) for (let x = 0; x < 16; x++) o.d[y * o.w + cx + x] = cel.d[y * cel.w + cx + 15 - x];
  return o;
}

/** Walk cycle cel for time t (4 beats at `fps` steps/second). */
export function walkCel(id, t, fps = 8) { const F = heroFrames(id); return F['walk' + (Math.floor(t * fps) & 3)]; }
/** Idle breathing cel (slow 2-frame). */
export function idleCel(id, t, phase = 0) { const F = heroFrames(id); return F[((Math.floor(t * 2 + phase) & 1) ? 'idle1' : 'idle0')]; }
