// Showreel kit "comic" — product media pages: HOOK (splash), SCREEN, FEATURE, SCROLL, BEFORE_AFTER. Screenshots are
// printed into the panels (colour halftone first, the real pixels grow in through the dot screen).

import { comicScene, snapIn } from './lib/page.js';
import { h, css } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { mediaOf } from '../base/media.js';
import { C, agentSvg, figure, burst, speedLines, CURSOR_SVG } from './lib/art.js';
import { caption, sfx, slam, headline } from './lib/letter.js';
import { printShot, comicBrowser, scrollBrowser, heroBlock } from './lib/print.js';

const IMAGE_DOC = { type: 'image', default: null, doc: '{asset, path, w, h, url, page_title, full_page} (asset = film asset name)' };

/** Onomatopoeia for a hero artefact. */
function heroWord(c) {
  const k = (c && c.kind) || 'image';
  if (k === 'terminal') return c.tests_passed ? 'PASS!' : c.ok === false ? 'UH-OH!' : 'DONE!';
  if (k === 'diff') return 'SHNK!';
  if (k === 'code') return 'TAK!';
  return 'BOOM!';
}

/** Browser size that fits maxW x maxH (chrome 64) keeping the image aspect. */
function fitBrowser(ctx, img, maxW, maxH) {
  const m = mediaOf(ctx, img);
  const w = Math.round(Math.min(maxW, ((maxH - 64) * m.w) / m.h));
  return { w, vh: Math.round(Math.min(maxH - 64, (w * m.h) / m.w)) };
}

/** Yellow marker ring (ink-backed ellipse) that draws on around a rect; returns {el, update(t, t0)}. */
function markerRing(P, r, o = {}) {
  const pad = o.pad ?? 26;
  const w = r.w + 2 * pad, hh = r.h + 2 * pad;
  const el = P.svg(w, hh, `<ellipse cx="${w / 2}" cy="${hh / 2}" rx="${w / 2 - 8}" ry="${hh / 2 - 8}" fill="none" stroke="${C.ink}" stroke-width="20" pathLength="1" stroke-dasharray="1 1"/>` +
    `<ellipse cx="${w / 2}" cy="${hh / 2}" rx="${w / 2 - 8}" ry="${hh / 2 - 8}" fill="none" stroke="${C.yellow}" stroke-width="10" pathLength="1" stroke-dasharray="1 1"/>`,
  { style: `position:absolute;left:${r.x - pad}px;top:${r.y - pad}px;z-index:30;` });
  return {
    el,
    update(t, t0) {
      const u = seg(t, t0, t0 + 0.45, ease.inOutCubic);
      for (const e of el.children) css(e, { strokeDashoffset: (1 - u).toFixed(4) });
      css(el, { opacity: t >= t0 ? '1' : '0' });
    },
  };
}

// ------------------------------------------------------------------------------------- 9:16 close-up pages
/** Crop (image fractions) around bbox for a pw x ph box: the bbox fills ~`fill` of the crop, clamped to the image. */
function closeCrop(ctx, img, bb, pw, ph, fill = 0.62) {
  const m = mediaOf(ctx, img);
  const A = pw / ph;
  let cw = Math.max((bb[2] * m.w) / fill, ((bb[3] * m.h) / fill) * A, 260 * A);
  let ch = cw / A;
  if (cw > m.w) { cw = m.w; ch = cw / A; }
  if (ch > m.h) { ch = m.h; cw = ch * A; }
  const cx = (bb[0] + bb[2] / 2) * m.w, cy = (bb[1] + bb[3] / 2) * m.h;
  const x = clamp(cx - cw / 2, 0, m.w - cw), y = clamp(cy - ch / 2, 0, m.h - ch);
  return [x / m.w, y / m.h, cw / m.w, ch / m.h];
}

/**
 * Portrait media page: an establishing panel (the whole printed screen with a yellow inset box on the focus area)
 * above a close-up panel (the focus area printed big, coarser dots) — the comic's way to zoom without losing width.
 */
