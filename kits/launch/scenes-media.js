// Hype kit "launch" — product media scenes on the table: HOOK, SCREEN, FEATURE, SCROLL, BEFORE_AFTER, MONTAGE.

import { launchScene, camTrack, fitRect, nodeIn, pushTrack, panelWires, productScale } from './stage.js';
import { h, css, fitSize } from '../base/dom.js';
import { clamp, lerp, seg, ease } from '../base/motion.js';
import { browserBlock, cursorBlock, ringBlock } from '../base/media.js';
import { toolCard } from '../base/cards.js';
import { kineticLine, riseIn } from '../base/type.js';
import { contentBlock } from '../base/scenes-media.js';

const IMAGE_DOC = { type: 'image', default: null, doc: '{asset, path, w, h, url, page_title, full_page}' };

/** Browser width so the screenshot fits a box (keeps the image aspect). */
function bw(img, maxW, maxH) {
  const w = Number(img.w) || 1440, hh = Number(img.h) || 900;
  return Math.round(Math.min(maxW, ((maxH - 66) * w) / hh));
}

/** Headline column (landscape, left) or band (portrait, bottom) in screen space. Returns {update(t)}. */
function headline(F, text, o = {}) {
  const L = F.portrait;
  const box = h('div', 'srb-abs');
  const eyebrow = o.eyebrow ? h('div', 'srb-eyebrow', null, [h('i'), o.eyebrow]) : null;
  const line = kineticLine(text, { className: 'srb-h1', emphasis: o.emphasis ?? 'auto' });
  const fs = L ? fitSize(text, 840, 3, 92, 66, 0.5) : fitSize(text, o.colW || 620, 4, 96, 66, 0.5);
  line.el.style.cssText = `font-size:${fs}px;margin-top:${eyebrow ? 26 : 0}px;max-width:${L ? 840 : o.colW || 620}px;`;
  if (eyebrow) box.appendChild(eyebrow);
  box.appendChild(line.el);
  if (o.scrim !== false) {
    const scrim = h('div', 'slw-scrim');
    scrim.style.cssText = L ? `left:0;right:0;bottom:0;height:${F.H - (o.top ?? F.H - F.safe.b - 320) + 140}px;background:linear-gradient(180deg,rgba(10,11,13,0),rgba(10,11,13,.86) 34%,rgba(10,11,13,.94));`
      : 'left:0;top:0;bottom:0;width:980px;background:linear-gradient(90deg,rgba(10,11,13,.95) 0%,rgba(10,11,13,.9) 52%,rgba(10,11,13,0) 100%);';
    F.ov.appendChild(scrim);
  }
  box.style.cssText = L ? `left:${F.safe.l}px;top:${o.top ?? F.H - F.safe.b - 320}px;`
    : `left:${F.safe.l}px;top:0;height:${F.H}px;display:flex;flex-direction:column;justify-content:center;`;
  F.ov.appendChild(box);
  return { update(t, t0 = 0.3) { if (eyebrow) riseIn(eyebrow, t, t0 - 0.1); line.update(t, t0, { stagger: 0.08 }); } };
}

/** Frame region for media beside a headline column / above a band. */
function mediaRegion(F, withHead) {
  if (!withHead) return { x: F.safe.l - 40, y: F.safe.t - 20, w: F.W - F.safe.l - F.safe.r + 80, h: F.H - F.safe.t - F.safe.b + 40 };
  return F.portrait ? { x: 50, y: F.safe.t + 40, w: F.W - 100, h: F.H - F.safe.t - F.safe.b - 320 }
    : { x: 790, y: 70, w: F.W - 790 - 60, h: F.H - 140 };
}

