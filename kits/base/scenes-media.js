// Showreel kits/base — product media scenes: HOOK, SCREEN, FEATURE, SCROLL, BEFORE_AFTER, MONTAGE.

import { defineDomScene, flatCam, place, fitZoom } from './scene.js';
import { h, css, fitSize } from './dom.js';
import { seg, ease, pchip, clamp, lerp } from './motion.js';
import { codeBlock, diffBlock } from './code.js';
import { termBlock, termFont, termWidth } from './term.js';
import { browserBlock, cursorBlock, ringBlock } from './media.js';
import { toolCard } from './cards.js';
import { kineticLine, riseIn } from './type.js';
import { COMMON, panelIn } from './scenes-panels.js';

const IMAGE_DOC = { type: 'image', default: null, doc: '{asset, path, w, h, url, page_title, full_page} (asset = film asset name)' };

/**
 * Build the right block for a self-describing content dict (HOOK hero, BEFORE_AFTER sides):
 * kind image | terminal | diff | code. o: {width, maxH, fast (everything revealed early), t0}
 */
export function contentBlock(ctx, c, o = {}) {
  const kind = (c && c.kind) || (c && (c.path || c.asset) && (c.w || c.asset) ? 'image' : 'code');
  let width = o.width || 1300;
  const t0 = o.t0 ?? 0;
  if (kind === 'image') {
    const img = c.image || c;
    const b = browserBlock(ctx, img, { width, maxViewH: o.maxH ? o.maxH - 58 : undefined });
    return { ...b, kind, update() {}, cues: [] };
  }
  if (kind === 'terminal') {
    const n = (c.output || []).length;
    const fs = o.fontSize || termFont(c, o.portrait);
    if (o.hug) width = Math.min(width, termWidth(c, fs, o.portrait));
    const b = termBlock(c, { width, fontSize: fs, typeAt: [t0, t0 + (o.fast ? 0.35 : 0.9)],
      streamAt: [t0 + (o.fast ? 0.4 : 1.1), t0 + (o.fast ? 0.4 : 1.1) + Math.min(1.0, n * (o.fast ? 0.06 : 0.12))],
      badgeAt: o.badgeAt, wrap: o.wrap, maxRows: o.maxRows || 10 });
    return { ...b, kind };
  }
  if (kind === 'diff') {
    const b = diffBlock(c, { width, fontSize: o.fontSize || 24, reveal: [t0, t0 + (o.fast ? 0.6 : 1.4)] });
    return { ...b, kind };
  }
  const b = codeBlock(c, { width, fontSize: o.fontSize || 24, reveal: [t0, t0 + (o.fast ? 0.7 : 1.6)], caret: false });
  return { ...b, kind: 'code' };
}

// ------------------------------------------------------------------------------------- HOOK
defineDomScene('kit:base/HOOK', {
  describe: 'Scroll-stopper: the best real artefact (product capture, green test run, diff) tilts up out of a blur with a <= 6 word headline.',
  params: { ...COMMON, hero: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...block data}' } },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const hero = p.hero || {};
    const label = String(p.label || '').trim();
    const L = F.portrait;
    const width = L ? 940 : (label ? 1180 : 1440);
    const maxH = L ? 1100 : 800;
    const b = contentBlock(ctx, hero, { width, maxH, fast: true, t0: 0.05, badgeAt: Math.min(1.0, dur * 0.5), wrap: L, portrait: L, hug: true });
    F.cam.appendChild(b.el);
    const bx = L ? (F.W - b.w) / 2 : label ? F.W - F.safe.r - b.w + 30 : (F.W - b.w) / 2;
    const by = L ? 600 + (1150 - Math.min(b.h, 1150)) / 2 : (F.H - b.h) / 2 + 10;
    place(b.el, bx, by);
    let line = null;
    if (label) {
      line = kineticLine(label, { className: 'srb-h1', emphasis: 'auto' });
      const fs = L ? 92 : 96;
      line.el.style.cssText = `position:absolute;font-size:${fs}px;width:${L ? 840 : 560}px;` +
        (L ? `left:${F.safe.l}px;top:${300}px;` : `left:${F.safe.l}px;top:${F.H / 2 - fs * 1.2}px;`);
      F.ov.appendChild(line.el);
    }
    const zw = Math.min(1, fitZoom(F, b.w, b.h, L ? 1.1 : 1.05));
    return {
      cues: [...(b.cues || []), ...(label ? [{ t: 0.3, sfx: 'appear', gain_db: -12 }] : [])],
      render(t) {
        b.update(t);
        panelIn(b.el, t, -0.35, 0.95, { tilt: 22, rise: 80, blur: 10 });
        if (line) line.update(t, 0.12, { stagger: 0.08 });
        const u = seg(t, 0, dur, ease.outCubic);
        flatCam(F, t, F.W / 2, F.H / 2, zw * lerp(1, 1.05, u));
      },
    };
  },
});