function closeUpPage(ctx, p, F, P, o) {
  const W = F.W, H = F.H;
  const img = p.image || {};
  const bb = p.bbox || [0.1, 0.1, 0.8, 0.8];
  const top = o.top ?? 200, gut = 26;
  const { w, vh } = fitBrowser(ctx, img, 920, o.maxH1 || 700);
  const br = comicBrowser(ctx, img, w, vh, { cell: 11 });
  const R1 = { x: 40, y: top, w: W - 80, h: br.h + 140 };
  const p1 = P.panel(R1, { bg: o.bg1 || 'cyan' });
  const bx = Math.round((R1.w - br.w) / 2), by = 98;
  br.el.style.left = `${bx}px`; br.el.style.top = `${by}px`;
  p1.el.appendChild(br.el);
  const cap1 = caption(o.cap1, { x: 30, y: 28 });
  p1.el.appendChild(cap1.el);
  const r = br.shot.rect(bb);
  const inset = h('div', 'cx-abs');
  inset.style.cssText = `left:${bx + r.x - 8}px;top:${by + br.chromeH + r.y - 8}px;width:${r.w + 16}px;height:${r.h + 16}px;` +
    `border:6px solid ${C.yellow};box-shadow:0 0 0 4px ${C.ink},inset 0 0 0 4px ${C.ink};z-index:30;`;
  p1.el.appendChild(inset);
  const y2 = top + R1.h + gut;
  const R2 = { x: 40, y: y2, w: W - 80, h: H - 40 - y2 };
  const p2 = P.panel(R2, { bg: o.bg2 || 'sun', rays: [0.5, 0.55], seed: 17 });
  const cw = R2.w - 96, chh = R2.h - 150;
  const cs = printShot(ctx, img, cw, chh, { crop: closeCrop(ctx, img, bb, cw, chh), cell: 17 });
  const frame = h('div', 'cx-abs');
  frame.style.cssText = `left:44px;top:104px;width:${cw}px;height:${chh}px;outline:6px solid ${C.ink};box-shadow:16px 16px 0 ${C.ink};background:${C.white};overflow:hidden;`;
  frame.appendChild(cs.el);
  p2.el.appendChild(frame);
  const cap2 = caption(o.cap2, { x: 30, y: 28 });
  p2.el.appendChild(cap2.el);
  const rc = cs.rect(bb);
  const rr = { x: 44 + rc.x, y: 104 + rc.y, w: rc.w, h: rc.h };
  return { R1, R2, p1, p2, br, cs, rr, cap1, cap2, inset, frameX: 44, frameY: 104 };
}

function screenPortrait(ctx, p, F, P) {
  const W = F.W, H = F.H, dur = ctx.dur;
  const img = p.image || {};
  const title = String(img.page_title || '').trim();
  const pg = closeUpPage(ctx, p, F, P, { cap1: title ? `Meanwhile, at ${title}\u2026` : 'Meanwhile, in the app\u2026', cap2: 'Look closer!', maxH1: 720 });
  const ring = markerRing(P, pg.rr, { pad: 22 });
  pg.p2.el.appendChild(ring.el);
  const look = burst(P.doc, { w: 230, h: 170, spikes: 12, fill: 'yellow', seed: 91, shadow: 8, text: 'LOOK!', size: 60 });
  look.el.style.left = `${clamp(pg.rr.x + pg.rr.w - 150, 20, pg.R2.w - 250)}px`;
  look.el.style.top = `${clamp(pg.rr.y - 120, 70, pg.R2.h - 190)}px`;
  look.el.style.zIndex = '34';
  pg.p2.el.appendChild(look.el);
  const tP2 = clamp(dur * 0.24, 0.9, 1.4), tRing = tP2 + 0.7;
  const c1 = [W / 2, pg.R1.y + pg.R1.h / 2 + 120, 1.0], c2 = [W / 2, pg.R2.y + pg.R2.h / 2 - 60, 1.06];
  const cam = P.track([[0, c1], [tP2 - 0.1, c1], [tP2 + 0.6, c2], [dur + 1, [c2[0], c2[1] + 10, 1.08]]]);
  return {
    cues: [{ t: 0.15, sfx: 'appear', gain_db: -12 }, { t: tP2, sfx: 'move', gain_db: -12 }, { t: tRing + 0.4, sfx: 'hit', gain_db: -10 }],
    render(t) {
      pg.cap1.update(t, 0.05);
      pg.br.shot.update(t, 0.15, 0.55);
      snapIn(pg.br.el, t, -0.05, { rise: 50, from: 0.94 });
      css(pg.inset, { opacity: seg(t, tP2 - 0.4, tP2 - 0.2).toFixed(3) });
      P.panelIn(pg.p2, t, tP2, 'top');
      pg.cap2.update(t, tP2 + 0.2);
      pg.cs.update(t, tP2 + 0.1, 0.5);
      ring.update(t, tRing);
      const s = slam(t, tRing + 0.4);
      css(look.el, { opacity: s.op.toFixed(3), transform: `rotate(-8deg) scale(${s.s.toFixed(4)})` });
      P.camera(t, cam(t));
    },
  };
}

