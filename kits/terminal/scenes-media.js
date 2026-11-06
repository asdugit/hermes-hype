// Showreel kit "terminal" — media scenes: HOOK, SCREEN, FEATURE, SCROLL, BEFORE_AFTER. Product captures are shown
// in box-drawn panes as phosphor ASCII -> ordered dither -> the real image (raster-scan resolve); zoom happens in
// discrete steps (terminal zoom), the pointer is a pixel-art hardware sprite, the click is an inverse-video flash.

import { h, css } from '../base/dom.js';
import { prettyUrl } from '../base/media.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { tubeScene } from './tube.js';
import { contentBox, paneFont, zoomSteps } from './scenes-panes.js';
import { ADV, lineH, sp, esc, len, fit, wrap, box, row, txt, typing, blink, cursor, phosphorOf } from './crt.js';
import { termPane, codePane, diffPane } from './pane.js';
import { phosphorMedia, pointer } from './phosphor.js';

const IMAGE_DOC = { type: 'image', default: null, doc: '{asset, path, w, h, url, page_title, full_page} (asset = film asset name)' };

/**
 * A screenshot in a box-drawn pane, sized to fit maxW x maxH (reference px) at grid font fs. The pane and the media
 * live in `wrap` (a full-frame layer, so zoom transforms apply to both). st = stage times {ascii, dither, real}.
 */
export function mediaPane(ctx, F, T, img, o) {
  const meta = img && typeof img === 'object' ? img : { asset: img };
  const fs = o.fs, adv = fs * ADV, lh = lineH(fs);
  const iw = Number(meta.w) || 1440, ih0 = Number(meta.h) || 900;
  const viewFrac = o.viewH ? Math.min(1, o.viewH / ih0) : 1;
  const ih = ih0 * viewFrac;
  // the image area snaps to whole grid cells (the pane is text); the image is fitted inside it
  const inner = Math.max(8, Math.floor(Math.min(o.maxW / adv - 4, (iw * (o.maxH - 2 * lh) / ih) / adv)));
  const sc = (inner * adv) / iw;
  const rows = Math.max(3, Math.ceil((ih * sc) / lh));
  const dw = inner * adv, dh = Math.min(ih * sc, rows * lh);
  const pw = (inner + 4) * adv, ph = (rows + 2) * lh;
  const x = o.x ?? o.cx - pw / 2, y = o.y ?? o.cy - ph / 2;
  const wrapEl = h('div', '');
  wrapEl.style.cssText = `position:absolute;left:0;top:0;width:${F.W}px;height:${F.H}px;transform-origin:0 0;`;
  (o.parent || T.scr).appendChild(wrapEl);
  const pre = h('pre', 'tm-pre');
  pre.style.cssText = `left:${Math.round(x)}px;top:${Math.round(y)}px;font-size:${fs}px;line-height:${lh}px;`;
  const title = fit(String(meta.page_title || o.title || 'screen'), 40);
  const url = prettyUrl(meta.url || '');
  pre.innerHTML = box(title, inner, Array.from({ length: rows }, () => txt('', '')), { right: fit(url, Math.max(8, inner - len(title) - 8)) }).join('\n');
  wrapEl.appendChild(pre);
  const ax = Math.round(x + 2 * adv + (inner * adv - dw) / 2), ay = Math.round(y + lh + (rows * lh - dh) / 2);
  const crop = o.viewH ? [0, o.cropY || 0, 1, viewFrac] : null;
  const m = phosphorMedia(ctx, F, meta, dw, dh, { phosphor: o.phosphor, crop: crop || undefined });
  css(m.el, { left: `${ax}px`, top: `${ay}px` });
  wrapEl.appendChild(m.el);
  const area = { x: ax, y: ay, w: dw, h: dh };
  return { wrap: wrapEl, pre, m, area, x, y, w: pw, h: ph, fs, inner, rows, meta, update: (t, st) => m.update(t, st) };
}

/**
 * Zoom for `wrap` (transform-origin 0 0): at scale s the point q maps to d + s*q, with d chosen so the focus point
 * f glides linearly from where it is (s = 1) to the frame point c (s = z): d = (1-w) f + w c - s f, w = (s-1)/(z-1).
 */
