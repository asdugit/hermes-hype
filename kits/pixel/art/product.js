// product.js — turn ANY product image/video frame into palette-locked pixel art, and frame it as a boss.
// productSprite: frame at time t -> area-downsampled -> contrast/saturation "pop" -> ordered-dither quantise
// to the kit palette (or a sub-palette) -> Sprite. Cached per (asset, frame, size, options).
import { Sprite } from './../core/gfx.js';
import { quantize, REMAP } from './../core/palette.js';
import { drawText, measure } from './../core/text.js';
import { bar } from './../ui/ui.js';

const CACHE = new Map();
const CACHE_MAX = 96;

/** Pixels (RGBA) of a frame source at w x h with cover/contain fit. Works for ImageBitmap/Image/Canvas and {data,width,height}. */
function pixelsOf(src, w, h, fit) {
  let crop = null;
  if (src && src.__crop) { crop = src.__crop; src = src.src; }
  const fw = src.width || src.naturalWidth, fh = src.height || src.naturalHeight;
  const ox = crop ? crop[0] * fw : 0, oy = crop ? crop[1] * fh : 0, sw = crop ? crop[2] * fw : fw, sh = crop ? crop[3] * fh : fh;
  const sc = fit === 'contain' ? Math.min(w / sw, h / sh) : Math.max(w / sw, h / sh);
  const dw = sw * sc, dh = sh * sc, dx = (w - dw) / 2, dy = (h - dh) / 2;
  if (src.data && !(typeof ImageBitmap !== 'undefined' && src instanceof ImageBitmap)) {
    // box-filter resample (Node dev harness / ImageData input)
    const out = new Uint8ClampedArray(w * h * 4);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const x0 = (x - dx) / sc, x1 = (x + 1 - dx) / sc, y0 = (y - dy) / sc, y1 = (y + 1 - dy) / sc;
      let r = 0, g = 0, b = 0, a = 0, n = 0;
      for (let sy = Math.max(0, Math.floor(y0)); sy < Math.min(sh, Math.ceil(y1)); sy++)
        for (let sx = Math.max(0, Math.floor(x0)); sx < Math.min(sw, Math.ceil(x1)); sx++) {
          const p = ((Math.floor(oy) + sy) * fw + Math.floor(ox) + sx) * 4; r += src.data[p]; g += src.data[p + 1]; b += src.data[p + 2]; a += src.data[p + 3]; n++;
        }
      const q = (y * w + x) * 4; if (n) { out[q] = r / n; out[q + 1] = g / n; out[q + 2] = b / n; out[q + 3] = a / n; }
    }
    return out;
  }
  const oc = new OffscreenCanvas(w, h), g = oc.getContext('2d', { willReadFrequently: true });
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  if (crop) g.drawImage(src, ox, oy, sw, sh, dx, dy, dw, dh); else g.drawImage(src, dx, dy, dw, dh);
  return g.getImageData(0, 0, w, h).data;
}

/** Contrast/saturation boost so small quantised art reads (pop 0..1). */
function pop(px, amount) {
  if (!amount) return px;
  const c = 1 + amount * 0.35, s = 1 + amount * 0.6;
  for (let i = 0; i < px.length; i += 4) {
    let r = px[i], g = px[i + 1], b = px[i + 2];
    const l = 0.299 * r + 0.587 * g + 0.114 * b;
    r = l + (r - l) * s; g = l + (g - l) * s; b = l + (b - l) * s;
    px[i] = (r - 128) * c + 128; px[i + 1] = (g - 128) * c + 128; px[i + 2] = (b - 128) * c + 128;
  }
  return px;
}

/**
 * Product media -> pixel sprite at time t.
 * @param ctx   SDK ctx (unused except for asset resolution by name)
 * @param asset asset handle from ctx.asset(name) (or {frame(t)} / an image-like with width/height)
 * @param o     {w, h, t=0, palette=null (sub-palette tokens), dither=28, pop=0.5, fit='cover'|'contain', loop=true, outline=null}
 * @returns {Sprite|null}
 */