/** Shared camera for a browser frame: wide establish, push to the bbox, hold with drift. */
/**
 * Camera for a browser frame inside a screen region {x, y, w, h} (reference px; default = safe area):
 * wide establish, push to the bbox (>= 1.4x the establish zoom), hold with drift. Returns t -> [cx, cy, z].
 * Use with flatCam(..., {ax: region centre x, ay: region centre y}).
 */
function screenCam(F, bx, by, b, bbox, dur, tPush, o = {}) {
  const R = o.region || { x: F.safe.l, y: F.safe.t, w: F.W - F.safe.l - F.safe.r, h: F.H - F.safe.t - F.safe.b };
  const zw = Math.min(o.maxWide || 1, (R.w * 0.98) / b.w, (R.h * 0.98) / b.h);
  const r = b.rect(bbox);
  const zp = clamp(Math.min((R.w * 0.92) / r.w, (R.h * 0.88) / r.h), Math.max(zw * 1.4, o.minPush || 0), o.maxZoom || 2.6);
  const cx = bx + r.x + r.w / 2, cy = by + r.y + r.h / 2;
  return pchip([[0, [bx + b.w / 2, by + b.h / 2, zw * 0.97]], [tPush, [bx + b.w / 2, by + b.h / 2 + 4, zw]],
    [tPush + 0.75, [cx, cy, zp]], [dur + 1, [cx + 5, cy + 5, zp * 1.025]]]);
}

function browserWidth(F, m, maxW, maxH) {
  const aspect = m.w / m.h;
  return Math.round(Math.min(maxW, (maxH - 58) * aspect));
}

