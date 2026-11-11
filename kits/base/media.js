// Auteur kits/base — browser frame + device frame + cursor/ripple + highlight ring blocks for the
// product media scenes (HOOK image, SCREEN, FEATURE, SCROLL, BEFORE_AFTER images).

import { h, css, ICONS } from './dom.js';
import { seg, ease, clamp, lerp } from './motion.js';

/** Resolve an image param ({asset, path, w, h, url, ...} or an asset name) to {image, w, h, meta}. */
export function mediaOf(ctx, img) {
  const meta = img && typeof img === 'object' ? img : { asset: img };
  const name = meta.asset || meta.name || null;
  let a = null;
  try { a = name && typeof ctx.asset === 'function' ? ctx.asset(name) : null; } catch (e) { a = null; }
  const image = a && (a.image || (typeof a.frame === 'function' ? a.frame(0) : null));
  const w = Number((a && a.w) || meta.w || (image && (image.naturalWidth || image.width)) || 1440);
  const hh = Number((a && a.h) || meta.h || (image && (image.naturalHeight || image.height)) || 900);
  return { image, w, h: hh, meta, asset: a };
}

/** Pretty URL for the address bar: no scheme, no trailing slash. */
export function prettyUrl(u) {
  let s = String(u || '').trim();
  s = s.replace(/^[a-z]+:\/\/(\/)?/i, '').replace(/\/$/, '');
  return s;
}

const LOCAL_PATH = /^(?:~|\/|[a-z]:[\\/]|file:)|\\/i;

/**
 * Address-bar text for a screenshot: a web URL (no scheme), else the page title, else the file name — never a
 * filesystem path (local captures and session screenshots carry paths) — cut to `maxChars` with an ellipsis.
 */
// machine-made file stems ("e84_desktop_1920x1080", "shot_003", "cap-2026...") never reach an address bar
const MACHINE_STEM = /^(?:e\d+_|shot[_-]?\d|cap(?:ture)?[_-]|img[_-]?\d|screenshot[_-]?\d)|\d{3,4}x\d{3,4}|_(?:full|desktop|mobile|viewport|cut|el|step)(?:_|$)|^\d+$/i;

export function addressText(meta, maxChars = 60, fallback = '') {
  const m = meta || {};
  const raw = String(m.url || '').trim();
  let s = raw && !LOCAL_PATH.test(raw) ? prettyUrl(raw) : '';
  if (!s && m.page_title) s = String(m.page_title).trim().replace(/\.(png|jpe?g|webp|gif|avif|bmp)$/i, '');
  if (!s && (raw || m.path)) {
    const stem = String(raw || m.path).split(/[\\/]/).pop().replace(/\.(png|jpe?g|webp|gif|avif|bmp|mp4|webm|mov)$/i, '');
    s = MACHINE_STEM.test(stem) ? '' : stem;
  }
  if (!s) s = String(fallback || '').trim();
  return s.length > maxChars ? `${s.slice(0, Math.max(4, maxChars - 1))}\u2026` : s;
}

/**
 * Browser frame showing a screenshot. o: {width, viewH (viewport height px; default from image aspect,
 * capped by maxViewH), maxViewH, scroll:[from,to] fractions (full-page captures), chrome (bool)}.
 * The screenshot is painted once into a canvas (so any image/frames source works) and moved by CSS.
 */
export function browserBlock(ctx, img, o = {}) {
  const m = mediaOf(ctx, img);
  const width = o.width || 1400;
  const chromeH = o.chrome === false ? 0 : 66;
  const scale = width / m.w;
  const natural = m.h * scale;
  const viewH = Math.round(Math.min(o.viewH || natural, o.maxViewH || natural));
  const el = h('div', 'srb-browser');
  el.style.cssText = `width:${width}px;height:${chromeH + viewH}px;`;
  if (chromeH) {
    const bar = h('div', 'srb-urlbar');
    const dots = h('div', 'srb-dots', null, [h('i'), h('i'), h('i')]);
    const url = h('div', 'srb-url');
    url.dataset.qa = 'off';           // browser chrome: cropped by push-ins by design, not content to QA
    // ~16 px per mono char at 27 px; dots + padding + lock take ~190 px
    const pu = addressText(m.meta, Math.max(12, Math.floor((width - 200) / 17)), (ctx.film && ctx.film.title) || '');
    const slash = /^[\w.-]+(:\d+)?\//.test(pu) ? pu.indexOf('/') : -1;
    url.appendChild(h('span', '', { html: ICONS.lock }));
    if (slash > 0) { url.appendChild(h('b', '', { text: pu.slice(0, slash) })); url.append(pu.slice(slash)); }
    else url.appendChild(h('b', '', { text: pu || ' ' }));
    bar.append(dots, url);
    el.appendChild(bar);
  }
  const view = h('div', 'srb-view');
  view.style.cssText = `width:${width}px;height:${viewH}px;`;
  el.appendChild(view);
  // paint: cap the canvas at 4096 px tall (very long full-page captures are downsampled)
  const cap = Math.min(1, 4096 / m.h, 2400 / m.w);
  const cw = Math.max(1, Math.round(m.w * cap)), chh = Math.max(1, Math.round(m.h * cap));
  const cv = h('canvas');
  cv.width = cw; cv.height = chh;
  const g = cv.getContext('2d');
  if (m.image) {
    g.imageSmoothingQuality = 'high';
    g.drawImage(m.image, 0, 0, cw, chh);
  } else {
    g.fillStyle = '#ECEAE4'; g.fillRect(0, 0, cw, chh);
  }
  const cs = width / cw;
  cv.style.width = cw + 'px';
  cv.style.height = chh + 'px';
  view.appendChild(cv);
  const sb = h('div', 'srb-scrollbar');
  const scrollable = natural > viewH + 2;
  if (scrollable) view.appendChild(sb);
  const range = Math.max(0, natural - viewH);
  let scrollY = 0;

  function setScroll(u) {
    scrollY = range * clamp(u);
    css(cv, { transform: `translate(0, ${(-scrollY).toFixed(2)}px) scale(${cs})` });
    if (scrollable) {
      const th = Math.max(40, viewH * viewH / natural);
      css(sb, { height: th + 'px', top: `${(6 + (viewH - th - 12) * clamp(u)).toFixed(2)}px` });
    }
  }
  setScroll(0);
  return {
    el, w: width, h: chromeH + viewH, chromeH, viewH, natural, scrollable, media: m,
    setScroll,
    /** image-fraction point -> block px (accounts for the current scroll) */
    pt(fx, fy) { return [fx * width, chromeH + fy * natural - scrollY]; },
    /** image-fraction rect [x,y,w,h] -> block px rect */
    rect(b) { return { x: b[0] * width, y: chromeH + b[1] * natural - scrollY, w: b[2] * width, h: b[3] * natural }; },
    view,
  };
}