export function productSprite(ctx, asset, o = {}) {
  if (!asset) return null;
  const w = o.w | 0 || 96, h = o.h | 0 || 64, t = o.t || 0;
  const fps = asset.fps || 30, fi = asset.frame ? Math.floor(t * fps + 1e-6) : 0;
  const key = `${asset.name || asset.src || ''}|${asset.w}x${asset.h}|${fi}|${w}x${h}|${(o.palette || []).join(',')}|${o.dither ?? 28}|${o.pop ?? 0.5}|${o.fit || 'cover'}`;
  let s = CACHE.get(key);
  if (s) return s;
  let src = asset.frame ? asset.frame(t, { loop: o.loop !== false }) : asset;
  if (!src && asset.image) src = asset.image;
  if (!src) return null;
  const px = pop(new Uint8ClampedArray(pixelsOf(src, w, h, o.fit || 'cover')), o.pop ?? 0.5);
  s = new Sprite(w, h, quantize(px, w, h, { palette: o.palette || null, dither: o.dither ?? 28 }));
  if (o.outline) s = s.outlined(o.outline);
  CACHE.set(key, s);
  if (CACHE.size > CACHE_MAX) CACHE.delete(CACHE.keys().next().value);
  return s;
}

const HORN = Sprite.rows([
  '.kk.................',
  'kwck................',
  'kcck................',
  'kccpk...............',
  'kcppk...............',
  '.kcppk..............',
  '.kcpptk.............',
  '.kkcpptk............',
  '..kcpptk............',
  '..kkcpptk...........',
  '...kcpppttk.........',
  '...kkcpppttk........',
  '....kcppppttkk......',
  '.....kkcpppptttk....',
  '......kkccpppptttkk.',
  '........kkccppppttbk',
  '..........kkcccpptbk',
  '............kkkkkkk.',
], { k: 'ink', w: 'white', c: 'cream', p: 'peach', t: 'tan', b: 'brown' });
const HORN_R = HORN.flipX();

/**
 * Boss-lair backdrop inside a picture rect: dark ember gradient, slowly turning stepped light rays, a glowing
 * floor disc and drifting embers — the stage for a product cutout.
 */
export function lair(S, x, y, w, h, t = 0) {
  S.clip(x, y, w, h);
  S.vbands(x, y, w, h, ['ink', 'plumdk', 'plum', 'maroon'], 4);
  const cx = x + w / 2, cy = y + h * 0.62, rot = Math.floor(t * 6) / 6 * 0.25;
  for (let k = 0; k < 8; k++) {                       // rays: 8 wedges, every other one lit
    if (k & 1) continue;
    const a0 = rot + k * Math.PI / 4, a1 = a0 + Math.PI / 9, R = Math.max(w, h);
    S.poly([[cx, cy], [cx + Math.cos(a0) * R, cy + Math.sin(a0) * R], [cx + Math.cos(a1) * R, cy + Math.sin(a1) * R]], 'maroon');
  }
  S.glow(cx, cy, w * 0.55, REMAP.ember, 1.1, 0.7);
  S.ellipse(cx, y + h * 0.86, w * 0.36, h * 0.07, 'ink', 0.8);
  S.ellipse(cx, y + h * 0.86, w * 0.30, h * 0.05, 'maroon', 0.6);
  for (let i = 0; i < 10; i++) {                      // embers rising
    const ph = (t * 0.35 + i * 0.137) % 1, ex = x + ((i * 53 + 17) % w), ey = y + h - ph * h;
    S.px(ex + Math.round(Math.sin(t * 3 + i) * 2), ey, ph < 0.5 ? 'gold' : 'amber');
  }
  S.unclip();
}

/**
 * Draw the product as a framed BOSS portrait: gold frame with horns + crest gem, ember aura, name plate and
 * HP bar. (x, y) = top-left of the picture area (pw x ph). Returns layout rects {pic, plate, bar, outer}.
 * o: {name, level, hp (0..1), hpLag, t, aura (0..1), gold (0..1 golden shimmer), horns (bool), lair (draw the lair backdrop), remap, say}
 */