// ------------------------------------------------------------------------------------- SCREEN
defineDomScene('kit:base/SCREEN', {
  describe: 'Real screenshot in a browser frame: establish wide, push to the focus box (>= 1.4x), hold with drift.',
  params: { ...COMMON, image: IMAGE_DOC, bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'focus box [x,y,w,h] as image fractions' } },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const img = p.image || {};
    const L = F.portrait;
    const width = browserWidth(F, { w: img.w || 1440, h: img.h || 900 }, L ? 960 : 1560, L ? 1300 : 900);
    const b = browserBlock(ctx, img, { width, maxViewH: L ? 1240 : 840 });
    F.cam.appendChild(b.el);
    const bx = (F.W - b.w) / 2, by = (F.H - b.h) / 2;
    place(b.el, bx, by);
    const tPush = clamp(dur * 0.28, 1.0, 1.6);
    const cam = screenCam(F, bx, by, b, p.bbox || [0.1, 0.1, 0.8, 0.8], dur, tPush);
    return {
      cues: [{ t: tPush + 0.05, sfx: 'move', gain_db: -12 }],
      render(t) {
        panelIn(b.el, t);
        const [cx, cy, z] = cam(t);
        flatCam(F, t, cx, cy, z, { lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- FEATURE
defineDomScene('kit:base/FEATURE', {
  describe: 'Product frame + one feature: push to the region, the cursor arrives, pauses, clicks (ripple), an accent ring and the feature name land.',
  params: {
    ...COMMON, image: IMAGE_DOC,
    feature: { type: 'string', default: '', doc: 'feature name (<= 6 words), shown as the headline' },
    bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'feature region [x,y,w,h] (image fractions)' },
    click: { type: 'array', default: [0.5, 0.5], doc: 'click point [x,y] (image fractions)' },
  },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const img = p.image || {};
    const L = F.portrait;
    const width = browserWidth(F, { w: img.w || 1440, h: img.h || 900 }, L ? 960 : 1480, L ? 1200 : 860);
    const b = browserBlock(ctx, img, { width, maxViewH: L ? 1140 : 800 });
    F.cam.appendChild(b.el);
    const bx = (F.W - b.w) / 2, by = (F.H - b.h) / 2;
    place(b.el, bx, by);
    const bbox = p.bbox || [0.1, 0.1, 0.8, 0.8];
    const click = p.click || [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2];
    const tPush = clamp(dur * 0.2, 0.9, 1.3);
    const sync = Number(p._sync && p._sync.click);
    const press = Number.isFinite(sync) && sync > tPush + 0.8 && sync < dur - 0.6 ? sync : clamp(dur * 0.45, tPush + 1.2, Math.max(tPush + 1.2, dur - 1.4));
    const arrive = press - 0.62;
    const name = String(p.feature || p.label || '').trim();
    // media region: right of the label column (landscape) / above the label band (portrait)
    const R = !name ? null : L ? { x: 60, y: F.safe.t, w: F.W - 120, h: F.H - F.safe.t - F.safe.b - 330 }
      : { x: 800, y: F.safe.t, w: F.W - 800 - 70, h: F.H - F.safe.t - F.safe.b };
    const cam = screenCam(F, bx, by, b, bbox, dur, tPush, { minPush: 1.0, maxZoom: L ? 1.9 : 2.2, region: R || undefined });
    const ax = R ? R.x + R.w / 2 : F.W / 2, ay = R ? R.y + R.h / 2 : F.H / 2;
    const ring = ringBlock();
    const [px, py] = b.pt(click[0], click[1]);
    const cur = cursorBlock({ from: [px + b.w * 0.22, py + b.h * 0.26], to: [px, py], arrive, press, travel: 0.75, size: 1.35 });
    b.view.appendChild(ring.el);
    for (const e of cur.els) b.el.appendChild(e);
    const rRect = b.rect(bbox);
    rRect.y -= b.chromeH;
    let line = null, eyebrow = null;
    if (name) {
      const box = h('div', 'srb-abs');
      eyebrow = h('div', 'srb-eyebrow', null, [h('i'), 'Feature']);
      line = kineticLine(name, { className: 'srb-h1', emphasis: 'auto' });
      const fs = L ? 84 : fitSize(name, 600, 3, 92, 64, 0.5);
      line.el.style.cssText = `font-size:${fs}px;margin-top:26px;max-width:${L ? 840 : 620}px;`;
      box.append(eyebrow, line.el);
      box.style.cssText = L ? `left:${F.safe.l}px;top:${F.H - F.safe.b - 300}px;`
        : `left:${F.safe.l}px;top:0;height:${F.H}px;display:flex;flex-direction:column;justify-content:center;`;
      F.ov.append(box);
    }
    return {
      cues: [{ t: tPush + 0.05, sfx: 'move', gain_db: -12 }, ...cur.cues],
      render(t) {
        panelIn(b.el, t);
        cur.update(t);
        ring.update(t, rRect, press + 0.12);
        const [cx, cy, z] = cam(t);
        flatCam(F, t, cx, cy, z, { ax, ay });
        if (line) {
          riseIn(eyebrow, t, 0.3);
          line.update(t, 0.4, { stagger: 0.08 });
        }
      },
    };
  },
});

// ------------------------------------------------------------------------------------- SCROLL
defineDomScene('kit:base/SCROLL', {
  describe: 'Smooth scroll through a full-page product capture inside a browser frame.',
  params: { ...COMMON, image: IMAGE_DOC, scroll: { type: 'array', default: [0, 1], doc: '[from, to] scroll fractions' } },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const img = p.image || {};
    const L = F.portrait;
    const width = L ? 940 : 1320;
    const b = browserBlock(ctx, img, { width, viewH: L ? 1260 : 850 });
    F.cam.appendChild(b.el);
    const bx = (F.W - b.w) / 2, by = (F.H - b.h) / 2;
    place(b.el, bx, by);
    const [s0, s1] = (p.scroll || [0, 1]).map(Number);
    const t0 = 0.7, t1 = Math.max(t0 + 1, dur - 0.7);
    const zw = Math.min(1.08, fitZoom(F, b.w, b.h, 1.0));
    return {
      cues: [{ t: t0, sfx: 'move', gain_db: -14 }],
      render(t) {
        panelIn(b.el, t);
        b.setScroll(lerp(s0, s1, seg(t, t0, t1, ease.inOutCubic)));
        const u = seg(t, 0, dur, ease.inOutCubic);
        flatCam(F, t, F.W / 2, F.H / 2, zw * lerp(1, 1.04, u), { roll: lerp(0.3, -0.3, u), lift: F.caps ? 40 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- BEFORE_AFTER
defineDomScene('kit:base/BEFORE_AFTER', {
  describe: 'The money shot: before and after in one frame; a handle wipes across to reveal the after state.',
  params: {
    ...COMMON,
    before: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
    after: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
  },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const L = F.portrait;
    const width = L ? 940 : 1360;
    const maxH = L ? 1150 : 820;
    const wipeAt = clamp(dur * 0.42, 1.2, dur - 1.4);
    const bb = contentBlock(ctx, p.before || {}, { width, maxH, fast: true, t0: 0.05, badgeAt: 0.6, wrap: L, portrait: L });
    const ab = contentBlock(ctx, p.after || {}, { width, maxH, fast: true, t0: wipeAt + 0.2, badgeAt: wipeAt + 0.6, wrap: L, portrait: L });
    const slotH = Math.max(bb.h, ab.h);
    const slot = h('div', 'srb-abs');
    const sx = (F.W - width) / 2, sy = (F.H - slotH) / 2 + (L ? 0 : 20);
    slot.style.cssText = `left:${sx}px;top:${sy}px;width:${width}px;height:${slotH}px;`;
    const wrapA = h('div', 'srb-abs');
    wrapA.style.cssText = `left:0;top:0;width:${width}px;height:${slotH}px;`;
    place(bb.el, 0, (slotH - bb.h) / 2);
    place(ab.el, 0, (slotH - ab.h) / 2);
    wrapA.appendChild(ab.el);
    const handle = h('div', 'srb-handle');
    const knob = h('div', 'srb-knob', { text: '\u2194' });
    handle.appendChild(knob);
    handle.style.top = '-24px';
    handle.style.bottom = '-24px';
    slot.append(bb.el, wrapA, handle);
    F.cam.appendChild(slot);
    const tagB = h('div', 'srb-tag', { text: 'Before' });
    const tagA = h('div', 'srb-tag after', { text: 'After' });
    tagB.style.cssText = `position:absolute;left:${sx}px;top:${sy - 70}px;`;
    tagA.style.cssText = `position:absolute;left:${sx}px;top:${sy - 70}px;`;
    F.cam.append(tagB, tagA);
    const zw = Math.min(1, fitZoom(F, width, slotH + 80, 1.0));
    const cues = [...(bb.cues || []).filter((c) => c.sfx !== 'pass'), { t: wipeAt, sfx: 'move', gain_db: -10 },
      ...(ab.cues || []).filter((c) => c.sfx === 'pass' || c.sfx === 'appear')];
    return {
      cues,
      render(t) {
        bb.update(t); ab.update(t);
        panelIn(slot, t);
        const w = seg(t, wipeAt, wipeAt + 0.85, ease.inOutCubic);
        const x = w * width;
        css(wrapA, { clipPath: `inset(-40px ${(width - x).toFixed(2)}px -40px -40px)` });
        css(wrapA, { visibility: w > 0 ? 'visible' : 'hidden' });
        css(bb.el, { visibility: w < 1 ? 'visible' : 'hidden' });
        css(handle, { left: `${x.toFixed(2)}px`, opacity: (seg(t, wipeAt - 0.25, wipeAt) * (1 - seg(t, wipeAt + 1.0, wipeAt + 1.3))).toFixed(3) });
        riseIn(tagB, t, 0.2);
        css(tagB, { visibility: w < 0.5 ? 'visible' : 'hidden' });
        css(tagA, { opacity: seg(t, wipeAt + 0.4, wipeAt + 0.6).toFixed(3), transform: `scale(${(0.85 + 0.15 * seg(t, wipeAt + 0.4, wipeAt + 0.8, ease.outBack)).toFixed(4)})` });
        const u = seg(t, 0, dur, ease.inOutCubic);
        flatCam(F, t, F.W / 2 + (w - 0.5) * 40, F.H / 2 - 30, zw * lerp(1, 1.04, u), { lift: F.caps ? 40 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- MONTAGE
defineDomScene('kit:base/MONTAGE', {
  describe: "Breadth of the agent's work: real tool calls as cards on a rail; the camera whips card to card on the beat.",
  params: { ...COMMON, items: { type: 'array', default: [], doc: '[{id, t, kind, tool, arg, clipped}] 3-16 tool calls' } },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const L = F.portrait;
    const items = (p.items || []).slice(0, 16);
    const n = Math.max(1, items.length);
    const cw = L ? 860 : 700, chh = L ? 210 : 250, gap = L ? 48 : 60;
    const rail = h('div', 'srb-abs');
    F.cam.appendChild(rail);
    const pos = items.map((it, i) => {
      const c = toolCard(it, { width: cw, height: chh });
      // landscape: two staggered rows marching right; portrait: one column marching down
      const x = L ? (F.W - cw) / 2 : 260 + i * (cw * 0.55 + gap * 0.45);
      const y = L ? 300 + i * (chh + gap) : F.H / 2 - chh - 24 + (i % 2) * (chh + 48);
      place(c.el, x, y);
      rail.appendChild(c.el);
      return { el: c.el, x: x + cw / 2, y: y + chh / 2 };
    });
    const step = dur / n;
    const keysCam = [];
    pos.forEach((q, i) => {
      const ti = i * step;
      const cx = L ? F.W / 2 : q.x, cy = L ? q.y + 80 : F.H / 2;
      keysCam.push([ti, [cx, cy]]);
      keysCam.push([ti + Math.min(step * 0.6, 0.45), [cx + (L ? 0 : 12), cy + (L ? 10 : 0)]]);
    });
    if (!keysCam.length) keysCam.push([0, [F.W / 2, F.H / 2]]);
    keysCam.sort((a2, b2) => a2[0] - b2[0]);
    const cam = pchip(keysCam);
    const cues = pos.map((q, i) => ({ t: i * step + 0.02, sfx: 'appear', gain_db: -16 }));
    const zoom = 1.0;
    return {
      cues,
      render(t) {
        const cur = clamp(Math.floor((t + 0.05) / step), 0, n - 1);
        pos.forEach((q, i) => {
          const ti = (i - 2) * step;
          const u = seg(t, ti - 0.1, ti + 0.4, ease.outQuint);
          const on = i === cur;
          const dist = Math.abs(i - cur);
          css(q.el, { opacity: (u * (on ? 1 : dist === 1 ? 0.8 : 0.5)).toFixed(3),
            transform: u >= 1 ? `scale(${on ? 1.04 : 1})` : `perspective(1600px) rotateX(${((1 - u) * 75).toFixed(3)}deg) translate(0, ${((1 - u) * 30).toFixed(2)}px) scale(${on ? 1.04 : 1})`,
            transformOrigin: '50% 100%', zIndex: on ? '5' : '1' });
          q.el.classList.toggle('on', on);
        });
        const [cx, cy] = cam(t);
        // motion blur stand-in during whips: velocity from the curve itself (pure in t)
        const [cx2, cy2] = cam(t + 1 / 60);
        const v = Math.hypot(cx2 - cx, cy2 - cy) * 60;
        css(rail, { filter: v > 900 ? `blur(${Math.min(3, (v - 900) / 600).toFixed(2)}px)` : 'none' });
        flatCam(F, t, cx, cy, zoom, { lift: F.caps ? 40 : 0 });
      },
    };
  },
});
