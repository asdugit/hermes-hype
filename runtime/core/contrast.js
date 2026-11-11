// Runtime contrast pass for DOM shots (E19): headline/body text must read at >= 4.5:1 against what is actually
// behind it. Customised themes put dark type on a dark blurred screenshot, or light type on a light capture.
// At a few fixed times per shot the runtime measures each visible text box's colour against the backdrop under
// it (solid backgrounds, simple gradients and image/canvas pixels, composited top-down), and gives text that
// fails a halo plate in a contrasting tint of its own colour (text-shadow: no layout change). Text that already
// reads is left alone, so curated looks stay intact.
import { domTextBoxes } from './qa.js';

const MIN_RATIO = 4.5;

let probe = null;
function rgbaOf(css) {
  if (!css || css === 'transparent') return [0, 0, 0, 0];
  const m = /^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/.exec(css);
  if (m) {
    let a = m[4] == null ? 1 : parseFloat(m[4]);
    if (m[4] && m[4].endsWith('%')) a /= 100;
    return [+m[1], +m[2], +m[3], a];
  }
  if (!probe) {
    const c = document.createElement('canvas');
    c.width = 1; c.height = 1;
    probe = c.getContext('2d', { willReadFrequently: true });
  }
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = '#000';
  probe.fillStyle = css;
  probe.fillRect(0, 0, 1, 1);
  const d = probe.getImageData(0, 0, 1, 1).data;
  return [d[0], d[1], d[2], d[3] / 255];
}

const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
export const luminance = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
export const ratio = (a, b) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

const imgCache = new WeakMap();
/** Average colour of an image/canvas element around client point (x, y), filter applied (blur ignored). */
function samplePixels(el, x, y) {
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return null;
  let src = el, nw, nh;
  if (el.tagName === 'IMG') { if (!el.complete || !el.naturalWidth) return null; nw = el.naturalWidth; nh = el.naturalHeight; }
  else if (el.tagName === 'CANVAS') { nw = el.width; nh = el.height; }
  else if (el.tagName === 'VIDEO') { nw = el.videoWidth; nh = el.videoHeight; }
  else return null;
  if (!nw || !nh) return null;
  let ent = imgCache.get(el);
  const filt = (getComputedStyle(el).filter || 'none').replace(/blur\([^)]*\)/g, '').trim() || 'none';
  if (!ent || el.tagName !== 'IMG' || ent.filt !== filt) {
    const SW = 96, SH = Math.max(8, Math.round((96 * nh) / nw));
    const c = document.createElement('canvas');
    c.width = SW; c.height = SH;
    const g = c.getContext('2d', { willReadFrequently: true });
    try {
      g.filter = filt;
      g.drawImage(src, 0, 0, SW, SH);
      ent = { data: g.getImageData(0, 0, SW, SH).data, SW, SH, filt };
    } catch (_) { return null; }
    imgCache.set(el, ent);
  }
  // map the client point into the picture (object-fit cover/contain/fill)
  const fit = getComputedStyle(el).objectFit;
  let dw = r.width, dh = r.height, ox = 0, oy = 0;
  if (fit === 'cover' || fit === 'contain') {
    const s = fit === 'cover' ? Math.max(r.width / nw, r.height / nh) : Math.min(r.width / nw, r.height / nh);
    dw = nw * s; dh = nh * s; ox = (r.width - dw) / 2; oy = (r.height - dh) / 2;
  }
  const u = (x - r.left - ox) / dw, v = (y - r.top - oy) / dh;
  if (u < 0 || v < 0 || u > 1 || v > 1) return null;
  const { data, SW, SH } = ent;
  const cx = Math.round(u * (SW - 1)), cy = Math.round(v * (SH - 1));
  let R = 0, G = 0, B = 0, A = 0, n = 0;
  for (let j = -2; j <= 2; j++) for (let i = -2; i <= 2; i++) {
    const px = Math.min(SW - 1, Math.max(0, cx + i)), py = Math.min(SH - 1, Math.max(0, cy + j));
    const k = (py * SW + px) * 4;
    const a = data[k + 3] / 255;
    R += data[k] * a; G += data[k + 1] * a; B += data[k + 2] * a; A += a; n++;
  }
  if (A < 0.05 * n) return null;
  return [R / A, G / A, B / A, A / n];
}

