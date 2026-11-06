// Showreel kit "comic" — product media printed into panels: the screenshot first appears as a coarse colour
// halftone (Ben-Day print), then the real pixels grow in through the dot screen; a faint print screen stays on.
// Also the comic browser frame (yellow address caption) and hero content blocks (image | terminal | diff | code).

import { h, css } from '../../base/dom.js';
import { seg, ease, clamp } from '../../base/motion.js';
import { mediaOf, prettyUrl, browserBlock } from '../../base/media.js';
import { contentBlock } from '../../base/scenes-media.js';
import { flat, PENDING, svgEl, dotsPath } from './art.js';

/**
 * Screenshot printed into a w x hh box. o: {crop: [x, y, w, h] fractions (default: cover-fit, top-aligned),
 * cell (halftone pitch px), scale}. update(t, t0, dur) runs the dot reveal. Returns {el, w, h, pt(fx, fy), rect(b)}.
 */
export function printShot(ctx, img, w, hh, o = {}) {
  const m = mediaOf(ctx, img);
  const el = h('div', 'cx-shot');
  el.style.cssText = `width:${w}px;height:${hh}px;`;
  // crop rect in image px: cover-fit unless given
  let cr = o.crop;
  if (!cr) {
    const s = Math.max(w / m.w, hh / m.h);
    const vw = w / s / m.w, vh = hh / s / m.h;
    cr = [(1 - vw) / 2, o.top === false ? (1 - vh) / 2 : 0, vw, vh];
  }
  const sx = cr[0] * m.w, sy = cr[1] * m.h, sw = cr[2] * m.w, sh = cr[3] * m.h;
  const doc = el.ownerDocument;
  // the real pixels: the loaded asset <img> cropped by position (no canvas: plain images paint into the camera
  // layer, canvases become composited layers whose raster depends on seek history)
  let real;
  if (m.image && m.image.src) {
    real = h('div', 'cx-real');
    real.style.cssText = `width:${w}px;height:${hh}px;background:#FFFDF6;`;
    const im = doc.createElement('img');
    im.decoding = 'sync';
    im.draggable = false;
    const iw = w / cr[2], ih = hh / cr[3];
    im.style.cssText = `position:absolute;left:${(-cr[0] * iw).toFixed(2)}px;top:${(-cr[1] * ih).toFixed(2)}px;width:${iw.toFixed(2)}px;height:${ih.toFixed(2)}px;max-width:none;`;
    im.src = m.image.src;
    PENDING.push(im.decode().catch(() => {}));
    real.appendChild(im);
  } else {
    const sc = o.scale || 2;
    const rc = doc.createElement('canvas');
    rc.width = Math.round(w * sc); rc.height = Math.round(hh * sc);
    rc.style.cssText = `width:${w}px;height:${hh}px;`;
    const g = rc.getContext('2d');
    g.fillStyle = '#FFFDF6'; g.fillRect(0, 0, rc.width, rc.height);
    if (m.image) { g.imageSmoothingQuality = 'high'; g.drawImage(m.image, sx, sy, sw, sh, 0, 0, rc.width, rc.height); }
    real = flat(rc);
  }
  // colour halftone of the same crop (dot size = darkness, dot colour = boosted pixel colour, quantised to a
  // process-ink palette so the screen is a few SVG paths: vector, re-rasterised crisply, deterministic)
  const cell = o.cell || 13;
  const nx = Math.max(1, Math.ceil(w / cell)), ny = Math.max(1, Math.ceil(hh / cell));
  const small = doc.createElement('canvas');
  small.width = nx; small.height = ny;
  const sg = small.getContext('2d', { willReadFrequently: true });
  if (m.image) sg.drawImage(m.image, sx, sy, sw, sh, 0, 0, nx, ny);
  let px = null;
  try { px = sg.getImageData(0, 0, nx, ny).data; } catch (e) { px = null; }
  const q = (v) => Math.min(255, Math.round(v / 51) * 51);
  const groups = new Map();
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const k = (j * nx + i) * 4;
      const r = px ? px[k] : 200, gg = px ? px[k + 1] : 200, b = px ? px[k + 2] : 200;
      const lum = (0.2126 * r + 0.7152 * gg + 0.0722 * b) / 255;
      const mx = Math.max(r, gg, b), mn = Math.min(r, gg, b);
      // boost saturation, push toward process inks
      const boost = (v) => q(clamp(Math.round(mn + (v - mn) * 1.6 - (255 - mx) * 0.25), 0, 255));
      const rad = Math.sqrt(clamp(1.08 - lum, 0.06, 1)) * cell * 0.62;
      const key = `${boost(r)},${boost(gg)},${boost(b)}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push([(i + 0.5 + (j % 2) * 0.5) * cell, (j + 0.5) * cell, rad]);
    }
  }
  const paths = [...groups.entries()].map(([k, ds]) => `<path fill="rgb(${k})" d="${dotsPath(ds)}"/>`).join('');
  const toneImg = svgEl(doc, w, hh, `<rect width="${w}" height="${hh}" fill="#FFFDF6"/>${paths}`, { style: 'position:absolute;left:0;top:0;overflow:hidden;' });
  el.append(toneImg, real);
  const dots = h('div', 'cx-benday');
  dots.style.cssText += '--dot:rgba(20,17,15,.07);--cell:6px;mix-blend-mode:multiply;';
  el.appendChild(dots);
  const pcell = cell;
  return {
    el, w, h: hh, media: m, crop: cr,
    /** image-fraction point -> box px */
    pt(fx, fy) { return [((fx - cr[0]) / cr[2]) * w, ((fy - cr[1]) / cr[3]) * hh]; },
    rect(bb) { const [x, y] = this.pt(bb[0], bb[1]); return { x, y, w: (bb[2] / cr[2]) * w, h: (bb[3] / cr[3]) * hh }; },
    /** dots grow from nothing to full coverage between t0 and t0 + dur (the print "develops") */
    update(t, t0 = 0.2, dur = 0.55) {
      const u = seg(t, t0, t0 + dur, ease.inOutCubic);
      if (u >= 1) { css(real, { maskImage: 'none', webkitMaskImage: 'none', visibility: 'visible' }); css(toneImg, { visibility: 'hidden' }); return; }
      css(toneImg, { visibility: 'visible' });
      if (u <= 0) { css(real, { visibility: 'hidden' }); return; }
      const R = (u * pcell * 0.76).toFixed(2);
      const mask = `radial-gradient(circle, #000 ${R}px, transparent ${(Number(R) + 0.8).toFixed(2)}px)`;
      css(real, { visibility: 'visible', maskImage: mask, webkitMaskImage: mask, maskSize: `${pcell}px ${pcell}px`, webkitMaskSize: `${pcell}px ${pcell}px` });
    },
  };
}

