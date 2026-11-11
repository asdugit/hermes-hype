// scene.mjs — dev harness: render a pixel-kit scene at given times in Node (no browser) to PNGs + a
// contact sheet. The kit draws into an index buffer, so the fake 2D context only needs ImageData I/O.
// usage: node tests/kits/pixel/node/scene.mjs <scene-file> <export> <w>x<h> <dur> <t1,t2,...> [params.json|-] [outdir] [scale]
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { encodePNG } from './png.mjs';
import { makeCtx } from './fakectx.mjs';

const [file, exp, size, dur, times, pjson, outdir = join(tmpdir(), 'auteur-k1'), scaleArg = '2'] = process.argv.slice(2);
const [w, h] = size.split('x').map(Number), scale = Number(scaleArg);
const mod = await import(pathToFileURL(resolve(file)).href);
const scene = mod[exp];
const params = pjson && pjson !== '-' ? JSON.parse(readFileSync(pjson, 'utf8')) : {};
mkdirSync(outdir, { recursive: true });
const ctx = makeCtx(w, h, Number(dur), params);
if (scene.def.setup) await scene.def.setup(ctx, params);
const ts = times.split(',').map(Number);
const imgs = [];
const t0 = process.hrtime.bigint();
for (const t of ts) { scene.def.render(ctx, t, params); imgs.push(ctx.g.last.data.slice()); }
const ms = Number(process.hrtime.bigint() - t0) / 1e6;
// contact sheet: up to 4 columns, each frame upscaled by `scale`
const cols = Math.min(4, ts.length), rows = Math.ceil(ts.length / cols), W = w * scale, H = h * scale, pad = 4;
const SW = cols * (W + pad) + pad, SH = rows * (H + pad) + pad, sheet = new Uint8Array(SW * SH * 4).fill(40);
imgs.forEach((d, k) => {
  const ox = pad + (k % cols) * (W + pad), oy = pad + Math.floor(k / cols) * (H + pad);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const s = (((y / scale) | 0) * w + ((x / scale) | 0)) * 4, o = ((oy + y) * SW + ox + x) * 4;
    sheet[o] = d[s]; sheet[o + 1] = d[s + 1]; sheet[o + 2] = d[s + 2]; sheet[o + 3] = 255;
  }
});
const name = `${exp}_${w}x${h}${process.env.TAG ? '_' + process.env.TAG : ''}`;
if (process.env.FRAMES) imgs.forEach((d, k) => { const fw = w * scale, fh = h * scale, o = new Uint8Array(fw * fh * 4); for (let y = 0; y < fh; y++) for (let x = 0; x < fw; x++) { const s = (((y / scale) | 0) * w + ((x / scale) | 0)) * 4, q = (y * fw + x) * 4; o[q] = d[s]; o[q + 1] = d[s + 1]; o[q + 2] = d[s + 2]; o[q + 3] = 255; } writeFileSync(`${outdir}/${name}_f${k}.png`, encodePNG(fw, fh, o)); });
writeFileSync(`${outdir}/${name}.png`, encodePNG(SW, SH, sheet));
if (scene.def.cues) writeFileSync(`${outdir}/${name}.cues.json`, JSON.stringify(scene.def.cues(ctx, params), null, 1));
console.log(`${name}: ${ts.length} frames, ${(ms / ts.length).toFixed(1)} ms/frame, qa boxes=${ctx.qaBoxes.length}, errors=${ctx.errors.length}`);
console.log(`${outdir}/${name}.png`);