function gradientColour(bgImage) {
  if (!bgImage || bgImage === 'none' || !/gradient/.test(bgImage)) return null;
  const cols = bgImage.match(/rgba?\([^)]*\)|#[0-9a-f]{3,8}\b/gi);
  if (!cols || !cols.length) return null;
  let R = 0, G = 0, B = 0, A = 0;
  for (const c of cols) { const [r, g, b, a] = rgbaOf(c); R += r * a; G += g * a; B += b * a; A += a; }
  if (A <= 0) return null;
  return [R / A, G / A, B / A, A / cols.length];
}

/** Composite backdrop colour behind `el` at client point (x, y): every layer under the text, top-down. */
function backdropAt(el, x, y, stageEl, base, scope) {
  const stack = document.elementsFromPoint(x, y);
  let i = stack.indexOf(el);
  if (i < 0) {
    // the text's own element may not be hit (pointer-events / inline box): start under its closest hit ancestor
    i = stack.findIndex((s) => s.contains(el)) - 1;
  }
  const opCache = new Map();
  const effOp = (e) => {
    if (!e || e === stageEl || e === document.body) return 1;
    if (opCache.has(e)) return opCache.get(e);
    const cs = getComputedStyle(e);
    const v = (cs.visibility === 'hidden' ? 0 : Number(cs.opacity)) * effOp(e.parentElement);
    opCache.set(e, v);
    return v;
  };
  let R = 0, G = 0, B = 0, rem = 1, pic = 0;
  const add = (c, a) => { if (a <= 0) return; R += c[0] * a * rem; G += c[1] * a * rem; B += c[2] * a * rem; rem *= 1 - a; };
  for (let k = i + 1; k < stack.length && rem > 0.02; k++) {
    const e = stack[k];
    if (e === document.documentElement || e === document.body) break;
    if (!(scope || stageEl).contains(e)) continue;
    if (e !== el && el.contains(e)) continue;
    const op = effOp(e);
    if (op < 0.02) continue;
    const cs = getComputedStyle(e);
    if (e.tagName === 'IMG' || e.tagName === 'CANVAS' || e.tagName === 'VIDEO') {
      const c = samplePixels(e, x, y);
      if (c) { pic += c[3] * op * rem; add(c, c[3] * op); }
      continue;
    }
    const g = gradientColour(cs.backgroundImage);
    if (g) add(g, g[3] * op);
    const bg = rgbaOf(cs.backgroundColor);
    if (bg[3] > 0) add(bg, bg[3] * op);
  }
  add(base, 1);
  const out = [R, G, B];
  out.pic = pic;
  return out;
}

/**
 * Find display text below `minRatio` against its backdrop. Returns [{el, ratio, text, colour}] (worst sample of
 * each element). minSize: only text at least this big (film px).
 */
