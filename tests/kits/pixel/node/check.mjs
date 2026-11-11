// check.mjs — machine checks for the pixel kit (driven by tests/kits/pixel/test_pixel_kit.py):
// every scene x aspect x time renders without throwing, uses ONLY palette colours (alpha 255), is a pure function
// of t (same pixels when re-rendered after other times), keeps registered text inside the safe area, and emits cues
// whose SFX names exist. Prints one JSON object.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { SCENES } from '../../../../kits/pixel/scenes/index.js';
import { RGB } from '../../../../kits/pixel/core/palette.js';
import { schedule } from '../../../../kits/pixel/scenes/boss-battle.js';
import { makeCtx } from './fakectx.mjs';
import { DATA } from './quick_sheet.mjs';

const sfx = JSON.parse(readFileSync(new URL('../../../../assets/audio/sfx/sfx.json', import.meta.url), 'utf8'));
const SOUNDS = new Set(Object.keys(sfx.sounds));
const PAL = new Set(RGB.map(([r, g, b]) => (r << 16) | (g << 8) | b));
const PARAMS = {
  'kit:pixel/boss-battle': { boss_media: 'car', boss_name: 'RED CAR' },
  'kit:pixel/title-screen': { title: 'RED CAR', tagline: 'The road is yours.', media: 'car', footer: '(C) 2026 TEST' },
  'kit:pixel/item-get': { media: 'car', name: 'RED CAR', desc: 'Zero to sixty before the boss blinks.' },
  'kit:pixel/shop': { media: 'car', name: 'RED CAR', price: '24,999 G' },
};
const DUR = 6;
const results = { scenes: 0, frames: 0, errors: [], offPalette: [], nondeterministic: [], unsafeText: [], badCues: [], ms: {} };
const hash = (d) => createHash('sha1').update(d).digest('hex');

for (const sc of SCENES) {
  const type = sc.id.split('/')[1];
  const params = PARAMS[sc.id] || (DATA[type] ? { data: DATA[type], image: ['HOOK', 'SCREEN', 'FEATURE', 'SCROLL'].includes(type) ? 'car' : null } : {});
  results.scenes++;
  for (const [w, h] of [[480, 270], [270, 480]]) {
    const ctx = makeCtx(w, h, DUR, params), times = [-0.2, 0.1, 1.0, 2.5, DUR - 0.3, DUR + 0.2], hashes = {};
    let total = 0;
    for (const t of times) {
      ctx.qaBoxes.length = 0;
      try {
        const t0 = process.hrtime.bigint(); sc.def.render(ctx, t, params); total += Number(process.hrtime.bigint() - t0) / 1e6;
      } catch (e) { results.errors.push(`${sc.id} ${w}x${h} t=${t}: ${e.stack || e}`); continue; }
      results.frames++;
      const d = ctx.g.last.data; hashes[t] = hash(d);
      let off = 0; for (let i = 0; i < d.length; i += 4) if (d[i + 3] !== 255 || !PAL.has((d[i] << 16) | (d[i + 1] << 8) | d[i + 2])) off++;
      if (off) results.offPalette.push(`${sc.id} ${w}x${h} t=${t}: ${off} px`);
      if (t >= 0.5 && t <= DUR) for (const b of ctx.qaBoxes) {
        const s = ctx.safe;
        if (b.x < s.l - 2 || b.y < s.t - 2 || b.x + b.w > w - s.r + 2 || b.y + b.h > h - s.b + 2) results.unsafeText.push(`${sc.id} ${w}x${h} t=${t}: "${b.text}" [${b.x},${b.y},${b.w},${b.h}]`);
      }
    }
    // purity: re-render in a different order and compare
    for (const t of [2.5, 0.1, DUR - 0.3]) { sc.def.render(ctx, t, params); if (hash(ctx.g.last.data) !== hashes[t]) results.nondeterministic.push(`${sc.id} ${w}x${h} t=${t}`); }
    results.ms[`${sc.id} ${w}x${h}`] = +(total / times.length).toFixed(1);
    if (sc.def.cues) for (const c of sc.def.cues(ctx, params) || []) if (!SOUNDS.has(c.sfx) || !(c.t >= 0 && c.t <= DUR + 1)) results.badCues.push(`${sc.id}: ${JSON.stringify(c)}`);
  }
}
// boss-battle schedule invariants
const B = schedule(13, { attacks: [{ by: 'boss', kind: 'blade', dmg: [48, 52, 61] }], menu: ['FIGHT', 'ITEM', 'BUY', 'RUN'], pick: 'BUY', party: ['knight', 'mage', 'rogue'], timings: {} });
results.schedule = { click: B.click, menuT: B.menuT, moves: B.moves, hits: B.hits.map(h => h.t), pickIdx: B.pickIdx };
// frame 0 of a Quick film is its thumbnail: the HOOK opens lit (a real E2E film opened at mean luma 10)
const lumaOf = (d) => { let s = 0; for (let i = 0; i < d.length; i += 4) s += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]; return s / (d.length / 4); };
results.hookLuma = {};
const hookScene = SCENES.find(s => s.id === 'kit:pixel/HOOK');
for (const [w, h] of [[480, 270], [270, 480]]) {
  const params = { data: DATA.HOOK, image: 'car' }, ctx = makeCtx(w, h, DUR, params);
  hookScene.def.render(ctx, 0, params);
  results.hookLuma[`${w}x${h}`] = +lumaOf(ctx.g.last.data).toFixed(1);
}
// Quick TITLE with captions up: PRESS START blinks above the caption band (it sat on the caption line in 9:16)
results.titlePress = {};
const titleScene = SCENES.find(s => s.id === 'kit:pixel/TITLE');
for (const [w, h] of [[480, 270], [270, 480]]) {
  const params = { data: DATA.TITLE, media: 'car', _captions: true }, ctx = makeCtx(w, h, DUR, params);
  let box = null;
  for (const t of [1.65, 1.7, 1.8, 2.0, 2.4, 2.6]) { ctx.qaBoxes.length = 0; titleScene.def.render(ctx, t, params); box = ctx.qaBoxes.find(b => /PRESS START/.test(b.text)) || box; }
  results.titlePress[`${w}x${h}`] = box ? { y1: box.y + box.h, h } : null;
}
console.log(JSON.stringify(results));