// ------------------------------------------------------------------------------------- HOOK
launchScene('kit:launch/HOOK', {
  describe: 'Scroll-stopper: the best real artefact hinges up off the table out of a blurred push-in, <= 6 word headline beside it.',
  params: { hero: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const hero = p.hero || {};
    const label = String(p.label || '').trim();
    const width = L ? 980 : label ? 1060 : 1500;
    const b = contentBlock(ctx, hero, { width, maxH: L ? 1000 : 860, fast: true, t0: 0.05, badgeAt: Math.min(1.0, dur * 0.45), wrap: L, portrait: L, hug: true });
    const n = W.node(b.el, { x: 0, y: 0, z: 10, w: b.w, h: b.h, tilt: 36 });
    W.light(0, -b.h * 0.3, b.w * 1.1, b.h * 1.6);
    const wires = panelWires(W, n, b, b.h * 0.85, { outAt: 0.8 });
    const R = mediaRegion(F, !!label);
    const c = W.nodePoint(n, b.w / 2, b.h / 2);
    const wide = hero.kind === 'image' || (!hero.kind && (hero.asset || hero.path));
    const d = fitRect(W, F, b.w, b.h, 12, (L && wide ? 1.45 : 0.98) * R.w / F.W, 0.92 * R.h / F.H) / productScale(p);
    const shift = [R.x + R.w / 2 - F.W / 2, R.y + R.h / 2 - F.H / 2];
    const cam = camTrack([
      [0, { target: [c[0], c[1] + 40, c[2] - 30], dist: d * 1.14, yaw: -9, pitch: 40, roll: -2 }],
      [1.0, { target: c, dist: d * 1.0, yaw: -4, pitch: 46, roll: -1 }],
      [dur + 0.5, { target: [c[0] + 10, c[1], c[2] + 10], dist: d * 0.94, yaw: -1, pitch: 47, roll: -0.5 }],
    ]);
    const head = label ? headline(F, label) : null;
    return {
      cues: [...(b.cues || []), { t: 0.05, sfx: 'move', gain_db: -14 }, ...(label ? [{ t: 0.35, sfx: 'appear', gain_db: -12 }] : [])],
      render(t) {
        b.update(t);
        const u = seg(t, -0.45, 0.85, ease.outCubic);
        W.update(n, { tilt: lerp(4, 36, u), z: lerp(4, 10, u) });
        const blur = (1 - seg(t, -0.3, 0.55, ease.outCubic)) * 10;
        css(b.el, { filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : 'none' });
        for (const w of wires) w.set(t);
        W.camera(t, { ...cam(t), shift });
        if (head) head.update(t, 0.15);
      },
    };
  },
});

