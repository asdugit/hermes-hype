// Hype kit "terminal" — product media in the tube. A screenshot is painted once into three plates:
// ASCII (phosphor characters by luminance), ordered dither (Bayer 4x4 phosphor dots) and the real image; the
// shot resolves ASCII -> dither -> real with a bright raster line sweeping down the glass (whole frames, no
// fades: a CRT redraws, it does not dissolve). Plates are drawn in setup; render only moves clip edges.

import { h, css } from '../base/dom.js';
import { mediaOf } from '../base/media.js';
import { clamp, seg, ease } from '../base/motion.js';
import { phosphorOf } from './crt.js';

const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16);
const RAMP = ' .:-=+*#%@';

/** Average luminance grid (gx x gy cells, 0..1) of an image source; null if the pixels cannot be read. */
function lumaGrid(doc, img, gx, gy, crop) {
  const c = doc.createElement('canvas');
  c.width = gx; c.height = gy;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.imageSmoothingQuality = 'high';
  const [sx, sy, sw, sh] = crop;
  g.drawImage(img, sx, sy, sw, sh, 0, 0, gx, gy);
  let d;
  try { d = g.getImageData(0, 0, gx, gy).data; } catch (e) { return null; }
  const lum = new Float32Array(gx * gy), chroma = new Float32Array(gx * gy);
  let mean = 0;
  for (let i = 0; i < gx * gy; i++) {
    const r = d[i * 4] / 255, gg = d[i * 4 + 1] / 255, b = d[i * 4 + 2] / 255;
    // luminance plus a chroma boost: coloured UI (buttons, charts) must light up even when mid-grey in luma
    lum[i] = 0.2126 * r + 0.7152 * gg + 0.0722 * b;
    chroma[i] = Math.max(r, gg, b) - Math.min(r, gg, b);
    mean += lum[i];
  }
  mean /= gx * gy;
  // light UIs (white pages) invert: the ink, not the paper, is what a phosphor would draw
  const inv = mean > 0.5;
  const vals = new Float32Array(gx * gy);
  for (let i = 0; i < gx * gy; i++) vals[i] = clamp((inv ? 1 - lum[i] : lum[i]) + chroma[i] * 0.9);
  // contrast stretch between the 4th and 97th percentiles
  const sorted = Array.from(vals).sort((a, b) => a - b);
  const lo = sorted[Math.floor(sorted.length * 0.04)], hi = Math.max(lo + 0.05, sorted[Math.floor(sorted.length * 0.97)]);
  for (let i = 0; i < vals.length; i++) vals[i] = Math.pow(clamp((vals[i] - lo) / (hi - lo)), 0.85);
  return vals;
}

/**
 * Media plates for an image param, displayed at w x h reference px (surface scale k). o: {phosphor, cell (dither
 * px), crop: [x, y, w, h] image fractions (default whole), full (keep full-page height; SCROLL)}.
 * Returns {el, w, h, update(t, stages), media}; stages = {ascii: t0, dither: t1, real: t2, scan: s} times.
 */