export function lowContrast(root, stage, { W, H, minSize = 22, picSize = 0, base = [0, 0, 0], minRatio = MIN_RATIO, scope = null } = {}) {
  const out = new Map();
  const sr = stage.el.getBoundingClientRect();
  const sc = stage.scale || 1;
  for (const b of domTextBoxes(root, stage, { id: 'contrast', kind: 'shot' })) {
    const [x, y, w, h] = b.rect;
    // headline type everywhere; smaller body type only where it sits over a picture (captures, renders)
    if (b.size < Math.min(minSize, picSize || minSize) || w < 4 || h < 4) continue;
    const onlyPic = b.size < minSize;
    if (x + w < 0 || y + h < 0 || x > W || y > H) continue;
    const cs = getComputedStyle(b.el);
    const fill = cs.webkitTextFillColor && !/currentcolor/i.test(cs.webkitTextFillColor) ? cs.webkitTextFillColor : cs.color;
    const tc = rgbaOf(fill);
    if (tc[3] < 0.3) continue;                         // outlined / knocked-out display type: not measurable here
    if (cs.backgroundClip === 'text' || cs.webkitBackgroundClip === 'text') continue;
    // designed outlines: an opaque text-stroke or text-shadow colour already separates the glyphs from anything
    let own = 0;
    const sw = parseFloat(cs.webkitTextStrokeWidth) || 0;
    if (sw >= 1) { const sc2 = rgbaOf(cs.webkitTextStrokeColor); if (sc2[3] >= 0.5) own = Math.max(own, ratio(tc, sc2)); }
    if (cs.textShadow && cs.textShadow !== 'none') {
      for (const col of cs.textShadow.match(/rgba?\([^)]*\)/g) || []) {
        const sc2 = rgbaOf(col);
        if (sc2[3] >= 0.5) own = Math.max(own, ratio(tc, sc2));
      }
    }
    if (own >= minRatio) continue;
    let worst = Infinity, wbd = null;
    for (const [fx, fy] of [[0.5, 0.55], [0.2, 0.55], [0.8, 0.55], [0.35, 0.3], [0.65, 0.8]]) {
      const px = x + w * fx, py = y + h * fy;
      if (px < 0 || py < 0 || px > W || py > H) continue;
      const bd = backdropAt(b.el, sr.left + px * sc, sr.top + py * sc, stage.el, base, scope);
      const c = [tc[0] * tc[3] + bd[0] * (1 - tc[3]), tc[1] * tc[3] + bd[1] * (1 - tc[3]), tc[2] * tc[3] + bd[2] * (1 - tc[3])];
      if (onlyPic && !(bd.pic > 0.3)) continue;
      const r = ratio(c, bd);
      if (r < worst) { worst = r; wbd = bd; }
    }
    if (worst < minRatio) {
      const prev = out.get(b.el);
      if (!prev || worst < prev.ratio) out.set(b.el, { el: b.el, ratio: worst, text: b.text, colour: tc, backdrop: wbd });
    }
  }
  return [...out.values()];
}

/** Halo plate for text of colour `tc` over backdrop `bd`: a tint of the text's hue pushed away from the text
 * (lighter behind text that is darker than its backdrop, darker behind text that is lighter). */
export function haloFor(tc, bd = null) {
  const L = luminance(tc);
  const light = bd ? L <= luminance(bd) : L < 0.3;
  const mixTo = light ? 255 : 0;
  const w = light ? 0.9 : 0.86;
  const c = tc.slice(0, 3).map((v) => Math.round(v + (mixTo - v) * w));
  const col = (a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  return `0 0 0.05em ${col(0.95)}, 0 0 0.16em ${col(0.9)}, 0 0 0.4em ${col(0.8)}, 0 0 0.85em ${col(0.6)}`;
}

/** Mark failing text with a halo (persistent for the instance). Returns the list it fixed. */
let peStyle = null;
export function fixContrast(root, stage, opts) {
  if (!peStyle) {
    peStyle = document.createElement('style');
    peStyle.textContent = '#sr-stage, #sr-stage * { pointer-events: auto !important; }';
  }
  document.head.appendChild(peStyle);
  let bad;
  try { bad = lowContrast(root, stage, opts); } finally { peStyle.remove(); }
  for (const b of bad) {
    if (b.el.dataset.srHalo) continue;
    b.el.dataset.srHalo = b.ratio.toFixed(2);
    const prev = getComputedStyle(b.el).textShadow;
    b.el.style.textShadow = prev && prev !== 'none' ? `${prev}, ${haloFor(b.colour, b.backdrop)}` : haloFor(b.colour, b.backdrop);
  }
  return bad;
}
