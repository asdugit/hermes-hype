// sheet.mjs — dev harness: render sprite sheets of the pixel kit's art to PNG for visual review.
// usage: node tests/kits/pixel/node/sheet.mjs <out_dir>
import { mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Screen } from '../../../../kits/pixel/core/gfx.js';
import { drawText } from '../../../../kits/pixel/core/text.js';
import { heroFrames, HERO_IDS } from '../../../../kits/pixel/art/heroes.js';
import { writeScreen } from './png.mjs';

const out = process.argv[2] || join(tmpdir(), 'auteur-k1');
mkdirSync(out, { recursive: true });

export function heroSheet() {
  const keys = Object.keys(heroFrames('knight'));
  const S = new Screen(keys.length * 34 + 4, HERO_IDS.length * 44 + 14).fill('navy');
  keys.forEach((k, i) => drawText(S, k.slice(0, 5), 4 + i * 34, 1, { font: 'tiny', color: 'ice' }));
  HERO_IDS.forEach((id, r) => {
    const F = heroFrames(id);
    keys.forEach((k, i) => { S.rect(2 + i * 34, 12 + r * 44, 32, 36, 'royal'); S.blit(F[k], 2 + i * 34, 12 + r * 44); });
  });
  return S;
}
writeScreen(`${out}/heroes.png`, heroSheet(), 6);
console.log('wrote', out);