function featurePortrait(ctx, p, F, P) {
  const W = F.W, dur = ctx.dur;
  const name = String(p.feature || p.label || '').trim();
  const R0 = { x: 40, y: 200, w: W - 80, h: 300 };
  const p0 = P.panel(R0, { bg: 'action', rays: [0.85, 0.6], seed: 23 });
  const cap = caption('New power!', { x: 30, y: 26 });
  p0.el.appendChild(cap.el);
  const head = headline((name || 'The feature').toUpperCase(), { x: 32, y: 92, w: 700, lines: 2, max: 92, min: 58 });
  p0.el.appendChild(head.el);
  const hero = figure(agentSvg({ pose: 'bust', rim: 'white' }), 740, 50, 250);
  p0.el.appendChild(hero);
  const pg = closeUpPage(ctx, p, F, P, { top: 526, cap1: 'The app\u2026', cap2: 'Click!', maxH1: 540, bg2: 'cyan' });
  const bb = p.bbox || [0.1, 0.1, 0.8, 0.8];
  const click = p.click || [bb[0] + bb[2] / 2, bb[1] + bb[3] / 2];
  const [qx, qy] = pg.cs.pt(click[0], click[1]);
  const cpt = [pg.frameX + qx, pg.frameY + qy];
  const ring = markerRing(P, pg.rr, { pad: 20 });
  pg.p2.el.appendChild(ring.el);
  const sl = h('div', 'cx-abs');
  sl.style.cssText = `left:${cpt[0] - 210}px;top:${cpt[1] - 210}px;width:420px;height:420px;z-index:31;`;
  sl.appendChild(speedLines(P.doc, 420, 420, 210, 210, { n: 44, clear: 70, seed: 7 }));
  pg.p2.el.appendChild(sl);
  const cur = h('div', 'cx-cursor', { html: CURSOR_SVG });
  pg.p2.el.appendChild(cur);
  const clk = burst(P.doc, { w: 250, h: 170, spikes: 13, fill: 'yellow', seed: 33, shadow: 8, text: 'CLICK!', size: 58 });
  clk.el.style.left = `${clamp(pg.rr.x + pg.rr.w - 40, 10, pg.R2.w - 270)}px`;
  clk.el.style.top = `${clamp(pg.rr.y - 150, 70, pg.R2.h - 190)}px`;
  clk.el.style.zIndex = '34';
  pg.p2.el.appendChild(clk.el);
  const tP1 = 0.3, tP2 = clamp(dur * 0.22, 1.0, 1.4);
  const sync = Number(p._sync && p._sync.click);
  const press = Number.isFinite(sync) && sync > tP2 + 1.0 && sync < dur - 0.6 ? sync : clamp(dur * 0.5, tP2 + 1.3, Math.max(tP2 + 1.3, dur - 1.3));
  const arrive = press - 0.62;
  const from = [cpt[0] + 240, cpt[1] + 200];
  const c1 = [W / 2, 900, 1.0], c2 = [W / 2, pg.R2.y + pg.R2.h / 2 - 80, 1.08];
  const cam = P.track([[0, c1], [tP2 - 0.1, c1], [tP2 + 0.7, c2], [dur + 1, [c2[0], c2[1] + 8, 1.1]]]);
  return {
    cues: [{ t: 0.2, sfx: 'appear', gain_db: -12 }, { t: tP2, sfx: 'move', gain_db: -12 }, { t: press, sfx: 'click', gain_db: -4 }, { t: press + 0.05, sfx: 'hit', gain_db: -10 }],
    render(t) {
      P.spinRays(t);
      cap.update(t, 0.05);
      head.update(t, 0.15, 0.08);
      const hu = seg(t, 0, 0.5, ease.outCubic);
      css(hero, { transform: `translate(${((1 - hu) * 60).toFixed(1)}px,0)` });
      P.panelIn(pg.p1, t, tP1, 'top');
      pg.cap1.update(t, tP1 + 0.15);
      pg.br.shot.update(t, tP1 + 0.1, 0.5);
      css(pg.inset, { opacity: seg(t, tP2 - 0.4, tP2 - 0.2).toFixed(3) });
      P.panelIn(pg.p2, t, tP2, 'top');
      pg.cap2.update(t, tP2 + 0.2);
      pg.cs.update(t, tP2 + 0.1, 0.5);
      const u = seg(t, arrive - 0.7, arrive, ease.inOutCubic);
      const x = lerp(from[0], cpt[0], u), y = lerp(from[1], cpt[1], u) - Math.sin(Math.PI * u) * 50;
      const dip = t >= press ? Math.exp(-(t - press) * 14) : 0;
      css(cur, { opacity: seg(t, arrive - 0.9, arrive - 0.65).toFixed(3), transform: `translate(${(x - 6).toFixed(1)}px,${(y - 6).toFixed(1)}px) scale(${(1.25 * (1 - 0.18 * dip)).toFixed(4)})` });
      const k = seg(t, press, press + 0.12);
      css(sl, { opacity: (t >= press ? 1 - seg(t, press + 0.5, press + 0.9) : 0).toFixed(3), transform: `scale(${(0.7 + 0.3 * k).toFixed(3)})` });
      const s = slam(t, press + 0.02, { from: 1.8 });
      css(clk.el, { opacity: s.op.toFixed(3), transform: `rotate(9deg) scale(${s.s.toFixed(4)})` });
      ring.update(t, press + 0.15);
      P.camera(t, cam(t), { shakes: [press + 0.02], amp: 6 });
    },
  };
}