function zoomD(s, z, fx, fy, cx, cy) {
  const w = z > 1.0001 ? clamp((s - 1) / (z - 1)) : 0;
  return [(1 - w) * fx + w * cx - s * fx, (1 - w) * fy + w * cy - s * fy];
}
function zoomCss(s, z, fx, fy, cx, cy) {
  if (s <= 1.0001) return 'none';
  const [dx, dy] = zoomD(s, z, fx, fy, cx, cy);
  return `translate3d(${dx.toFixed(1)}px,${dy.toFixed(1)}px,0) scale(${s.toFixed(4)})`;
}
/** Screen-space position of the wrap-local point (qx, qy) under zoomCss. */
function zoomPt(s, z, fx, fy, cx, cy, qx, qy) {
  if (s <= 1.0001) return [qx, qy];
  const [dx, dy] = zoomD(s, z, fx, fy, cx, cy);
  return [dx + s * qx, dy + s * qy];
}

/** Any content dict (HOOK hero, BEFORE_AFTER side) as a pane: terminal | diff | code | image. */
function contentPane(ctx, F, T, c, o) {
  const kind = (c && c.kind) || (c && (c.asset || c.path) && c.w ? 'image' : 'code');
  if (kind === 'image') {
    const fs = o.fs || 24;
    const mp = mediaPane(ctx, F, T, c, { fs, maxW: o.maxW, maxH: o.maxH, cx: o.cx, cy: o.cy, phosphor: o.phosphor, title: o.title });
    const st = { ascii: o.t0, dither: o.t0 + 0.3, real: o.t0 + 0.6, scan: 0.16 };
    if (o.title) mp.pre.innerHTML = box(o.title, mp.inner, Array.from({ length: mp.rows }, () => txt('', '')), { right: fit(prettyUrl(c.url || ''), 30) }).join('\n');
    return { els: [mp.wrap], w: mp.w, h: mp.h, x: mp.x, y: mp.y, cues: [{ t: o.t0, sfx: 'appear', gain_db: -12 }], update: (t) => mp.update(t, st), mp, kind };
  }
  const maxCols = Math.floor(o.maxW / ((o.fs || 24) * ADV)) - 4;
  let pane;
  if (kind === 'terminal') pane = termPane(c, { inner: Math.min(maxCols, Math.max(30, len(String(c.cmd || '')) + 2, ...(c.output || []).map((s) => len(String(s)) + 8))), t0: o.t0, maxType: o.fast ? 0.5 : 1.0, per: 0.05, wrapCmd: true, maxRows: o.maxRows || 8, title: o.title, finalPrompt: false });
  else if (kind === 'diff') pane = diffPane(c, { inner: maxCols, t0: o.t0, maxRows: o.maxRows || 10 });
  else pane = codePane(c, { inner: maxCols, t0: o.t0, maxRows: o.maxRows || 10, focusAt: o.t0 + 0.7 });
  const fs = o.fs || 24;
  const pw = pane.cols * fs * ADV, ph = pane.rows * lineH(fs);
  const x = o.cx - pw / 2, y = o.cy - ph / 2;
  T.mount(pane.el, x, y, fs);
  if (o.title && kind !== 'terminal') pane.el.dataset.title = o.title;
  return { els: [pane.el], w: pw, h: ph, x, y, cues: pane.cues, update: (t) => pane.update(t), pane, kind };
}

