// Showreel kit "launch" — type-led scenes over the table world: TITLE, STATS, CALLOUT, END.
// The lockups reuse kit:base layouts (TITLE_DEF, ...) on a screen-space type layer; the table, light pool,
// converging connectors and pulses live in the 3D world underneath (slightly defocused so type stays crisp).

import { launchScene, camTrack, fitRect, nodeIn, hubWires, panelWires } from './stage.js';
import { h, css } from '../base/dom.js';
import { clamp, lerp, seg, ease } from '../base/motion.js';
import { TITLE_DEF, STATS_DEF, CALLOUT_DEF, END_DEF } from '../base/scenes-titles.js';
import { contentBlock } from '../base/scenes-media.js';

/** Run a base type-scene build on a screen-space layer above the world. */
function typeLayer(ctx, p, F, def) {
  const layer = h('div', 'srb-abs');
  layer.style.cssText = 'left:0;top:0;width:100%;height:100%;transform-origin:0 0;';
  F.ov.appendChild(layer);
  const dummy = h('div');
  const F2 = { ...F, cam: layer, bg: dummy, ov: F.ov };
  return def.build(ctx, p, F2) || { render() {}, cues: [] };
}

function defocus(W, px) { css(W.view, { filter: px > 0.05 ? `blur(${px.toFixed(2)}px)` : 'none' }); }

/**
 * The film's product image (params.backdrop, injected by Quick mode) as a large screen lying on the table
 * under the type: the world blur defocuses it into a product echo, a radial scrim keeps the type legible.
 * Returns {set(t)} or null. o: {x, y, width, tilt, rz, op, scrim}
 */
function backdropPanel(ctx, W, F, p, o = {}) {
  if (!p.backdrop || !(p.backdrop.asset || p.backdrop.path)) return null;
  const L = F.portrait;
  const b = contentBlock(ctx, p.backdrop, { width: o.width || (L ? 1250 : 1700), fast: true, t0: 0 });
  b.el.dataset.qa = 'off';          // a defocused echo: its address bar is decoration, not text to check
  b.el.style.filter = `blur(${o.blur ?? 7}px) brightness(.82)`;
  const n = W.node(b.el, { x: o.x ?? 0, y: (o.y ?? 0) + b.h / 2, z: 2, w: b.w, h: b.h, tilt: o.tilt ?? 6, rz: o.rz ?? -5 });
  const scrim = h('div', 'slw-scrim');
  scrim.style.cssText = `position:absolute;inset:0;pointer-events:none;background:radial-gradient(${L ? '90% 60%' : '62% 70%'} at 50% ${L ? '46%' : '50%'},` +
    `rgba(10,11,13,${o.scrim ?? 0.78}) 0%,rgba(10,11,13,${((o.scrim ?? 0.78) * 0.55).toFixed(2)}) 55%,rgba(10,11,13,0) 100%);`;
  F.ov.insertBefore(scrim, F.ov.firstChild);
  return {
    set(t) {
      const u = seg(t, -0.3, 1.2, ease.outCubic);
      W.update(n, { op: (o.op ?? 0.5) * u, tilt: (o.tilt ?? 6) + (1 - u) * 10, rz: (o.rz ?? -5) + (1 - u) * -4, z: 2 + (1 - u) * 60 });
    },
  };
}