// ------------------------------------------------------------------------------------- SCREEN
launchScene('kit:launch/SCREEN', {
  describe: 'Real screenshot in a paper browser frame lying on the table: establish wide, push to the focus box, hold.',
  params: { image: IMAGE_DOC, bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'focus box (image fractions)' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const img = p.image || {};
    const b = browserBlock(ctx, img, { width: bw(img, L ? 980 : 1600, L ? 1300 : 1000), maxViewH: L ? 1240 : 940 });
    const n = W.node(b.el, { x: 0, y: b.h / 2, z: 40, w: b.w, h: b.h });
    W.light(0, 0, b.w * 1.15, b.h * 1.4);
    const wires = panelWires(W, n, b, b.h * 0.3, { outAt: 1.2 });
    const tPush = clamp(dur * 0.28, 1.0, 1.6);
    const cam = pushTrack(W, F, n, b, b.rect(p.bbox || [0.1, 0.1, 0.8, 0.8]), { tPush, dur, yaw0: 9, pitchWide: 26, pitchPush: 14,
      pushFillH: L ? 0.62 : 0.86, pushFillW: L ? 1.7 : 0.9, maxPush: L ? 2.6 : 2.1, keepLeft: false, scale: productScale(p) });
    return {
      cues: [{ t: tPush + 0.05, sfx: 'move', gain_db: -12 }],
      render(t) {
        const u = nodeIn(t);
        W.update(n, { z: lerp(150, 40, u), op: clamp(u * 2) });
        for (const w of wires) w.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- FEATURE
launchScene('kit:launch/FEATURE', {
  describe: 'One product feature: push to its region, cursor arrives, pauses, clicks with a ripple, accent ring; feature name as headline.',
  params: {
    image: IMAGE_DOC, feature: { type: 'string', default: '', doc: 'feature name (<= 6 words)' },
    bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'feature region (image fractions)' },
    click: { type: 'array', default: [0.5, 0.5], doc: 'click point (image fractions)' },
  },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const img = p.image || {};
    const name = String(p.feature || p.label || '').trim();
    const b = browserBlock(ctx, img, { width: bw(img, L ? 980 : 1500, L ? 1200 : 960), maxViewH: L ? 1140 : 900 });
    const n = W.node(b.el, { x: 0, y: b.h / 2, z: 40, w: b.w, h: b.h });
    W.light(0, 0, b.w * 1.15, b.h * 1.4);
    const bbox = p.bbox || [0.1, 0.1, 0.8, 0.8];
    const click = p.click || [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2];
    const tPush = clamp(dur * 0.2, 0.9, 1.3);
    const sync = Number(p._sync && p._sync.click);
    const press = Number.isFinite(sync) && sync > tPush + 0.8 && sync < dur - 0.6 ? sync : clamp(dur * 0.45, tPush + 1.2, Math.max(tPush + 1.2, dur - 1.4));
    const R = mediaRegion(F, !!name);
    const cam = pushTrack(W, F, n, b, b.rect(bbox), { tPush, dur, yaw0: 8, pitchWide: 26, pitchPush: 14, region: R, pushFillH: 0.8,
      pushFillW: L ? 1.35 : 0.9, keepLeft: false, maxPush: L ? 2.8 : 2.4, scale: productScale(p) });
    const ring = ringBlock();
    const [px, py] = b.pt(click[0], click[1]);
    const cur = cursorBlock({ from: [px + b.w * 0.2, py + b.h * 0.24], to: [px, py], arrive: press - 0.62, press, travel: 0.75, size: 1.5 });
    b.view.appendChild(ring.el);
    for (const e of cur.els) b.el.appendChild(e);
    const rr = b.rect(bbox);
    rr.y -= b.chromeH;
    const wires = panelWires(W, n, b, b.h * 0.3, { outAt: press + 0.1 });
    const head = name ? headline(F, name, { eyebrow: 'Feature' }) : null;
    return {
      cues: [{ t: tPush + 0.05, sfx: 'move', gain_db: -12 }, ...cur.cues],
      render(t) {
        const u = nodeIn(t);
        W.update(n, { z: lerp(150, 40, u), op: clamp(u * 2) });
        cur.update(t);
        ring.update(t, rr, press + 0.12);
        for (const w of wires) w.set(t);
        W.camera(t, cam(t));
        if (head) head.update(t, 0.3);
      },
    };
  },
});

// ------------------------------------------------------------------------------------- SCROLL
launchScene('kit:launch/SCROLL', {
  describe: 'Full-page capture in a browser frame standing on the table like a display; it scrolls top to bottom under a slow orbit.',
  params: { image: IMAGE_DOC, scroll: { type: 'array', default: [0, 1], doc: '[from, to] scroll fractions' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const img = p.image || {};
    const b = browserBlock(ctx, img, { width: L ? 960 : 1360, viewH: L ? 1280 : 820 });
    const n = W.node(b.el, { x: 0, y: 0, z: 0, w: b.w, h: b.h, tilt: 68 });
    W.light(0, -200, b.w * 1.4, 1400);
    const foot = W.nodePoint(n, 0, b.h);
    const wire = W.wire([[foot[0] - 20, foot[1] + 40], [foot[0] - 300, foot[1] + 40], [foot[0] - 300, foot[1] + 1200], [foot[0] - 3400, foot[1] + 1200]], { pulseStart: 0.5, every: 1.3, reverse: true });
    const c = W.nodePoint(n, b.w / 2, b.h / 2);
    const d = fitRect(W, F, b.w, b.h, 6, 0.8, 0.84) / productScale(p);
    const cam = camTrack([
      [0, { target: c, dist: d * 1.06, yaw: -7, pitch: 64, roll: -1 }],
      [dur + 0.5, { target: [c[0], c[1], c[2] - 10], dist: d * 0.96, yaw: 6, pitch: 70, roll: 0.8 }],
    ]);
    const [s0, s1] = (p.scroll || [0, 1]).map(Number);
    const t0 = 0.6, t1 = Math.max(t0 + 1, dur - 0.6);
    return {
      cues: [{ t: t0, sfx: 'move', gain_db: -14 }],
      render(t) {
        const u = nodeIn(t);
        W.update(n, { tilt: lerp(40, 68, u), op: clamp(u * 2) });
        b.setScroll(lerp(s0, s1, seg(t, t0, t1, ease.inOutCubic)));
        wire.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- BEFORE_AFTER
launchScene('kit:launch/BEFORE_AFTER', {
  describe: 'Before and after side by side on the table; a pulse carries across, the after panel lifts off the table and the camera trucks to it.',
  params: {
    before: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
    after: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
  },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const width = L ? 940 : 880;
    const switchAt = clamp(dur * 0.42, 1.2, dur - 1.6);
    const bb = contentBlock(ctx, p.before || {}, { width, maxH: L ? 780 : 760, fast: true, t0: 0.05, badgeAt: 0.6, wrap: L, portrait: L, fontSize: L ? undefined : 28 });
    const ab = contentBlock(ctx, p.after || {}, { width, maxH: L ? 780 : 760, fast: true, t0: switchAt + 0.25, badgeAt: switchAt + 0.75, wrap: L, portrait: L, fontSize: L ? undefined : 28 });
    const gap = 150;
    const nb = L ? W.node(bb.el, { x: 0, y: -gap / 2, z: 30, w: bb.w, h: bb.h }) : W.node(bb.el, { x: -(width + gap) / 2, y: bb.h / 2, z: 30, w: bb.w, h: bb.h });
    const na = L ? W.node(ab.el, { x: 0, y: gap / 2 + ab.h, z: 30, w: ab.w, h: ab.h }) : W.node(ab.el, { x: (width + gap) / 2, y: ab.h / 2, z: 30, w: ab.w, h: ab.h });
    W.light(0, 0, 2200, 1500);
    const pb = L ? W.nodePoint(nb, bb.w / 2, bb.h) : W.nodePoint(nb, bb.w, bb.h / 2);
    const pa = L ? W.nodePoint(na, ab.w / 2, 0) : W.nodePoint(na, 0, ab.h / 2);
    const link = W.wire([[pb[0] + (L ? 0 : 14), pb[1] + (L ? 14 : 0)], [pa[0] - (L ? 0 : 14), pa[1] - (L ? 14 : 0)]], { pulses: 1, pulseStart: switchAt - 0.25, every: 9, speed: 900, len: 140 });
    const cB = W.nodePoint(nb, bb.w / 2, bb.h / 2), cA = W.nodePoint(na, ab.w / 2, ab.h / 2);
    const mid = [(cB[0] + cA[0]) / 2, (cB[1] + cA[1]) / 2, 30];
    const dAll = L ? fitRect(W, F, width, bb.h + ab.h + gap, 18, 0.86, 0.82) : fitRect(W, F, width * 2 + gap, Math.max(bb.h, ab.h), 18, 0.9, 0.8);
    const dOne = L ? fitRect(W, F, width, ab.h, 14, 0.9, 0.5) : fitRect(W, F, width, ab.h, 14, 0.62, 0.8);
    const dClose = Math.max(dOne, dAll * 0.62) / productScale(p);
    const toward = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, 30];
    const cam = camTrack([
      [0, { target: toward(cB, cA, 0.12), dist: dClose * 1.06, yaw: -4, pitch: 20, roll: -1 }],
      [switchAt - 0.35, { target: toward(cB, cA, 0.2), dist: dClose, yaw: -2, pitch: 16, roll: -0.6 }],
      [switchAt + 0.65, { target: [cA[0], cA[1], 60], dist: dClose, yaw: 2, pitch: 14, roll: 0 }],
      [dur + 0.5, { target: [cA[0] + 10, cA[1] + 8, 60], dist: dClose * 0.97, yaw: 3, pitch: 13, roll: 0.3 }],
    ]);
    const tagB = h('div', 'srb-tag', { text: 'Before' });
    const tagA = h('div', 'srb-tag after', { text: 'After' });
    F.ov.append(tagB, tagA);
    const cues = [...(bb.cues || []).filter((c) => c.sfx !== 'pass'), { t: switchAt, sfx: 'move', gain_db: -10 }, ...(ab.cues || []).filter((c) => c.sfx === 'pass' || c.sfx === 'appear')];
    return {
      cues,
      render(t) {
        bb.update(t); ab.update(t);
        const lift = seg(t, switchAt, switchAt + 0.6, ease.outCubic);
        const uB = nodeIn(t), uA = seg(t, switchAt - 0.5, switchAt + 0.3, ease.outQuint);
        W.update(nb, { op: clamp(uB * 2) * lerp(1, 0.55, lift), z: 30 });
        W.update(na, { z: lerp(30, 90, lift), op: lerp(0.35, 1, uA) });
        link.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
        // tags ride above each panel's top-left corner (projected)
        const tb = W.project(W.nodePoint(nb, 0, 0)), ta = W.project(W.nodePoint(na, 0, 0));
        css(tagB, { left: `${tb[0].toFixed(1)}px`, top: `${(tb[1] - 64).toFixed(1)}px`, opacity: (seg(t, 0.15, 0.5) * lerp(1, 0.6, lift)).toFixed(3) });
        css(tagA, { left: `${ta[0].toFixed(1)}px`, top: `${(ta[1] - 64).toFixed(1)}px`, opacity: seg(t, switchAt + 0.2, switchAt + 0.5).toFixed(3),
          transform: `scale(${(0.85 + 0.15 * seg(t, switchAt + 0.2, switchAt + 0.6, ease.outBack)).toFixed(4)})` });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- MONTAGE
launchScene('kit:launch/MONTAGE', {
  describe: "Breadth of the agent's work: real tool calls as cards along a wired path on the table; the camera whips card to card, each stands up as it arrives.",
  params: { items: { type: 'array', default: [], doc: '[{id, t, kind, tool, arg, clipped}] 3-16' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const items = (p.items || []).slice(0, 16);
    const n = Math.max(1, items.length);
    const cw = L ? 820 : 700, chh = L ? 220 : 240;
    const gx = L ? 0 : cw + 150, gy = L ? chh + 90 : 0;      // a tight conveyor: 3+ cards in frame at once
    const step = dur / n;
    const nodes = items.map((it, i) => {
      const c = toolCard(it, { width: cw, height: chh });
      // a gentle S along the table: x marches, y swings
      const x = L ? Math.sin(i * 0.9) * 70 : i * gx;
      const y = L ? i * gy : Math.sin(i * 1.1) * 110;
      return { c, node: W.node(c.el, { x, y: y + chh / 2, z: 24, w: cw, h: chh }), x, y };
    });
    W.light(L ? 0 : (n - 1) * gx / 2, L ? (n - 1) * gy / 2 : 0, L ? 1600 : n * 460 + 1200, L ? n * 200 + 1200 : 1500);
    // the wire threads every card (under them), pulses run along the whole path
    const pts = nodes.map((q) => [q.x, q.y + chh + 70]);
    if (pts.length >= 2) W.wire([[pts[0][0] - (L ? 0 : 600), pts[0][1] - (L ? 500 : 0)], ...pts, [pts[pts.length - 1][0] + (L ? 0 : 900), pts[pts.length - 1][1] + (L ? 900 : 0)]],
      { radius: 160, pulses: 3, every: step * 2, speed: L ? 1200 : 1500, port: false });
    const d = fitRect(W, F, L ? cw * 1.08 : cw * 2.25, L ? chh * 4.0 : chh * 2.0, 20, 0.94, 0.86);
    const keys = [];
    nodes.forEach((q, i) => {
      const t0 = i * step;
      const tg = [q.x, q.y - chh * (L ? 0.1 : 0.25), 60];     // the standing card's visual centre
      keys.push([t0, { target: tg, dist: d, yaw: L ? 0 : -6, pitch: 24, roll: -1 }]);
      keys.push([t0 + Math.min(step * 0.62, 0.42), { target: [tg[0] + (L ? 0 : 18), tg[1] + (L ? 14 : 0), 24], dist: d * 0.985, yaw: L ? 0 : -6, pitch: 24, roll: -1 }]);
    });
    if (!keys.length) keys.push([0, { target: [0, 0, 0], dist: d, yaw: 0, pitch: 30 }]);
    keys.sort((a, b) => a[0] - b[0]);
    const cam = camTrack(keys);
    const cues = nodes.map((q, i) => ({ t: i * step + 0.02, sfx: 'appear', gain_db: -16 }));
    return {
      cues,
      render(t) {
        const cur = clamp(Math.floor((t + 0.05) / step), 0, n - 1);
        nodes.forEach((q, i) => {
          const arrive = seg(t, i * step - 0.12, i * step + 0.3, ease.outQuint);
          const pre = seg(t, (i - 2) * step - 0.2, (i - 2) * step + 0.3, ease.outQuint);
          const behind = cur - i;           // cards behind fade out before the camera leaves them (no off-frame text)
          W.update(q.node, { tilt: lerp(0, 24, arrive), z: lerp(24, 40, arrive), op: clamp(pre * 1.4) * (behind >= 2 ? 0 : behind === 1 ? 0.6 : 1) });
          q.c.el.classList.toggle('on', i === cur);
        });
        for (const w of W.wires) w.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
      },
    };
  },
});