// --------------------------------------------------------------------------------------------- HOOK
tubeScene('kit:terminal/HOOK', {
  describe: 'Scroll-stopper: the tube powers on (dot -> line -> picture, degauss wobble), the hero artefact appears in a pane (a product capture resolves ASCII -> dither -> real; a test run prints with its PASS block) and a <= 6 word headline types in VT323.',
  powerOn: true,
  params: { hero: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...block data}' } },
  build(ctx, p, F, T) {
    const L = F.portrait, B = contentBox(F, T);
    const hero = p.hero || {};
    const label = String(p.label || '').trim();
    const labZ = L ? 84 : 92;
    const labLines = label ? wrap('> ' + label, Math.floor((B.w) / (labZ * 0.42)), '  ') : [];
    const labH = labLines.length * labZ * 1.0 + (label ? 30 : 0);
    const lab = label ? T.disp(B.x, B.y + (L ? 10 : -6), labZ, 'h') : null;
    if (lab) { lab.style.width = `${B.w}px`; lab.style.whiteSpace = 'pre'; }
    const ty = typing(labLines.join('\n'), 0.55, { cps: 32, maxDur: 1.0, seed: 1 });
    const kind = hero.kind || (hero.w ? 'image' : 'code');
    const fs = kind === 'image' ? (L ? 22 : 24) : L ? 30 : 40;
    const avail = { w: B.w, h: B.h - labH };
    const pane = contentPane(ctx, F, T, hero, { fs, maxW: avail.w, maxH: avail.h, cx: F.W / 2, cy: B.y + labH + avail.h / 2,
      t0: 0.45, fast: true, phosphor: p.phosphor, maxRows: L ? 14 : 10 });
    T.bar('', '');
    return {
      cues: [...pane.cues, ...(label ? ty.cues({ every: 4, max: 10, gain_db: -16 }) : [])],
      render(t) {
        pane.update(t);
        if (lab) {
          const n = ty.count(t);
          const s = [...ty.chars].slice(0, n).join('').split('\n');
          lab.set(s.map((l, i) => (i === 0 ? sp('d', l.slice(0, 2)) + esc(l.slice(2)) : esc(l)) + (i === s.length - 1 && t > 0.45 ? `<span class="c${n < ty.n || blink(t - ty.end) ? '' : ' off'}" style="width:.45em"> </span>` : '')).join('\n'));
        }
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- SCREEN
function screenBuild(ctx, p, F, T, feature) {
  const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
  const img = p.image || {};
  const fs = L ? 22 : 24;
  const mp = mediaPane(ctx, F, T, img, { fs, maxW: B.w, maxH: B.h, cx: F.W / 2, cy: B.y + B.h / 2, phosphor: p.phosphor, parent: T.clip(B) });
  const st = { ascii: 0.12, dither: 0.42, real: 0.72, scan: 0.16 };
  const bb = Array.isArray(p.bbox) && p.bbox.length === 4 ? p.bbox.map(Number) : [0.1, 0.1, 0.8, 0.8];
  const A = mp.area;
  const bx = A.x + bb[0] * A.w, by = A.y + bb[1] * A.h, bw = bb[2] * A.w, bh = bb[3] * A.h;
  const fx = bx + bw / 2, fy = by + bh / 2;
  const cx = F.W / 2, cy = B.y + B.h / 2;
  const z = clamp(Math.min((B.w * 0.86) / bw, (B.h * 0.8) / bh), 1.4, 2.0);
  const tz = clamp(dur * 0.32, 1.25, 1.9);
  const cues = [{ t: st.ascii, sfx: 'appear', gain_db: -12 }, { t: tz, sfx: 'move', gain_db: -12 }];
  const P = phosphorOf(p);
  let feat = null;
  if (feature) {
    const click = Array.isArray(p.click) && p.click.length === 2 ? p.click.map(Number) : [bb[0] + bb[2] / 2, bb[1] + bb[3] / 2];
    const qx = A.x + click[0] * A.w, qy = A.y + click[1] * A.h;
    const syncClick = Number(p._sync && p._sync.click);
    const tClick = Number.isFinite(syncClick) && syncClick > tz + 0.5 && syncClick < dur - 0.6 ? syncClick : Math.min(tz + 1.1, dur - 0.9);
    const ptr = pointer(F, P, L ? 5 : 6);
    T.scr.appendChild(ptr);
    const flash = h('div', '');
    flash.style.cssText = `position:absolute;left:${bx}px;top:${by}px;width:${bw}px;height:${bh}px;background:#fff;mix-blend-mode:difference;`;
    const ring = h('div', '');
    ring.style.cssText = `position:absolute;left:${bx - 8}px;top:${by - 8}px;width:${bw + 16}px;height:${bh + 16}px;border:3px solid ${P.hot};box-shadow:0 0 18px rgba(${P.rgb.join(',')},.6), inset 0 0 18px rgba(${P.rgb.join(',')},.25);`;
    mp.wrap.append(flash, ring);
    const name = String(p.feature || p.label || '').trim();
    const tagFs = L ? 30 : 34;
    const tag = T.pre(0, 0, tagFs);
    const tagTy = typing(name, tClick + 0.25, { cps: 30, maxDur: 0.8, seed: 8 });
    cues.push({ t: tClick, sfx: 'click', gain_db: -4 });
    feat = { qx, qy, tClick, ptr, flash, ring, tag, tagTy, tagFs, name };
  }
  T.bar(feature ? 'feature' : 'screen', feature ? String(p.feature || '') : prettyUrl(img.url || ''));
  return {
    cues,
    render(t) {
      mp.update(t, st);
      const s = zoomSteps(t, tz, z, 3, 0.11);
      css(mp.wrap, { transform: zoomCss(s, z, fx, fy, cx, cy) });
      if (!feat) return;
      const f = feat;
      const [sx, sy] = zoomPt(s, z, fx, fy, cx, cy, f.qx, f.qy);
      const arrive = f.tClick - 0.15, leave = f.tClick - 0.85;
      const u = seg(t, leave, arrive, ease.inOutCubic);
      const px = lerp(F.W - T.M.r - 60, sx, u), py = lerp(F.H * 0.86, sy, u) - Math.sin(Math.PI * u) * 60;
      const dip = t >= f.tClick && t < f.tClick + 0.1 ? 4 : 0;
      css(f.ptr, { left: `${px.toFixed(1)}px`, top: `${(py + dip).toFixed(1)}px`, visibility: t >= leave - 0.05 ? 'visible' : 'hidden' });
      css(f.flash, { visibility: t >= f.tClick && t < f.tClick + 0.1 ? 'visible' : 'hidden' });
      css(f.ring, { visibility: t >= f.tClick + 0.1 && (t > f.tClick + 0.5 || Math.floor((t - f.tClick) * 12) % 2 === 0) ? 'visible' : 'hidden' });
      // feature tag in screen space, above the ring
      const [rx, ry] = zoomPt(s, z, fx, fy, cx, cy, bx - 8, by - 8);
      const n = f.tagTy.count(t);
      const shown = [...f.name].slice(0, n).join('');
      css(f.tag, { left: `${Math.max(T.M.l, rx).toFixed(1)}px`, top: `${Math.max(T.M.t + 40, ry - lineH(f.tagFs) - 14).toFixed(1)}px` });
      f.tag.set(t >= f.tClick + 0.2 && f.name ? sp('ih', ' \u25b8 ' + shown + ' ') + cursor(n < f.tagTy.n || blink(t - f.tagTy.end)) : '');
    },
  };
}

tubeScene('kit:terminal/SCREEN', {
  describe: 'Real screenshot in a box-drawn pane: it resolves ASCII -> phosphor dither -> the real image with a raster sweep, then zooms to the focus box in discrete font-size steps (>= 1.4x).',
  params: { image: IMAGE_DOC, bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'focus box [x,y,w,h] as image fractions' } },
  build(ctx, p, F, T) { return screenBuild(ctx, p, F, T, false); },
});

tubeScene('kit:terminal/FEATURE', {
  describe: 'Product capture + one feature: resolve, step-zoom to the region, the pixel-art pointer arrives and clicks (inverse-video flash, relay click), a hot frame and the inverse feature tag type in.',
  params: {
    image: IMAGE_DOC, feature: { type: 'string', default: '', doc: 'feature name (<= 6 words), typed as the tag' },
    bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'feature region [x,y,w,h] (image fractions)' },
    click: { type: 'array', default: [0.5, 0.5], doc: 'click point [x,y] (image fractions)' },
  },
  build(ctx, p, F, T) { return screenBuild(ctx, p, F, T, true); },
});

// --------------------------------------------------------------------------------------------- SCROLL
tubeScene('kit:terminal/SCROLL', {
  describe: 'Full-page capture in a pane: the first screen resolves from phosphor dither to real, then the page pages down like `less` in whole-line jumps; a block-character scrollbar rides the pane edge.',
  params: { image: IMAGE_DOC, scroll: { type: 'array', default: [0, 1], doc: '[from, to] scroll fractions' } },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
    const img = p.image || {};
    const fs = L ? 22 : 24, adv = fs * ADV, lh = lineH(fs);
    const iw = Number(img.w) || 1440, ihN = Number(img.h) || 2400;
    // viewport: the pane fills the content box; the image is shown at the pane's inner width
    const maxW = L ? B.w : Math.min(B.w, 1300);
    const inner = Math.floor((maxW - 4 * adv) / adv);
    const rows = Math.floor((B.h - 2 * lh) / lh);
    const dw = inner * adv, viewH = rows * lh;
    const sc = dw / iw, natural = ihN * sc;
    const sc0 = clamp(Number((p.scroll || [0, 1])[0]) || 0), sc1 = clamp(Number((p.scroll || [0, 1])[1] ?? 1));
    const range = Math.max(0, natural - viewH);
    const y0 = range * sc0;
    const mp = mediaPane(ctx, F, T, img, { fs, maxW: (inner + 4) * adv, maxH: (rows + 2) * lh, cx: F.W / 2, cy: B.y + B.h / 2,
      phosphor: p.phosphor, viewH: viewH / sc, cropY: y0 / natural });
    // the full page (real) that scrolls after the resolve
    const A = mp.area;
    const clip = h('div', '');
    clip.style.cssText = `position:absolute;left:${A.x}px;top:${A.y}px;width:${A.w}px;height:${A.h}px;overflow:hidden;visibility:hidden;`;
    const doc = F.el.ownerDocument;
    const cap = Math.min(1, 4096 / (natural * F.k));
    const full = doc.createElement('canvas');
    full.width = Math.max(1, Math.round(A.w * F.k * cap)); full.height = Math.max(1, Math.round(natural * (A.w / dw) * F.k * cap));
    full.style.cssText = `position:absolute;left:0;top:0;width:${A.w}px;height:${natural * (A.w / dw)}px;`;
    const im = mp.m.media.image;
    if (im) { const g = full.getContext('2d'); g.imageSmoothingQuality = 'high'; g.drawImage(im, 0, 0, full.width, full.height); }
    clip.appendChild(full);
    mp.wrap.appendChild(clip);
    const thumb = h('pre', 'tm-pre h');
    const tx = mp.x + (mp.inner + 3) * adv;
    thumb.style.cssText = `left:${tx}px;top:${mp.y + lh}px;font-size:${fs}px;line-height:${lh}px;background:transparent;`;
    mp.wrap.appendChild(thumb);
    const st = { ascii: 0.1, dither: 0.38, real: 0.66, scan: 0.15 };
    const tS = 1.05, tE = Math.max(tS + 0.8, dur - 0.6);
    const step = lh * 2; // page in two-line jumps
    T.bar('scroll', prettyUrl(img.url || ''));
    const cues = [{ t: st.ascii, sfx: 'appear', gain_db: -12 }];
    for (let i = 0; i < 6; i++) cues.push({ t: tS + i * (tE - tS) / 6, sfx: 'type', gain_db: -16 });
    return {
      cues,
      render(t) {
        mp.update(t, st);
        const u = seg(t, tS, tE, ease.inOutQuad);
        const off = y0 + (range * sc1 - y0) * u;
        const q = Math.round(off / step) * step;
        const scrolling = t >= tS;
        css(clip, { visibility: scrolling ? 'visible' : 'hidden' });
        css(full, { transform: `translate3d(0,${(-Math.min(range, q) * (A.w / dw)).toFixed(1)}px,0)` });
        const nT = Math.max(1, Math.round(rows * viewH / Math.max(viewH, natural)));
        const pos = Math.round((rows - nT) * (range > 0 ? Math.min(range, q) / range : 0));
        thumb.textContent = Array.from({ length: rows }, (_, i) => (i >= pos && i < pos + nT ? '\u2588' : ' ')).join('\n');
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- BEFORE_AFTER
tubeScene('kit:terminal/BEFORE_AFTER', {
  describe: 'Two panes, before/ and after/: the before state prints (red run, old screen), then the after pane prints beside it; pane focus moves to after (before dims to the background).',
  params: {
    before: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
    after: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
  },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
    const gap = L ? 50 : 56;
    const fs = L ? 24 : 24;
    const side = L ? { w: B.w, h: (B.h - gap) / 2 } : { w: (B.w - gap) / 2, h: B.h };
    const tA = 0.25, tB = clamp(dur * 0.36, 1.3, 2.2);
    const mk = (c, i, t0, title) => contentPane(ctx, F, T, c || {}, { fs, maxW: side.w, maxH: side.h,
      cx: L ? F.W / 2 : B.x + side.w / 2 + i * (side.w + gap), cy: L ? B.y + side.h / 2 + i * (side.h + gap) : B.y + B.h / 2,
      t0, fast: true, phosphor: p.phosphor, title, maxRows: L ? 9 : 12 });
    const A = mk(p.before, 0, tA, 'before/');
    const Bp = mk(p.after, 1, tB, 'after/');
    const focusAt = tB + 0.9;
    T.bar('before / after', '');
    return {
      cues: [...A.cues, ...Bp.cues, { t: tB, sfx: 'cut', gain_db: -10 }],
      render(t) {
        A.update(t);
        Bp.update(t);
        const dim = seg(t, focusAt, focusAt + 0.05);
        for (const el of A.els) css(el, { opacity: (1 - 0.55 * dim).toFixed(3), filter: dim > 0 ? 'saturate(.6)' : 'none' });
        for (const el of Bp.els) css(el, { visibility: t >= tB - 0.02 ? 'visible' : 'hidden' });
      },
    };
  },
});

export { row, wrap };