// ------------------------------------------------------------------------------------- TITLE
launchScene('kit:launch/TITLE', {
  describe: 'Name + thesis: left lockup (eyebrow, huge title, tagline with one serif accent word) beside the product hero at a low angle; connectors pulse toward it.',
  params: { ...TITLE_DEF.params, theme: { type: 'string', default: 'launch', doc: 'theme' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const heroData = p.hero && (p.hero.asset || p.hero.kind) ? p.hero : (p.backdrop && p.backdrop.asset ? p.backdrop : null);
    const hasHero = !!heroData;
    const T = typeLayer(ctx, { ...p, hero: null, _hero_elsewhere: hasHero, ...(L && hasHero ? { _title_top: 880 } : {}) }, F, TITLE_DEF);
    if (!hasHero) {
      W.light(0, 0, 1800, 1300);
      const wires = hubWires(W, 0, 0, 5, { arrive: 0.9, every: 1.5 });
      const cam = camTrack([[0, { target: [0, 60, 0], dist: 2300, yaw: -8, pitch: 58, roll: -1.5 }], [dur + 0.5, { target: [0, 0, 0], dist: 2100, yaw: 2, pitch: 54, roll: 0 }]]);
      defocus(W, 3);
      return { cues: T.cues, render(t) { T.render(t); for (const w of wires) w.set(t); W.camera(t, cam(t)); } };
    }
    const b = contentBlock(ctx, heroData, { width: L ? 960 : 1040, maxH: L ? 720 : 800, fast: true, t0: 0, wrap: L, portrait: L, hug: true });
    const n = W.node(b.el, { x: 0, y: 0, z: 8, w: b.w, h: b.h, tilt: 40 });
    W.light(0, -b.h * 0.3, b.w * 1.3, b.h * 1.8);
    const wires = panelWires(W, n, b, b.h * 0.92, { outAt: 0.6 });
    const R = L ? { x: 30, y: 170, w: F.W - 60, h: 660 } : { x: 960, y: 80, w: F.W - 960 - 50, h: F.H - 160 };
    const shift = [R.x + R.w / 2 - F.W / 2, R.y + R.h / 2 - F.H / 2];
    const c = W.nodePoint(n, b.w / 2, b.h / 2);
    const d = fitRect(W, F, b.w, b.h, 10, 0.92 * R.w / F.W, 0.86 * R.h / F.H);
    const cam = camTrack([
      [0, { target: [c[0], c[1] + 40, c[2]], dist: d * 1.22, yaw: 22, pitch: 36, roll: -3 }],
      [Math.min(1.2, dur * 0.4), { target: c, dist: d * 1.02, yaw: 10, pitch: 46, roll: -1.6 }],
      [dur + 0.5, { target: c, dist: d * 0.94, yaw: 3, pitch: 52, roll: -0.8 }],
    ]);
    return {
      cues: T.cues,
      render(t) {
        T.render(t);
        b.update(t);
        const u = seg(t, -0.4, 0.9, ease.outCubic);
        W.update(n, { tilt: lerp(14, 40, u), op: clamp(u * 2.5) });
        for (const w of wires) w.set(t);
        W.camera(t, { ...cam(t), shift });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- STATS
launchScene('kit:launch/STATS', {
  describe: 'Real numbers on the drop: big numerals count up over the table while connectors pulse into the hub; accent rule under the hero number.',
  params: { ...STATS_DEF.params, theme: { type: 'string', default: 'launch', doc: 'theme' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur;
    const bd = backdropPanel(ctx, W, F, p, { y: F.portrait ? 120 : 60, rz: -7 });
    const T = typeLayer(ctx, p, F, STATS_DEF);
    W.light(0, 0, 2000, 1400);
    const wires = hubWires(W, 0, 0, 6, { arrive: 0.25, every: 1.2 });
    const cam = camTrack([[0, { target: [0, 0, 0], dist: 1550, yaw: -16, pitch: 52, roll: -2 }], [dur + 0.5, { target: [0, -60, 0], dist: 2100, yaw: 10, pitch: 44, roll: 1 }]]);
    defocus(W, bd ? 4 : 2.5);
    return { cues: T.cues, render(t) { T.render(t); if (bd) bd.set(t); for (const w of wires) w.set(t); W.camera(t, cam(t)); } };
  },
});

// ------------------------------------------------------------------------------------- CALLOUT
launchScene('kit:launch/CALLOUT', {
  describe: 'One verbatim line in serif italic over the dim, defocused table; accent rule, mono attribution, near-still camera.',
  params: { ...CALLOUT_DEF.params, theme: { type: 'string', default: 'launch', doc: 'theme' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur;
    const bd = backdropPanel(ctx, W, F, p, { x: 120, y: 40, rz: 6, op: 0.5 });
    const T = typeLayer(ctx, p, F, CALLOUT_DEF);
    W.light(-300, 100, 1600, 1000);
    const wires = hubWires(W, -200, 0, 3, { arrive: 1.2, every: 2.2, angles: [200, 330, 20], ports: false });
    const cam = camTrack([[0, { target: [0, 0, 0], dist: 1900, yaw: -10, pitch: 60, roll: -2 }], [dur + 0.5, { target: [-60, 0, 0], dist: 1850, yaw: -6, pitch: 58, roll: -1.5 }]]);
    defocus(W, 4);
    css(W.view, { opacity: '0.75' });
    return { cues: T.cues, render(t) { T.render(t); if (bd) bd.set(t); for (const w of wires) w.set(t); W.camera(t, cam(t), { amp: 2 }); } };
  },
});

// ------------------------------------------------------------------------------------- END
launchScene('kit:launch/END', {
  describe: 'End card / thumbnail: camera pulls back to a near top-down table where every connector converges under the lockup; CTA pill, URL, credit.',
  params: { ...END_DEF.params, theme: { type: 'string', default: 'launch', doc: 'theme' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur;
    const bd = backdropPanel(ctx, W, F, p, { y: 40, rz: -4, op: 0.48, tilt: 2, blur: 9 });
    const T = typeLayer(ctx, p, F, END_DEF);
    W.light(0, 0, 2200, 1500);
    const wires = hubWires(W, 0, 0, 6, { arrive: 1.0, every: 1.6, r0x: 260, r0y: 160 });
    const cam = camTrack([
      [0, { target: [0, 160, 0], dist: 1350, yaw: -18, pitch: 46, roll: -3 }],
      [1.8, { target: [0, 0, 0], dist: 2300, yaw: -3, pitch: 14, roll: -0.6 }],
      [dur + 0.5, { target: [0, 0, 0], dist: 2420, yaw: 0, pitch: 10, roll: 0 }],
    ]);
    return {
      cues: [{ t: 0.05, sfx: 'move', gain_db: -12 }, ...T.cues],
      render(t) {
        T.render(t);
        if (bd) bd.set(t);
        defocus(W, lerp(0, bd ? 4.5 : 3, seg(t, 0.4, 1.6, ease.inOutCubic)));
        for (const w of wires) w.set(t);
        W.camera(t, cam(t), { amp: 3 });
      },
    };
  },
});

export { nodeIn };