export function phosphorMedia(ctx, F, img, w, h0, o = {}) {
  const doc = F.el.ownerDocument;
  const m = mediaOf(ctx, img);
  const P = phosphorOf(o);
  const k = F.k;
  const crop = o.crop || [0, 0, 1, 1];
  const src = [crop[0] * m.w, crop[1] * m.h, crop[2] * m.w, crop[3] * m.h];
  const hh = Math.round(h0);
  const el = h('div', 'tm-media');
  el.style.cssText = `width:${Math.round(w)}px;height:${hh}px;background:${P.glass};`;
  const mk = (cls) => {
    const c = doc.createElement('canvas');
    c.width = Math.max(1, Math.round(w * k)); c.height = Math.max(1, Math.round(hh * k));
    c.style.cssText = `width:${Math.round(w)}px;height:${hh}px;`;
    c.className = cls;
    el.appendChild(c);
    return c;
  };
  const cA = mk('tm-ascii'), cD = mk('tm-dither'), cR = mk('tm-real');
  const line = h('div', '');
  line.style.cssText = `position:absolute;left:0;width:100%;height:3px;background:${P.hot};box-shadow:0 0 14px 4px rgba(${P.rgb.join(',')},.7);`;
  el.appendChild(line);
  if (m.image) {
    // real plate (true colours: the product is the only full-colour thing in the tube)
    const gR = cR.getContext('2d');
    gR.imageSmoothingQuality = 'high';
    gR.drawImage(m.image, src[0], src[1], src[2], src[3], 0, 0, cR.width, cR.height);
    // a colour tube, not a monitor: paper whites go warm and a touch darker so the page sits in the glass
    gR.globalCompositeOperation = 'multiply';
    gR.fillStyle = o.warm || '#EAD5B8';
    gR.fillRect(0, 0, cR.width, cR.height);
    gR.globalCompositeOperation = 'source-over';
    // dither plate: phosphor dots on glass
    const cell = (o.cell || 6) * k;
    const gx = Math.max(2, Math.round(cR.width / cell)), gy = Math.max(2, Math.round(cR.height / cell));
    const L = lumaGrid(doc, m.image, gx, gy, src);
    const gD = cD.getContext('2d');
    gD.fillStyle = P.glass; gD.fillRect(0, 0, cD.width, cD.height);
    if (L) {
      const cw = cD.width / gx, ch = cD.height / gy, dot = Math.max(1, cw * 0.78);
      for (let y = 0; y < gy; y++) for (let x = 0; x < gx; x++) {
        const v = L[y * gx + x];
        if (v <= BAYER[(y & 3) * 4 + (x & 3)]) continue;
        gD.fillStyle = v > 0.9 ? P.hot : v > 0.45 ? P.ph : P.mid;
        gD.fillRect(x * cw, y * ch, dot, dot * (ch / cw));
      }
    }
    // ASCII plate: characters by luminance on the Plex Mono grid
    const fs = (o.asciiFs || 18) * k, cwA = fs * 0.6, chA = fs * 1.3;
    const ax = Math.max(2, Math.floor(cA.width / cwA)), ay = Math.max(2, Math.floor(cA.height / chA));
    const LA = lumaGrid(doc, m.image, ax, ay, src);
    const gA = cA.getContext('2d');
    gA.fillStyle = P.glass; gA.fillRect(0, 0, cA.width, cA.height);
    gA.font = `500 ${fs}px "IBM Plex Mono", monospace`;
    gA.textBaseline = 'top';
    if (LA) {
      for (let y = 0; y < ay; y++) for (let x = 0; x < ax; x++) {
        const v = LA[y * ax + x];
        const ch = RAMP[Math.min(RAMP.length - 1, Math.floor(v * RAMP.length))];
        if (ch === ' ') continue;
        gA.fillStyle = v > 0.85 ? P.hot : v > 0.4 ? P.ph : P.dim;
        gA.fillText(ch, x * cwA, y * chA + fs * 0.1);
      }
    }
  } else {
    for (const c of [cA, cD, cR]) { const g = c.getContext('2d'); g.fillStyle = P.glass; g.fillRect(0, 0, c.width, c.height); }
  }

  /** Stage times {ascii, dither, real}: each stage sweeps in top->bottom over `scan` seconds. */
  function update(t, st) {
    const scan = st.scan ?? 0.2;
    const uA = seg(t, st.ascii, st.ascii + scan), uD = seg(t, st.dither, st.dither + scan), uR = seg(t, st.real, st.real + scan);
    const clip = (u) => (u >= 1 ? 'none' : `inset(0 0 ${((1 - u) * 100).toFixed(2)}% 0)`);
    css(cA, { visibility: uA > 0 ? 'visible' : 'hidden', clipPath: clip(uA) });
    css(cD, { visibility: uD > 0 ? 'visible' : 'hidden', clipPath: clip(uD) });
    css(cR, { visibility: uR > 0 ? 'visible' : 'hidden', clipPath: clip(uR) });
    const active = [uR, uD, uA].find((u) => u > 0 && u < 1);
    css(line, { opacity: active !== undefined ? '1' : '0', top: `${((active ?? 0) * hh - 1.5).toFixed(1)}px` });
  }
  return { el, w: Math.round(w), h: hh, update, media: m };
}

/** Pixel-art pointer (hot phosphor) as a canvas element, `px` reference px per pixel. */
export function pointer(F, P, px = 5) {
  const rows = ['#.........', '##........', '#=#.......', '#==#......', '#===#.....', '#====#....', '#=====#...',
    '#======#..', '#===####..', '#=##=#....', '##..#=#...', '#...#=#...', '.....#=#..', '.....###..'];
  const doc = F.el.ownerDocument;
  const k = F.k;
  const c = doc.createElement('canvas');
  c.width = Math.round(10 * px * k); c.height = Math.round(rows.length * px * k);
  c.style.cssText = `position:absolute;width:${10 * px}px;height:${rows.length * px}px;filter:drop-shadow(0 0 6px rgba(${P.rgb.join(',')},.8));`;
  const g = c.getContext('2d');
  rows.forEach((r, y) => [...r].forEach((ch, x) => {
    if (ch === '.') return;
    g.fillStyle = ch === '#' ? P.hot : P.glass;
    g.fillRect(x * px * k, y * px * k, px * k, px * k);
  }));
  return c;
}

export { clamp, ease };