export function bossFrame(S, sprite, x, y, pw, ph, o = {}) {
  const t = o.t || 0, fx = x - 6, fy = y - 6, fw = pw + 12, fh = ph + 12;
  // ember aura behind the frame (pulses on twos)
  const pulse = (Math.floor(t * 4) & 1) ? 2 : 0, aura = o.aura ?? 1;
  if (aura > 0) S.glow(x + pw / 2, y + ph / 2, Math.max(pw, ph) * 0.75 + pulse, REMAP.ember, 0.9 * aura, ph / pw + 0.25);
  // bone horns curling up and out from the sides of the frame (clear of the message window above)
  if (o.horns !== false) { S.blit(HORN, fx - 14, fy + 1); S.blit(HORN_R, fx + fw - HORN.w + 14, fy + 1); }
  // frame: ink, gold bevel (cream highlight top-left, amber/brown shadow bottom-right)
  S.rect(fx, fy, fw, fh, 'ink');
  S.rect(fx + 1, fy + 1, fw - 2, fh - 2, 'gold');
  S.rect(fx + 1, fy + 1, fw - 2, 1, 'cream'); S.rect(fx + 1, fy + 1, 1, fh - 2, 'cream');
  S.rect(fx + 1, fy + fh - 2, fw - 2, 1, 'brown'); S.rect(fx + fw - 2, fy + 1, 1, fh - 2, 'brown');
  S.rect(fx + 3, fy + 3, fw - 6, fh - 6, 'amber'); S.rect(fx + 4, fy + 4, fw - 8, fh - 8, 'brown');
  for (let i = fx + 8; i < fx + fw - 8; i += 6) { S.px(i, fy + 2, 'amber'); S.px(i, fy + fh - 3, 'gold'); }
  // corner studs
  for (const [cx, cy] of [[fx + 2, fy + 2], [fx + fw - 5, fy + 2], [fx + 2, fy + fh - 5], [fx + fw - 5, fy + fh - 5]]) { S.rect(cx, cy, 3, 3, 'red'); S.px(cx, cy, 'coral'); S.frame(cx - 1, cy - 1, 5, 5, 'ink'); }
  // picture (over a "lair" backdrop when the product is a cutout)
  S.rect(x - 1, y - 1, pw + 2, ph + 2, 'ink');
  if (o.lair || !sprite) lair(S, x, y, pw, ph, t);
  if (sprite) S.blit(sprite, x + Math.round((pw - sprite.w) / 2), y + Math.round((ph - sprite.h) / 2) + (o.lair ? Math.round(ph * 0.04) : 0), o.remap ? { remap: o.remap } : {});
  if (o.gold > 0) S.remap(REMAP.gold, x, y, pw, ph, o.gold);
  // crest: a red gem in a gold claw on the top edge
  const cx = x + Math.round(pw / 2);
  S.rect(cx - 7, fy - 5, 14, 9, 'ink'); S.rect(cx - 6, fy - 4, 12, 7, 'gold'); S.rect(cx - 6, fy - 4, 12, 1, 'cream');
  S.rect(cx - 3, fy - 3, 6, 5, (Math.floor(t * 3) & 1) ? 'coral' : 'red'); S.px(cx - 2, fy - 3, 'peach'); S.frame(cx - 4, fy - 4, 8, 7, 'ink');
  // name plate + level
  const name = String(o.name ?? 'BOSS').toUpperCase(), lvl = o.level === null || o.level === undefined ? '' : `LV ${o.level}`;
  const label = lvl ? `${name}  ${lvl}` : name;
  const tw = measure(label, 'caps'), plw = Math.max(tw + 16, Math.min(fw, tw + 40)), plx = Math.round(cx - plw / 2), ply = fy + fh + 3;
  S.rect(plx, ply, plw, 14, 'ink'); S.rect(plx + 1, ply + 1, plw - 2, 12, 'maroon'); S.rect(plx + 1, ply + 1, plw - 2, 1, 'red'); S.rect(plx + 1, ply + 12, plw - 2, 1, 'plumdk');
  const textBox = { x: cx, y: ply + 3, label };
  const draw = o.say || ((str, xx, yy, oo) => drawText(S, str, xx, yy, oo));
  if (lvl) {
    const nx = cx - Math.round(tw / 2);
    draw(name, nx, ply + 3, { font: 'caps', color: 'white', shadow: [1, 1, 'ink'] });
    draw(lvl, nx + measure(name + '  ', 'caps'), ply + 3, { font: 'caps', color: 'gold', shadow: [1, 1, 'ink'] });
  } else draw(name, cx, ply + 3, { font: 'caps', color: 'white', shadow: [1, 1, 'ink'], align: 'center' });
  // HP bar under the plate
  const bw = Math.max(plw, 64), bx = Math.round(cx - bw / 2), by = ply + 17;
  drawText(S, 'HP', bx, by - 1, { font: 'tiny', color: 'coral', shadow: [1, 1, 'ink'] });
  bar(S, bx + 14, by, bw - 14, o.hp ?? 1, { h: 6, lag: o.hpLag, fill: ['coral', 'red'], tick: 6 });
  return { pic: { x, y, w: pw, h: ph }, outer: { x: fx, y: fy - 5, w: fw, h: by + 6 - (fy - 5) }, plate: { x: plx, y: ply, w: plw, h: 14 }, bar: { x: bx, y: by, w: bw, h: 6 }, text: textBox };
}
