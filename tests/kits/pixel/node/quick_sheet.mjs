// quick_sheet.mjs — dev harness: render every kit:pixel Quick type with synthetic data (both aspects) into one
// contact sheet per aspect + report ms/frame and QA box counts. Also the source of tests' synthetic data.
// usage: node tests/kits/pixel/node/quick_sheet.mjs [outdir] [t]
import { mkdirSync, writeFileSync } from 'node:fs';
import { QUICK } from '../../../../kits/pixel/scenes/quick.js';
import { encodePNG } from './png.mjs';
import { makeCtx } from './fakectx.mjs';

export const DATA = {
  HOOK: { label: 'Meet Red Car', image: 'car' },
  TITLE: { title: 'Red Car', tagline: 'The road is yours.' },
  PROBLEM: { text: 'Make me a launch page for my red car that shows it driving, with a buy button that works on phones.' },
  PLAN: { items: [{ text: 'Scaffold the page', status: 'done' }, { text: 'Hero video loop', status: 'done' }, { text: 'Buy button + checkout', status: 'in_progress' }, { text: 'Mobile pass', status: 'pending' }] },
  CODE: { path: 'src/buy.ts', lang: 'ts', start: 12, focus: [14, 16], lines: ['export async function buy(id: string) {', '  const cart = await getCart();', '  cart.add(id, 1);', '  const url = await checkout(cart);', '  window.location.assign(url);', '}', '', 'export const price = 24999;'] },
  DIFF: { path: 'src/buy.ts', adds: 3, dels: 1, hunks: [{ header: '@@ -12,4 +12,6 @@', lines: [[' ', 'export async function buy(id) {'], ['-', '  alert("soon");'], ['+', '  const cart = await getCart();'], ['+', '  cart.add(id, 1);'], ['+', '  location.assign(await checkout(cart));'], [' ', '}']] }] },
  TERMINAL: { cmd: 'npm test', output: ['> red-car@1.0.0 test', '> vitest run', ' PASS  buy.test.ts (3 tests)', ' PASS  page.test.ts (5 tests)', 'Tests  8 passed (8)'], exit_code: 0, ok: true },
  MONTAGE: { items: [{ tool: 'write', kind: 'write', arg: 'index.html' }, { tool: 'edit', kind: 'edit', arg: 'buy.ts' }, { tool: 'terminal', kind: 'terminal', arg: 'npm test' }, { tool: 'read', kind: 'read', arg: 'README' }, { tool: 'browser', kind: 'browser', arg: 'localhost' }, { tool: 'search', kind: 'search', arg: 'checkout' }] },
  SCREEN: { bbox: [0.2, 0.3, 0.5, 0.4] },
  STATS: { stats: [{ label: 'Files', value: 14, display: '14' }, { label: 'Tests', value: 8, display: '8' }, { label: 'Minutes', value: 42, display: '42' }] },
  BEFORE_AFTER: { before: { kind: 'terminal', cmd: 'npm test', output: ['FAIL buy.test.ts', '1 failed'] }, after: { kind: 'terminal', cmd: 'npm test', output: ['PASS buy.test.ts', '8 passed'] } },
  CALLOUT: { text: 'It finally works on my phone. Buying it now.', who: 'the user' },
  END: { title: 'Red Car', cta: 'npm create red-car', url: 'redcar.example', credit: 'Made with Hermes' },
  FEATURE: { feature: 'One tap to buy, even on a phone.', bbox: [0.55, 0.6, 0.3, 0.2], click: [0.7, 0.7] },
  SCROLL: { scroll: [0, 1] },
};

const out = process.argv[2] || 'C:/Users/2/AppData/Local/hermes/cache/scratch/k1';
const T = Number(process.argv[3] || 2.6);
if (import.meta.url.endsWith(process.argv[1].replace(/\\/g, '/').split('/').pop())) {
  mkdirSync(out, { recursive: true });
  for (const [w, h] of [[480, 270], [270, 480]]) {
    const cols = w > h ? 4 : 6, rows = Math.ceil(QUICK.length / cols), pad = 4;
    const SW = cols * (w + pad) + pad, SH = rows * (h + pad) + pad, sheet = new Uint8Array(SW * SH * 4).fill(30);
    QUICK.forEach((sc, k) => {
      const type = sc.id.split('/')[1], params = { data: DATA[type], image: ['HOOK', 'SCREEN', 'FEATURE', 'SCROLL'].includes(type) ? 'car' : null, media: type === 'TITLE' ? 'car' : null };
      const ctx = makeCtx(w, h, 5, params);
      const t0 = process.hrtime.bigint(); sc.def.render(ctx, T, params); const ms = Number(process.hrtime.bigint() - t0) / 1e6;
      const d = ctx.g.last.data, ox = pad + (k % cols) * (w + pad), oy = pad + Math.floor(k / cols) * (h + pad);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const s = (y * w + x) * 4, o = ((oy + y) * SW + ox + x) * 4; sheet[o] = d[s]; sheet[o + 1] = d[s + 1]; sheet[o + 2] = d[s + 2]; sheet[o + 3] = 255; }
      console.log(`${type.padEnd(13)} ${w}x${h} ${ms.toFixed(1)} ms qa=${ctx.qaBoxes.length} cues=${sc.def.cues ? sc.def.cues(ctx, params).length : 0}`);
    });
    writeFileSync(`${out}/quick_${w}x${h}${process.env.TAG ? '_' + process.env.TAG : ''}.png`, encodePNG(SW, SH, sheet));
  }
}
