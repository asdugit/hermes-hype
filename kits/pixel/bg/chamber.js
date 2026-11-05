// chamber.js — the boss chamber: purple-tinted vault, braziers with big flames, carpet runner, lit by fire.
import { Sprite } from './../core/gfx.js';
import { REMAP } from './../core/palette.js';
import { flicker, step, rand } from './../core/motion.js';
import { wall, floor, DUNGEON_LEVELS } from './dungeon.js';

const BIGFLAME = [
  ['....w.....', '...wc.....', '...cgc..w.', '..cggc.wc.', '..cgacccg.', '.cgaaagga.', '.gaarAaaga', 'gaarrrAaag', 'aarrmrrAaa', '.arrmmrraa', '..rmmmmra.'],
  ['.....w....', '....cw....', '.w.cgc....', '.cwcggc...', '.gcccagc..', '.aggaaagc.', 'agaaArraag', 'gaaArrraag', 'aaArrmrraa', '.aarrmmra.', '..rmmmmra.'],
  ['...w......', '...cw...w.', '..cgc..c..', '..cggccg..', '.cgaccagc.', '.gaaaaagg.', 'gaArrAaaga', 'gaArrrrAag', 'aaArmmrraa', '.aarmmmraa', '..rmmmmra.'],
].map(r => Sprite.rows(r, { w: 'white', c: 'cream', g: 'gold', a: 'amber', A: 'coral', r: 'red', m: 'maroon' }));
const BOWL = Sprite.rows([
  'kkkkkkkkkkkkkk',
  'kgGGGGGGGGGGgk',
  'kdggggggggggdk',
  '.kdddddddddddk',
  '..kkdddddddkk.',
  '....kkdddkk...',
  '.....kdGdk....',
  '.....kdgdk....',
  '.....kdgdk....',
  '.....kdgdk....',
  '....kddgddk...',
  '...kkkkkkkkk..',
], { k: 'ink', g: 'grey', G: 'silver', d: 'greydk' });

/** Brazier (bowl on a stand + animated big flame); (x, y) = bowl top centre. */
export function brazier(S, x, y, t, seed = 0) {
  S.blit(BOWL, x - 7, y);
  const f = Math.floor(step(t, 12) * 12 + seed) % 3;
  S.blit(BIGFLAME[f], x - 5, y - 10);
  for (let i = 0; i < 3; i++) { // rising embers
    const ph = (t * 0.9 + rand(seed, i)) % 1, ex = x - 3 + Math.round(rand(seed, i, 1) * 6 + Math.sin((t + i) * 5) * 2);
    S.px(ex, Math.round(y - 12 - ph * 26), ph < 0.5 ? 'gold' : 'amber');
  }
}

/**
 * Boss chamber backdrop + lighting. o: {floorY, top, braziers: [[x, y]...] (bowl tops), extraLights, glow:{x,y,r}}
 * Draws walls/floor, lights them (fire + boss glow), then braziers on top.
 */
export function chamber(S, t, o = {}) {
  const floorY = o.floorY ?? 150, top = o.top ?? 0;
  wall(S, 37, { top, floorY, seed: 23, tint: REMAP.dusk });
  floor(S, 0, { floorY, seed: 9 });
  S.remap(REMAP.dusk, 0, floorY, S.w, S.h - floorY);
  // carpet runner toward the viewer (maroon with gold trim), widening in perspective
  const cx = o.carpetX ?? S.w / 2;
  for (let y = floorY; y < S.h; y++) {
    const u = (y - floorY) / (S.h - floorY), hw = Math.round(18 + u * 70), x0 = Math.round(cx - hw);
    S.rect(x0, y, hw * 2, 1, 'maroon'); S.px(x0, y, 'gold'); S.px(x0 + hw * 2 - 1, y, 'gold'); S.px(x0 + 2, y, 'amber'); S.px(x0 + hw * 2 - 3, y, 'amber');
    if ((y - floorY) % 9 === 0) S.rect(x0 + 4, y, hw * 2 - 8, 1, 'plumdk');
  }
  const lights = [];
  for (const [bx, by] of o.braziers || []) {
    const r = 74 + Math.round(flicker(t, bx) * 3) * 3;
    lights.push({ x: bx, y: by - 8, r, k: 1 }, { x: bx, y: floorY + 20, r: r * 1.1, sy: 0.4, k: 0.8 });
  }
  if (o.glow) lights.push({ x: o.glow.x, y: o.glow.y, r: o.glow.r, k: o.glow.k ?? 0.7 });
  for (const l of o.extraLights || []) lights.push(l);
  S.light(lights, DUNGEON_LEVELS, 0, 0, S.w, S.h);
  for (const [bx, by] of o.braziers || []) brazier(S, bx, by, t, bx);
}