/** A phone-ish device frame (portrait media in 9:16 shots). Returns {el, screen, w, h}. */
export function deviceBlock(width, height) {
  const el = h('div', 'srb-device');
  el.style.cssText = `position:absolute;width:${width}px;height:${height}px;border-radius:${Math.round(width * 0.11)}px;` +
    'background:var(--sr-term);box-shadow:var(--sr-term-edge),var(--sr-panel-shadow);padding:16px;';
  const screen = h('div', 'srb-device-screen');
  screen.style.cssText = `position:relative;width:100%;height:100%;border-radius:${Math.round(width * 0.085)}px;overflow:hidden;background:#fff;`;
  el.appendChild(screen);
  return { el, screen, w: width, h: height };
}

/**
 * Cursor that travels along a path, pauses, presses (dip) and leaves a ripple. All block px.
 * o: {from:[x,y], to:[x,y], arrive (t), press (t), size}
 */
export function cursorBlock(o) {
  const cur = h('div', 'srb-cursor', { html: ICONS.cursor });
  const rip = h('div', 'srb-ripple');
  const rip2 = h('div', 'srb-ripple');
  const s = o.size || 1.4;
  const cues = [{ t: o.press, sfx: 'click', gain_db: -6 }];
  function update(t) {
    const travel0 = o.arrive - (o.travel || 0.7);
    const u = seg(t, travel0, o.arrive, ease.inOutCubic);
    // slight arc so the move reads as a hand, not a tween
    const x = lerp(o.from[0], o.to[0], u);
    const y = lerp(o.from[1], o.to[1], u) - Math.sin(Math.PI * u) * 40;
    const dip = t >= o.press ? Math.exp(-(t - o.press) * 14) * (t - o.press < 0.06 ? (t - o.press) / 0.06 : 1) : 0;
    const vis = seg(t, travel0 - 0.25, travel0 + 0.05);
    css(cur, { opacity: vis.toFixed(3), transform: `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px) scale(${(s * (1 - 0.16 * dip)).toFixed(4)})` });
    for (const [r, delay, max] of [[rip, 0, 90], [rip2, 0.12, 150]]) {
      const ru = seg(t, o.press + delay, o.press + delay + 0.7, ease.outCubic);
      const rad = 10 + max * ru;
      css(r, { opacity: t >= o.press + delay ? (1 - ru).toFixed(3) : '0', left: `${(o.to[0] - rad).toFixed(2)}px`,
        top: `${(o.to[1] - rad).toFixed(2)}px`, width: `${(rad * 2).toFixed(2)}px`, height: `${(rad * 2).toFixed(2)}px` });
    }
  }
  return { els: [rip, rip2, cur], update, cues };
}

/** Accent ring around a rect that draws in; dims the rest of its container. */
export function ringBlock() {
  const el = h('div', 'srb-ring');
  function update(t, rect, t0, dimTo = 0.28) {
    const u = seg(t, t0, t0 + 0.5, ease.outQuint);
    const pad = 10 + (1 - u) * 26;
    css(el, { left: `${(rect.x - pad).toFixed(2)}px`, top: `${(rect.y - pad).toFixed(2)}px`, width: `${(rect.w + 2 * pad).toFixed(2)}px`,
      height: `${(rect.h + 2 * pad).toFixed(2)}px`, opacity: clamp(u * 1.5).toFixed(3), '--dim': (dimTo * u).toFixed(3) });
  }
  return { el, update };
}