// ------------------------------------------------------------------------------------- HOOK
comicScene('kit:comic/HOOK', {
  describe: 'Splash page scroll-stopper: the best real artefact (printed screenshot, green test run, diff) inside a giant burst over a red sunburst, a <= 6 word headline in display lettering and one onomatopoeia; page shake on the slam.',
  params: { hero: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...block data}' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, dur = ctx.dur;
    const hero = p.hero || {};
    const label = String(p.label || '').trim();
    const pn = P.panel({ x: 40, y: L ? 40 : 200, w: W - 80, h: L ? H - 80 : H - 240 }, { bg: 'splash', rays: L ? (label ? [0.66, 0.5] : [0.5, 0.5]) : [0.5, 0.42], seed: 5, spin: 6 });
    const bw = L ? (label ? 1000 : 1400) : 940, bmax = L ? 760 : 820;
    const tfs = hero.kind === 'terminal' && (hero.output || []).length <= 3 ? (L ? 44 : 36) : undefined;
    const b = heroBlock(ctx, hero, { width: bw, maxH: bmax, t0: 0.12, develop: 0.45, badgeAt: Math.min(0.9, dur * 0.4), wrap: !L, portrait: !L, hug: true, fontSize: tfs });
    const cx = L ? (label ? pn.w - 70 - b.w / 2 : pn.w / 2) : pn.w / 2;
    const cy = L ? pn.h / 2 + 10 : (label ? 860 : 760);
    const bst = burst(P.doc, { w: b.w + (L ? 220 : 160), h: b.h + (L ? 260 : 240), spikes: 24, depth: 0.14, fill: 'white', seed: 14, shadow: 14 });
    bst.el.style.left = `${cx - bst.w / 2}px`; bst.el.style.top = `${cy - bst.h / 2}px`;
    pn.el.appendChild(bst.el);
    b.el.style.left = `${cx - b.w / 2}px`; b.el.style.top = `${cy - b.h / 2}px`;
    b.el.style.zIndex = '26';
    pn.el.appendChild(b.el);
    let head = null;
    if (label) {
      head = headline(label.toUpperCase(), L ? { x: S.l - 40, y: 0, w: 560, lines: 4, max: 128, min: 76 } : { x: S.l - 40, y: S.t - 200 + 20, w: 840, lines: 3, max: 110, min: 70 });
      if (L) head.el.style.top = `${Math.max(S.t - 40, pn.h / 2 - head.size * 1.9)}px`;
      pn.el.appendChild(head.el);
    }
    const word = heroWord(hero);
    const sw = sfx(word, L ? (hero.kind && hero.kind !== 'image'
      ? { x: cx - b.w / 2 + 10, y: cy + b.h / 2 + 24, size: 130, color: word === 'PASS!' ? C.green : C.yellow, rot: -8 }
      : { x: label ? cx - b.w / 2 - 40 : cx + b.w / 2 - 420, y: cy + b.h / 2 - 70, size: 140, color: C.yellow, rot: -8 })
      : { x: pn.w - 520, y: Math.min(1180, cy + b.h / 2 + 10), size: 132, color: word === 'PASS!' ? C.green : C.yellow, rot: -8 });
    pn.el.appendChild(sw.el);
    const tSlam = 0.22;
    return {
      cues: [...(b.cues || []).filter((c) => c.sfx !== 'pass'), { t: tSlam, sfx: 'hit', gain_db: -3 }, ...(label ? [{ t: 0.3, sfx: 'appear', gain_db: -12 }] : [])],
      render(t) {
        P.spinRays(t);
        const s = slam(t, tSlam - 0.08, { from: 1.5 });
        css(bst.el, { opacity: s.op.toFixed(3), transform: `scale(${s.s.toFixed(4)})` });
        b.update(t);
        snapIn(b.el, t, 0.0, { rise: 60, from: 0.8, rot: -2 });
        if (head) head.update(t, 0.25, 0.09);
        sw.update(t, tSlam + 0.2);
        const u = seg(t, 0, Math.min(dur, 1.5), ease.outCubic);
        P.camera(t, [W / 2, H / 2, lerp(1.07, 1.0, u)], { shakes: [tSlam], amp: 14 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- SCREEN
comicScene('kit:comic/SCREEN', {
  describe: 'The real screenshot printed into a big panel (colour halftone develops into the real pixels) with a caption; the camera establishes, then pushes onto the focus box (9:16: a close-up panel prints the focus area big), which a yellow marker ring circles with a LOOK! burst.',
  params: { image: IMAGE_DOC, bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'focus box [x,y,w,h] as image fractions' } },
  build(ctx, p, F, P) {
    if (F.portrait) return screenPortrait(ctx, p, F, P);
    const L = !F.portrait, W = F.W, H = F.H, dur = ctx.dur;
    const img = p.image || {};
    const R = L ? { x: 40, y: 40, w: W - 80, h: H - 80 } : { x: 40, y: 200, w: W - 80, h: H - 240 };
    const pn = P.panel(R, { bg: 'cyan' });
    const { w, vh } = fitBrowser(ctx, img, L ? 1560 : 940, L ? 860 : 1100);
    const br = comicBrowser(ctx, img, w, vh, { cell: 12 });
    const bx = (R.w - br.w) / 2, by = L ? (R.h - br.h) / 2 + 30 : 170;
    br.el.style.left = `${bx}px`; br.el.style.top = `${by}px`;
    pn.el.appendChild(br.el);
    const title = String(img.page_title || '').trim();
    const cap = caption(title ? `Meanwhile, at ${title}\u2026` : 'Meanwhile, in the app\u2026', { x: 30, y: L ? 20 : 40 });
    pn.el.appendChild(cap.el);
    const bb = p.bbox || [0.1, 0.1, 0.8, 0.8];
    const r = br.shot.rect(bb);
    const rr = { x: bx + r.x, y: by + br.chromeH + r.y, w: r.w, h: r.h };
    const ring = markerRing(P, rr, { pad: 22 });
    pn.el.appendChild(ring.el);
    const look = burst(P.doc, { w: 230, h: 170, spikes: 12, fill: 'yellow', seed: 91, shadow: 8, text: 'LOOK!', size: 60 });
    const lx = clamp(rr.x - 70, 20, R.w - 250), ly = clamp(rr.y - 130, 10, R.h - 200);
    look.el.style.left = `${lx}px`; look.el.style.top = `${ly}px`;
    pn.el.appendChild(look.el);
    const tPush = clamp(dur * 0.28, 1.0, 1.6);
    const whole = { x: R.x + bx - 20, y: R.y, w: br.w + 40, h: by + br.h + 30 };
    const focus = { x: R.x + Math.min(rr.x, lx) - 30, y: R.y + Math.min(rr.y - 40, ly) - 20, w: rr.w + 60 + Math.max(0, rr.x - lx), h: rr.h + 80 + Math.max(0, rr.y - ly) };
    const cam = P.track([[0, whole], [tPush, whole], [tPush + 0.75, focus], [dur + 1, { ...focus, x: focus.x + 8, y: focus.y + 6 }]], 40, 2.4);
    const tRing = tPush + 0.6;
    return {
      cues: [{ t: 0.15, sfx: 'appear', gain_db: -12 }, { t: tPush + 0.05, sfx: 'move', gain_db: -12 }, { t: tRing + 0.4, sfx: 'hit', gain_db: -10 }],
      render(t) {
        cap.update(t, 0.05);
        br.shot.update(t, 0.15, 0.55);
        snapIn(br.el, t, -0.05, { rise: 50, from: 0.94 });
        ring.update(t, tRing);
        const s = slam(t, tRing + 0.4);
        css(look.el, { opacity: s.op.toFixed(3), transform: `rotate(-8deg) scale(${s.s.toFixed(4)})` });
        P.camera(t, cam(t));
      },
    };
  },
});

// ------------------------------------------------------------------------------------- FEATURE
comicScene('kit:comic/FEATURE', {
  describe: 'One feature as a two-panel page: the feature name in display lettering beside the hero; the printed product shot in the big panel, the camera pushes in, the cursor arrives, pauses and clicks with a CLICK! burst and speed lines, a yellow marker ring circles the feature.',
  params: {
    image: IMAGE_DOC,
    feature: { type: 'string', default: '', doc: 'feature name (<= 6 words), shown as the headline' },
    bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'feature region [x,y,w,h] (image fractions)' },
    click: { type: 'array', default: [0.5, 0.5], doc: 'click point [x,y] (image fractions)' },
  },
  build(ctx, p, F, P) {
    if (F.portrait) return featurePortrait(ctx, p, F, P);
    const L = !F.portrait, dur = ctx.dur;
    const img = p.image || {};
    const name = String(p.feature || p.label || '').trim();
    const R1 = L ? { x: 40, y: 40, w: 600, h: 1000 } : { x: 40, y: 200, w: 1000, h: 420 };
    const R2 = L ? { x: 666, y: 40, w: 1214, h: 1000 } : { x: 40, y: 646, w: 1000, h: 1234 };
    const p1 = P.panel(R1, { bg: 'action', rays: L ? [0.5, 0.8] : [0.85, 0.6], seed: 23 });
    const cap = caption('New power!', { x: 30, y: 30 });
    p1.el.appendChild(cap.el);
    const head = headline((name || 'The feature').toUpperCase(), L ? { x: 36, y: 120, w: 520, lines: 4, max: 104, min: 64 } : { x: 36, y: 100, w: 620, lines: 3, max: 92, min: 60 });
    p1.el.appendChild(head.el);
    const hero = L ? figure(agentSvg({ pose: 'point', rim: 'white', cape: 'blue' }), 30, 560, 470) : figure(agentSvg({ pose: 'bust', rim: 'white' }), 700, 120, 270);
    p1.el.appendChild(hero);
    const p2 = P.panel(R2, { bg: 'cyan' });
    const { w, vh } = fitBrowser(ctx, img, L ? 1120 : 940, L ? 880 : 1100);
    const br = comicBrowser(ctx, img, w, vh, { cell: 12 });
    const bx = (R2.w - br.w) / 2, by = L ? (R2.h - br.h) / 2 : 40;
    br.el.style.left = `${bx}px`; br.el.style.top = `${by}px`;
    p2.el.appendChild(br.el);
    const bb = p.bbox || [0.1, 0.1, 0.8, 0.8];
    const click = p.click || [bb[0] + bb[2] / 2, bb[1] + bb[3] / 2];
    const r = br.shot.rect(bb);
    const rr = { x: bx + r.x, y: by + br.chromeH + r.y, w: r.w, h: r.h };
    const [cxl, cyl] = br.shot.pt(click[0], click[1]);
    const cpt = [bx + cxl, by + br.chromeH + cyl];
    const ring = markerRing(P, rr, { pad: 20 });
    p2.el.appendChild(ring.el);
    const sl = h('div', 'cx-abs');
    sl.style.cssText = `left:${cpt[0] - 210}px;top:${cpt[1] - 210}px;width:420px;height:420px;z-index:31;`;
    sl.appendChild(speedLines(P.doc, 420, 420, 210, 210, { n: 44, clear: 70, seed: 7 }));
    p2.el.appendChild(sl);
    const cur = h('div', 'cx-cursor', { html: CURSOR_SVG });
    p2.el.appendChild(cur);
    const clk = burst(P.doc, { w: 250, h: 170, spikes: 13, fill: 'yellow', seed: 33, shadow: 8, text: 'CLICK!', size: 58 });
    clk.el.style.left = `${clamp(rr.x + rr.w - 30, 10, R2.w - 260)}px`; clk.el.style.top = `${clamp(rr.y - 140, 10, R2.h - 190)}px`;
    p2.el.appendChild(clk.el);
    const tPush = clamp(dur * 0.2, 0.9, 1.3);
    const sync = Number(p._sync && p._sync.click);
    const press = Number.isFinite(sync) && sync > tPush + 0.8 && sync < dur - 0.6 ? sync : clamp(dur * 0.45, tPush + 1.2, Math.max(tPush + 1.2, dur - 1.4));
    const arrive = press - 0.62;
    const from = [cpt[0] + 260, cpt[1] + 220];
    const whole = { x: R2.x, y: R2.y, w: R2.w, h: L ? R2.h : Math.min(R2.h, br.h + 120) };
    const focus = { x: R2.x + rr.x - 60, y: R2.y + rr.y - 120, w: rr.w + 260, h: rr.h + 240 };
    const cam = P.track(L ? [[0, 'page'], [tPush, 'page'], [tPush + 0.75, focus], [dur + 1, { ...focus, x: focus.x + 8, y: focus.y + 6 }]]
      : [[0, R1], [0.6, R1], [tPush + 0.2, whole], [tPush + 0.95, focus], [dur + 1, { ...focus, y: focus.y + 6 }]], 30, L ? 2.0 : 1.6);
    return {
      cues: [{ t: 0.2, sfx: 'appear', gain_db: -12 }, { t: tPush + 0.05, sfx: 'move', gain_db: -12 }, { t: press, sfx: 'click', gain_db: -4 }, { t: press + 0.05, sfx: 'hit', gain_db: -10 }],
      render(t) {
        P.spinRays(t);
        cap.update(t, 0.1);
        head.update(t, 0.25, 0.1);
        const hu = seg(t, 0, 0.5, ease.outCubic);
        css(hero, { transform: `translate(${((1 - hu) * -60).toFixed(1)}px,0)` });
        br.shot.update(t, 0.2, 0.55);
        snapIn(br.el, t, -0.05, { rise: 50, from: 0.95 });
        // cursor: arc in, pause >= 0.6 s, press with a dip
        const u = seg(t, arrive - 0.7, arrive, ease.inOutCubic);
        const x = lerp(from[0], cpt[0], u), y = lerp(from[1], cpt[1], u) - Math.sin(Math.PI * u) * 50;
        const dip = t >= press ? Math.exp(-(t - press) * 14) : 0;
        css(cur, { opacity: seg(t, arrive - 0.9, arrive - 0.65).toFixed(3), transform: `translate(${(x - 6).toFixed(1)}px,${(y - 6).toFixed(1)}px) scale(${(1.2 * (1 - 0.18 * dip)).toFixed(4)})` });
        const k = seg(t, press, press + 0.12);
        css(sl, { opacity: (t >= press ? 1 - seg(t, press + 0.5, press + 0.9) : 0).toFixed(3), transform: `scale(${(0.7 + 0.3 * k).toFixed(3)})` });
        const s = slam(t, press + 0.02, { from: 1.8 });
        css(clk.el, { opacity: s.op.toFixed(3), transform: `rotate(9deg) scale(${s.s.toFixed(4)})` });
        ring.update(t, press + 0.15);
        P.camera(t, cam(t), { shakes: [press + 0.02], amp: 6 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- SCROLL
comicScene('kit:comic/SCROLL', {
  describe: 'A full-page capture printed in an inked browser frame scrolls top to bottom inside a blue sunburst panel; white motion streaks rush past and a SWOOSH! lands as the scroll starts.',
  params: { image: IMAGE_DOC, scroll: { type: 'array', default: [0, 1], doc: '[from, to] scroll fractions' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, dur = ctx.dur;
    const img = p.image || {};
    const R = L ? { x: 40, y: 40, w: W - 80, h: H - 80 } : { x: 40, y: 200, w: W - 80, h: H - 240 };
    const pn = P.panel(R, { bg: 'blue', rays: [0.5, 0.5], seed: 41, spin: 1.5 });
    const bw = L ? 1180 : 900, vh = L ? 800 : 1200;
    const b = scrollBrowser(ctx, img, bw, vh);
    const bx = L ? (R.w - bw) / 2 - 110 : (R.w - bw) / 2, by = L ? (R.h - b.h) / 2 + 50 : 130;
    b.el.style.left = `${bx}px`; b.el.style.top = `${by}px`;
    pn.el.appendChild(b.el);
    const streaks = [];
    for (let i = 0; i < 9; i++) {
      const s = h('div', 'cx-abs');
      const x = L ? bx + bw + 50 + (i % 3) * 46 : (i % 2 ? bx - 30 : bx + bw + 14) + (i % 3) * 4;
      s.style.cssText = `left:${x}px;top:0;width:${L ? 10 : 9}px;height:${120 + (i * 37) % 140}px;background:${C.white};box-shadow:0 0 0 4px ${C.ink};border-radius:6px;`;
      pn.el.appendChild(s);
      streaks.push({ el: s, ph: (i * 0.37) % 1, sp: 1.6 + (i % 4) * 0.35 });
    }
    const t0 = 0.7, t1 = Math.max(t0 + 1, dur - 0.7);
    const sw = sfx('SWOOSH!', L ? { x: bx + bw + 20, y: R.h / 2 - 60, size: 104, color: C.yellow, rot: -10 } : { x: R.w - 400, y: by + b.h - 160, size: 92, color: C.yellow, rot: -10 });
    pn.el.appendChild(sw.el);
    const url = String(img.url || img.page_title || '').replace(/^[a-z]+:\/\/(\/)?/i, '').replace(/\/$/, '');
    const cap = caption(url ? `Scrolling ${url}\u2026` : 'Scrolling the whole page\u2026', { x: 30, y: L ? 22 : 40 });
    pn.el.appendChild(cap.el);
    const [s0, s1] = (p.scroll || [0, 1]).map(Number);
    const cam = P.track([[0, [W / 2, H / 2, 1.04]], [dur + 1, [W / 2, H / 2 + 8, 1.0]]]);
    return {
      cues: [{ t: t0, sfx: 'move', gain_db: -10 }, { t: t0 + 0.1, sfx: 'appear', gain_db: -12 }],
      render(t) {
        P.spinRays(t);
        cap.update(t, 0.05);
        snapIn(b.el, t, -0.1, { rise: 60, from: 0.95 });
        const u = seg(t, t0, t1, ease.inOutCubic);
        b.setScroll(lerp(s0, s1, u));
        const v = seg(t, t0, t0 + 0.4) * (1 - seg(t, t1 - 0.5, t1));
        streaks.forEach((s) => {
          const y = ((s.ph + t * s.sp) % 1) * (R.h + 300) - 300;
          css(s.el, { opacity: (v * 0.95).toFixed(3), transform: `translate(0,${(R.h - y - 200).toFixed(1)}px)` });
        });
        sw.update(t, t0 + 0.1);
        P.camera(t, cam(t), { drift: 1.0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- BEFORE_AFTER
/** Zig-zag lightning gutter points between (x0, y0) and (x1, y1) (page coords), `n` teeth. */
function bolt(x0, y0, x1, y1, n, amp) {
  const pts = [];
  const dx = x1 - x0, dy = y1 - y0, L = Math.hypot(dx, dy);
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    const off = i === 0 || i === n ? 0 : (i % 2 ? amp : -amp);
    pts.push([x0 + dx * u + (-dy / L) * off, y0 + dy * u + (dx / L) * off]);
  }
  return pts;
}

comicScene('kit:comic/BEFORE_AFTER', {
  describe: 'The money shot as a split page: BEFORE in grey dots (desaturated), then a lightning-bolt gutter cracks open (KRAK!) and the AFTER panel slams in full colour over a sunburst.',
  params: {
    before: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
    after: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
  },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, dur = ctx.dur;
    const wipeAt = clamp(dur * 0.42, 1.3, dur - 1.6);
    const top = L ? 40 : 200, bot = H - 40;
    const g = L ? bolt(W * 0.52, top - 20, W * 0.46, bot + 20, 6, 34) : bolt(20, H * 0.53, W - 20, H * 0.5, 5, 30);
    const pa = P.panel({ x: 40, y: top, w: W - 80, h: bot - top }, { bg: 'grey' });
    const pb = P.panel({ x: 40, y: top, w: W - 80, h: bot - top }, { bg: 'sun', rays: L ? [0.75, 0.5] : [0.5, 0.78], seed: 9 });
    const loc = (pts) => pts.map(([x, y]) => `${(x - 40).toFixed(1)}px ${(y - top).toFixed(1)}px`).join(',');
    const clipB = L ? `polygon(${loc([g[0]])}, ${W}px -40px, ${W}px ${H}px, ${loc(g.slice().reverse())})`
      : `polygon(${loc(g)}, ${W}px ${H}px, -40px ${H}px)`;
    const cw = L ? 760 : 900, ch = L ? 700 : 560;
    const bb = heroBlock(ctx, p.before || {}, { width: cw, maxH: ch, t0: 0.1, develop: 0.4, badgeAt: 0.7, wrap: true, portrait: !L, hug: true });
    const ab = heroBlock(ctx, p.after || {}, { width: cw, maxH: ch, t0: wipeAt + 0.15, develop: 0.4, badgeAt: wipeAt + 0.5, wrap: true, portrait: !L, hug: true });
    const half = L ? { a: [(W * 0.49 - 40) / 2, (bot - top) / 2 + 20], b: [W * 0.49 + (W * 0.51 - 40) / 2 - 40, (bot - top) / 2 + 20] }
      : { a: [(W - 80) / 2, (H * 0.515 - top) / 2 + 40], b: [(W - 80) / 2, H * 0.515 - top + (bot - H * 0.515) * 0.42] };
    bb.el.style.left = `${half.a[0] - bb.w / 2}px`; bb.el.style.top = `${half.a[1] - bb.h / 2}px`;
    ab.el.style.left = `${half.b[0] - ab.w / 2}px`; ab.el.style.top = `${half.b[1] - ab.h / 2}px`;
    bb.el.style.filter = 'grayscale(1) contrast(.92)';
    pa.el.appendChild(bb.el);
    pb.el.appendChild(ab.el);
    const capA = caption('Before\u2026', { x: half.a[0] - bb.w / 2, y: half.a[1] - bb.h / 2 - 78, white: true });
    pa.el.appendChild(capA.el);
    const capB = caption('After!', { x: half.b[0] + ab.w / 2 - 150, y: half.b[1] - ab.h / 2 - 78 });
    pb.el.appendChild(capB.el);
    const gpath = g.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const gut = P.svg(W, H, `<path d="${gpath}" fill="none" stroke="${C.ink}" stroke-width="30" stroke-linejoin="miter" pathLength="1" stroke-dasharray="1 1"/>` +
      `<path d="${gpath}" fill="none" stroke="${C.paper}" stroke-width="14" stroke-linejoin="miter" pathLength="1" stroke-dasharray="1 1"/>`, { style: 'position:absolute;left:0;top:0;z-index:40;' });
    P.content.appendChild(gut);
    const krak = sfx('KRAK!', L ? { x: W * 0.49 - 170, y: H * 0.42, size: 120, color: C.yellow, rot: -10 } : { x: W / 2 - 160, y: H * 0.515 - 90, size: 108, color: C.yellow, rot: -6 });
    P.content.appendChild(krak.el);
    krak.el.style.zIndex = '45';
    const leftR = { x: 40 + half.a[0] - bb.w / 2 - 50, y: top + half.a[1] - bb.h / 2 - 90, w: bb.w + 100, h: bb.h + 140 };
    const cam = P.track([[0, leftR], [wipeAt - 0.1, leftR], [wipeAt + 0.45, 'page'], [dur + 1, L ? [W / 2, H / 2, 1.02] : 'page']], 30, 1.6);
    const cues = [...(bb.cues || []).filter((c) => c.sfx !== 'pass'), { t: wipeAt, sfx: 'hit', gain_db: -4 }, { t: wipeAt + 0.25, sfx: 'move', gain_db: -14 },
      ...(ab.cues || []).filter((c) => c.sfx === 'pass' || c.sfx === 'appear')];
    return {
      cues,
      render(t) {
        P.spinRays(t);
        capA.update(t, 0.05);
        bb.update(t); ab.update(t);
        snapIn(bb.el, t, 0.0, { rise: 40, from: 0.94, rot: -1.5 });
        const u = seg(t, wipeAt, wipeAt + 0.3, ease.outCubic);
        const off = (1 - u) * (L ? W * 0.6 : H * 0.5);
        css(pb.el, { clipPath: clipB, visibility: t >= wipeAt ? 'visible' : 'hidden', transform: L ? `translate(${off.toFixed(1)}px,0)` : `translate(0,${off.toFixed(1)}px)` });
        const gu = seg(t, wipeAt - 0.05, wipeAt + 0.2, ease.outCubic);
        for (const e of gut.children) css(e, { strokeDashoffset: (1 - gu).toFixed(4) });
        css(gut, { visibility: t >= wipeAt - 0.05 ? 'visible' : 'hidden' });
        capB.update(t, wipeAt + 0.35);
        snapIn(ab.el, t, wipeAt + 0.12, { rise: 0, from: 0.9, rot: 1.5 });
        krak.update(t, wipeAt + 0.02);
        P.camera(t, cam(t), { shakes: [wipeAt + 0.05], amp: 12 });
      },
    };
  },
});