/** Comic browser frame around a printed shot: a yellow address caption on top. Returns {el, shot, chromeH, w, h}. */
export function comicBrowser(ctx, img, w, viewH, o = {}) {
  const el = h('div', 'cx-abs');
  const chromeH = o.chrome === false ? 0 : 64;
  el.style.cssText = `width:${w}px;height:${viewH + chromeH}px;background:#FFFDF6;box-shadow:0 0 0 6px #14110F, 12px 12px 0 6px #14110F;`;
  if (chromeH) {
    const bar = h('div', 'srb-urlbar');
    bar.style.cssText = 'height:64px;font-size:26px;';
    const dots = h('div', 'srb-dots', null, [h('i'), h('i'), h('i')]);
    const url = h('div', 'srb-url');
    const meta = img && typeof img === 'object' ? img : {};
    url.appendChild(h('b', '', { text: prettyUrl(meta.url || meta.page_title || '') || ' ' }));
    bar.append(dots, url);
    el.appendChild(bar);
  }
  const shot = printShot(ctx, img, w, viewH, o);
  shot.el.style.top = `${chromeH}px`;
  el.appendChild(shot.el);
  return { el, shot, chromeH, w, h: viewH + chromeH };
}

/** Full-page scrolling browser (kit:base browserBlock restyled) with the print screen on top. */
export function scrollBrowser(ctx, img, w, viewH) {
  const b = browserBlock(ctx, img, { width: w, viewH });
  b.el.style.boxShadow = '0 0 0 6px #14110F, 12px 12px 0 6px #14110F';
  const dots = h('div', 'cx-benday');
  dots.style.cssText += '--dot:rgba(20,17,15,.07);--cell:6px;mix-blend-mode:multiply;z-index:3;';
  b.view.appendChild(dots);
  return b;
}

/**
 * Hero content for HOOK / BEFORE_AFTER / TITLE in comic ink: image -> printed shot in a browser caption frame;
 * terminal / diff / code -> the kit:base block (comic tokens). Returns {el, w, h, kind, update(t), cues}.
 */
export function heroBlock(ctx, c, o) {
  const kind = (c && c.kind) || (c && (c.asset || c.path) ? 'image' : 'code');
  if (kind === 'image') {
    const img = c.image || c;
    const m = mediaOf(ctx, img);
    const maxW = o.width, maxH = o.maxH - 64;
    const w = Math.round(Math.min(maxW, (maxH * m.w) / m.h));
    const vh = Math.round(Math.min(maxH, (w * m.h) / m.w));
    const b = comicBrowser(ctx, img, w, vh, { cell: o.cell });
    return { el: b.el, w: b.w, h: b.h, kind, shot: b.shot, cues: [], update: (t) => b.shot.update(t, o.t0 ?? 0.15, o.develop ?? 0.5) };
  }
  const b = contentBlock(ctx, c, { ...o, fast: true });
  return { ...b, kind };
}
