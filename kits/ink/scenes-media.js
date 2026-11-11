// Hype kit "ink" — product pages: HOOK, SCREEN, FEATURE, SCROLL, BEFORE_AFTER. Real captures are taped onto
// the page (cream mat, flat shadow, masking tape); marks over a capture (marker loops, cursor, notes) live on the
// top layer so the capture never covers them.

import { inkScene } from './lib/page.js';
import { h, css } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { mediaOf, prettyUrl } from '../base/media.js';
import { C, form, stroke, arrow, loop, sparkle, tick, drawOn, popIn, place, gpose, settleIn, writeOn, svgBox } from './lib/ink.js';
import { robot, setArm, blink, face } from './lib/cast.js';
import { tapedShot, luggageTag, note, machine, legalPad, codeLine } from './lib/props.js';
import { layer, text, clockOf, fitText, clip, CW } from './lib/scene.js';

const trunc = (s, n) => { s = String(s ?? '').replace(/\t/g, '    '); return s.length > n ? s.slice(0, n - 1) + '\u2026' : s; };
const isWide = (b) => !Array.isArray(b) || b.length < 4 || (b[2] >= 0.8 && b[3] >= 0.8);

/** Fit an image (w x h) into a box; full-page captures keep their top part at the box aspect. Returns {w, h, crop}. */
function fitShot(m, bw, bh) {
  const ar = m.w / m.h, br = bw / bh;
  if (ar >= br) return { w: bw, h: Math.round(bw / ar), crop: [0, 0, 1, 1] };
  if (ar >= br * 0.7) return { w: Math.round(bh * ar), h: bh, crop: [0, 0, 1, 1] };
  return { w: bw, h: bh, crop: [0, 0, 1, clamp((bh / (bw / m.w)) / m.h, 0.05, 1)] };
}

/**
 * A hero content block on paper (HOOK / BEFORE_AFTER): image -> taped capture; terminal -> the little machine;
 * code / diff -> a legal-pad card. Returns {el, w, h, kind, update(t, t0)}.
 */
function heroBlock(ctx, P, c, bw, bh, key) {
  const kind = String((c && c.kind) || 'image');
  if (kind === 'image' || c.asset) {
    const m = mediaOf(ctx, c);
    const f = fitShot(m, bw - 28, bh - 28);
    const s = tapedShot(ctx, P.doc, c, f.w, f.h, { crop: f.crop, key });
    return { el: s.el, w: s.w, h: s.h, kind: 'image', shot: s, update() {} };
  }
  if (kind === 'terminal') {
    const out = (c.output || []).map(String).slice(-8);
    const all = [`$ ${c.cmd || ''}`, ...out];
    const fs = Math.round(clamp((bw - 214) / (Math.max(14, ...all.map((l) => l.length)) * 0.6), 20, 34));
    const M = machine(P.doc, bw, Math.round(clamp(all.length * fs * 1.42 + 190, 380, bh)), { key });
    const lh = Math.round(fs * 1.42), maxC = Math.floor(M.screen.w / (fs * 0.6)), maxR = Math.max(2, Math.floor(M.screen.h / lh));
    const rows = all.slice(0, 1).concat(all.slice(1).slice(-(maxR - 1))).map((s, i) => {
      const bad = /fail|error|traceback|exception/i.test(s), good = /\bpass(ed)?\b|\bok\b|success/i.test(s);
      const r = h('div', 'ik-code-line', { text: trunc(s, maxC) || '\u00a0' });
      r.style.cssText = `position:absolute;left:0;top:${i * lh}px;font-size:${fs}px;line-height:${lh}px;color:${i === 0 ? '#E9B04A' : bad ? '#F2A48A' : good ? '#C3DCC3' : '#E6DAC6'};`;
      M.screen.el.appendChild(r);
      return r;
    });
    return { el: M.el, w: M.w, h: M.h, kind, update(t, t0) { rows.forEach((r, i) => { r.style.visibility = t >= t0 + i * 0.06 ? 'visible' : 'hidden'; }); } };
  }
  // code / diff on a legal pad
  const rows0 = [];
  if (kind === 'diff') for (const hk of c.hunks || []) for (const ln of hk.lines || []) rows0.push([String(ln[0] || ' ')[0], String(ln[1] ?? '')]);
  else for (const ln of c.lines || []) rows0.push([' ', String(ln ?? '')]);
  const margin = 70, top = 80;
  const fs = Math.round(clamp((bw - margin - 50) / (Math.max(14, ...rows0.map((r) => r[1].length)) * 0.6), 20, 30));
  const lh = Math.round(fs * 1.45), maxC = Math.floor((bw - margin - 50) / (fs * 0.6));
  const rows = rows0.slice(0, Math.max(2, Math.floor((bh - top - 30) / lh)));
  const pad = legalPad(P.doc, bw, top + rows.length * lh + 30, { lh, top, margin, key });
  rows.forEach(([op, s], i) => {
    const r = codeLine(trunc(s, maxC), c.lang, c.path);
    r.style.cssText = `position:absolute;left:${margin + 16}px;top:${top + i * lh}px;font-size:${fs}px;line-height:${lh - 6}px;` +
      (op === '+' ? 'color:#2C5D57;' : op === '-' ? 'opacity:.55;text-decoration:line-through;text-decoration-color:#D2603A;text-decoration-thickness:3px;' : '');
    pad.body.appendChild(r);
  });
  return { el: pad.el, w: pad.w, h: pad.h, kind, update() {} };
}

/** Hand-drawn arrow cursor markup (tip at 0,0). */
const CURSOR = form(['path', 'M0,0 L0,50 L13,38 L23,60 L33,55 L23,34 L40,34 Z'], 'cream', 'cursor', { sw: 3.4, noReg: true });

// ------------------------------------------------------------------------------------------------ HOOK
inkScene('kit:ink/HOOK', {
  describe: 'Scroll-stopper: the best real artefact (product capture, green test run, diff) is slapped onto the page with masking tape, outline drawing on, a <= 6 word handwritten label with an arrow points at it, and the robot peeks in from the corner.',
  params: { hero: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...block data}' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const hero = p.hero || {};
    const bw = L ? 1120 : 920, bh = L ? 720 : 760;
    const B = heroBlock(ctx, P, hero, bw, bh, 'hk:hero');
    const bx = L ? Math.round(W - S.r - B.w + 40) : Math.round((W - B.w) / 2), by = L ? Math.round(H / 2 - B.h / 2 + 10) : Math.round((H - B.h) / 2 - 90);
    B.el.style.left = `${bx}px`; B.el.style.top = `${by}px`;
    const label = clip(p.label || '', 44);
    const disc = layer(P, `<circle cx="${bx + B.w / 2}" cy="${by + B.h / 2}" r="${Math.max(B.w, B.h) * 0.62}" fill="${C.peach}" opacity=".7"/>`);
    P.content.appendChild(B.el);
    let lab = null, ar = null;
    if (label) {
      const lw = L ? Math.max(380, bx - S.l - 60) : 840;
      const ls = fitText(label, lw, 3, L ? 82 : 84, 50, CW.hand);
      const lx = L ? S.l + 30 : S.l + 10, ly = L ? S.t + 70 : S.t + 20;
      lab = text(P, 'ik-hand', label, lx, ly, `font-size:${ls}px;width:${lw}px;white-space:normal;line-height:1.05;transform:rotate(-4deg);`, 'top');
      const nl = Math.min(3, Math.ceil((label.length * ls * CW.hand) / lw));
      ar = L ? layer(P, arrow([lx + 120, ly + nl * ls * 1.1 + 20], [bx - 16, by + B.h * 0.4], 'hk:ar', { bend: 60, draw: 'a', sw: 4.5 }), 'top')
        : layer(P, arrow([lx + 520, ly + ls * 1.4], [bx + B.w * 0.6, by + 30], 'hk:ar', { bend: 40, draw: 'a', sw: 4.5 }), 'top');
    }
    const ro = L ? [S.l + 170, H - 60] : [W - 200, by + B.h + 330], rs = L ? 0.95 : 1.05;
    const A = layer(P, `<g data-k="bot"><g transform="translate(${ro[0]},${ro[1]}) scale(${rs})">${robot('r', { pose: 'wave' }).markup}</g></g>` +
      `<g data-k="spk">${sparkle(bx - 30, by + B.h - 40, 16)}${sparkle(bx + B.w + 30, by + 60, 12, 'terra')}</g>`, 'top');
    const bot = A.K.bot[0];
    const cam = P.track([[0, [W / 2 + 30, H / 2 + 10, 1.05]], [D + 0.4, [W / 2, H / 2, 1.0]]]);
    return {
      cues: [{ t: 0.04, sfx: 'move', gain_db: -12 }, { t: T(0.12), sfx: 'appear', gain_db: -8 }, ...(label ? [{ t: T(0.6), sfx: 'type', gain_db: -14 }] : [])],
      render(t) {
        css(disc.el, { opacity: seg(t, -0.2, 0.3).toFixed(3) });
        settleIn(B.el, t, T(0.02), { r: L ? -1.6 : -1.2, rise: 60, spin: -4, from: 1.08, settle: true, dur: 0.3 });
        B.update(t, T(0.25));
        if (lab) { writeOn(lab, seg(t, T(0.55), T(0.95))); drawOn(ar.D.a, seg(t, T(0.85), T(1.2), ease.inOutCubic)); }
        const rp = popIn(t, T(0.45), 0.32, 0.88, true);
        gpose(bot, { ox: ro[0], oy: ro[1], s: rp.s, op: rp.op, y: (1 - rp.s) * 80 });
        setArm(A.K['r-armR'][0], 'r', 150 + Math.sin(t * 7) * 16);
        blink(A.K, 'r', t, 'happy', 0.3);
        css(A.K.spk[0], { opacity: seg(t, T(0.4), T(0.6)).toFixed(3) });
        P.camera(t, cam(t));
      },
    };
  },
});

/** Taped product shot centred on the page + (optional) URL luggage tag. Shared by SCREEN / FEATURE. */
function shotPage(ctx, P, img, o = {}) {
  const L = !P.portrait, W = P.W, H = P.H;
  const m = mediaOf(ctx, img);
  const bw = L ? (o.bw || 1360) : 960, bh = L ? (o.bh || 820) : 1100;
  const f = fitShot(m, bw, bh);
  const s = tapedShot(ctx, P.doc, img, f.w, f.h, { crop: f.crop, key: o.key || 'shot' });
  const sx = Math.round((W - s.w) / 2 + (o.dx || 0)), sy = Math.round((H - s.h) / 2 + (o.dy ?? (L ? 20 : 40)));
  s.el.style.left = `${sx}px`; s.el.style.top = `${sy}px`;
  P.content.appendChild(s.el);
  let tag = null;
  const u = prettyUrl((img && (img.url || img.page_title)) || '');
  if (u && !/^file:/.test(String(img.url || ''))) {
    tag = luggageTag(P.doc, clip(u, 40), { size: L ? 28 : 26, key: `${o.key || 'shot'}:tag` });
    tag.el.style.left = `${sx + (L ? 40 : 20) - tag.off}px`; tag.el.style.top = `${sy - tag.h - 26}px`;
    P.content.appendChild(tag.el);
  } else if (img && img.page_title) {
    tag = luggageTag(P.doc, clip(img.page_title, 40), { size: L ? 28 : 26, key: `${o.key || 'shot'}:tag` });
    tag.el.style.left = `${sx + (L ? 40 : 20) - tag.off}px`; tag.el.style.top = `${sy - tag.h - 26}px`;
    P.content.appendChild(tag.el);
  }
  const R = (bb) => { const r = s.rect(bb); return { x: sx + r.x, y: sy + r.y, w: r.w, h: r.h }; };
  const pt = (fx, fy) => { const q = s.pt(fx, fy); return [sx + q[0], sy + q[1]]; };
  return { s, sx, sy, tag, R, pt, f };
}

// ------------------------------------------------------------------------------------------------ SCREEN
inkScene('kit:ink/SCREEN', {
  describe: 'Real screenshot taped to the page with its URL on a luggage tag: establish wide, then the camera pushes 1.4-1.9x to the focus box while a terracotta marker loop draws around it.',
  params: { image: { type: 'image', default: null, doc: '{asset, path, w, h, url, page_title, full_page} (asset = film asset name)' },
    bbox: { type: 'array', default: null, doc: 'focus box [x,y,w,h] as image fractions' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, T = clockOf(ctx.dur), D = ctx.dur;
    const sp = shotPage(ctx, P, p.image, { key: 'sc' });
    const wide = isWide(p.bbox);
    const fr = wide ? null : sp.R(p.bbox);
    const lp = fr ? layer(P, loop(fr.x, fr.y, fr.w, fr.h, 'sc:loop', { draw: 'l', pad: 20 }), 'top') : null;
    const tLoop = T(1.3);
    const whole = { x: sp.sx, y: sp.sy - (sp.tag ? 90 : 0), w: sp.s.w, h: sp.s.h + (sp.tag ? 90 : 0) };
    const z0 = Math.min(1.0, Math.min(W / (whole.w + 140), H / (whole.h + 140)));
    const zf = fr ? clamp(Math.min(W / (fr.w + (L ? 260 : 120)), H / (fr.h + 300)), L ? 1.3 : 1.0, 1.9) : 1.12;
    const cf = fr ? [fr.x + fr.w / 2, fr.y + fr.h / 2] : [W / 2, H / 2 + 20];
    const cam = P.track([[0, [W / 2, H / 2 - (sp.tag ? 30 : 0), Math.max(1, z0) * 0.98]], [T(0.6), [W / 2, H / 2 - (sp.tag ? 30 : 0), 1.0]], [D + 0.3, [cf[0], cf[1], zf]]]);
    return {
      cues: [{ t: 0.04, sfx: 'move', gain_db: -12 }, { t: T(0.6), sfx: 'move', gain_db: -16 }, ...(lp ? [{ t: tLoop, sfx: 'type', gain_db: -14 }] : [])],
      render(t) {
        settleIn(sp.s.el, t, -0.15, { r: L ? -0.8 : -0.6, rise: 50, spin: -2, from: 1.04, settle: true, dur: 0.32 });
        if (sp.tag) { const u = seg(t, T(0.35), T(0.75), ease.outCubic); place(sp.tag.el, { r: -14 * (1 - u) * Math.cos((t - T(0.35)) * 9) - 3, op: u, origin: '0% 50%' }); }
        if (lp) drawOn(lp.D.l, seg(t, tLoop, tLoop + T(0.5), ease.inOutCubic));
        P.camera(t, cam(t), { drift: 1.6 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ FEATURE
inkScene('kit:ink/FEATURE', {
  describe: 'Product capture + one feature: the camera pushes to the region, a hand-drawn cursor arrives, pauses and clicks (ink ripple), a terracotta marker loop circles the feature and a sticky note with the feature name slaps on beside it with an arrow.',
  params: { image: { type: 'image', default: null, doc: '{asset, path, w, h, url, page_title, full_page} (asset = film asset name)' },
    feature: { type: 'string', default: '', doc: 'feature name (<= 6 words), shown on the sticky note' },
    bbox: { type: 'array', default: null, doc: 'feature region [x,y,w,h] (image fractions)' },
    click: { type: 'array', default: null, doc: 'click point [x,y] (image fractions)' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, T = clockOf(ctx.dur), D = ctx.dur;
    const sp = shotPage(ctx, P, p.image, { key: 'fe', dx: L ? -120 : 0, bw: 1240 });
    const bb = isWide(p.bbox) ? [0.3, 0.3, 0.4, 0.4] : p.bbox;
    const fr = sp.R(bb);
    const ck = Array.isArray(p.click) && p.click.length >= 2 ? p.click : [bb[0] + bb[2] / 2, bb[1] + bb[3] / 2];
    const cp = sp.pt(ck[0], ck[1]);
    const sync = p._sync && Number.isFinite(Number(p._sync.click)) ? Number(p._sync.click) : null;
    const tClick = sync != null && sync > 0.6 ? Math.min(sync, D - 0.9) : T(1.0);
    const tArr = tClick - Math.min(0.75, T(0.75));
    // feature note beside the box (side with more room)
    const name = clip(p.feature || p.label || '', 40);
    const nw = L ? 340 : 400;
    const rightRoom = W - (fr.x + fr.w), leftRoom = fr.x;
    const side = L ? (rightRoom > leftRoom ? 1 : -1) : 0;
    const nx = L ? (side > 0 ? Math.min(W - nw - 60, fr.x + fr.w + 70) : Math.max(60, fr.x - nw - 70)) : Math.round(W / 2 - nw / 2 + 120);
    const ny = L ? Math.round(clamp(fr.y + fr.h / 2 - nw / 2, 120, H - nw - 140)) : Math.round(Math.min(H - 560, fr.y + fr.h + 80));
    let nt = null, ar = '';
    if (name) {
      const fsz = fitText(name, nw - 60, 3, 56, 38, CW.hand);
      nt = note(P.doc, nx, ny, nw, { color: 'butter', text: name, size: fsz, tape: true, key: 'fe:note' });
      nt.text.style.top = '54px';
      const a = L ? [side > 0 ? nx - 10 : nx + nw + 10, ny + nw * 0.55] : [nx + nw * 0.3, ny - 10];
      const b = L ? [side > 0 ? fr.x + fr.w + 26 : fr.x - 26, fr.y + fr.h * 0.5] : [fr.x + fr.w * 0.5, fr.y + fr.h + 26];
      ar = arrow(a, b, 'fe:ar', { bend: 30, draw: 'a', sw: 4.5 });
    }
    const top = layer(P, loop(fr.x, fr.y, fr.w, fr.h, 'fe:loop', { draw: 'l', pad: 18 }) + ar +
      `<g data-k="rip"><g transform="translate(${cp[0]},${cp[1]})">${stroke(['circle', 0, 0, 30], 'fe:r1', { sw: 4, stroke: 'terra' })}${stroke(['circle', 0, 0, 52], 'fe:r2', { sw: 3, stroke: 'terra', roughness: 1.4 })}</g></g>` +
      `<g data-k="cur">${CURSOR}</g>`, 'top');
    if (nt) P.top.appendChild(nt.el);
    const cur = top.K.cur[0], rip = top.K.rip[0];
    const from = [cp[0] + (L ? 360 : 220), cp[1] + (L ? 260 : 300)];
    const U = nt ? { x: Math.min(fr.x, nx), y: Math.min(fr.y, ny), x1: Math.max(fr.x + fr.w, nx + nw), y1: Math.max(fr.y + fr.h, ny + nw) }
      : { x: fr.x, y: fr.y, x1: fr.x + fr.w, y1: fr.y + fr.h };
    const zf = clamp(Math.min(W / (U.x1 - U.x + 180), H / (U.y1 - U.y + 220)), 1.0, 1.7);
    const cx = (U.x + U.x1) / 2, cy = (U.y + U.y1) / 2;
    const cam = P.track([[0, [W / 2, H / 2 - 20, 1.0]], [tArr, [W / 2 + (cx - W / 2) * 0.3, H / 2 + (cy - H / 2) * 0.3, 1.05]], [D + 0.3, [cx, cy, zf]]]);
    const tLoop = tClick + T(0.2), tNote = tClick + T(0.45);
    return {
      cues: [{ t: 0.04, sfx: 'move', gain_db: -12 }, { t: tClick, sfx: 'click', gain_db: -4 }, { t: tLoop, sfx: 'type', gain_db: -14 }, ...(nt ? [{ t: tNote, sfx: 'appear', gain_db: -10 }] : [])],
      render(t) {
        settleIn(sp.s.el, t, -0.15, { r: L ? -0.8 : -0.6, rise: 50, spin: -2, from: 1.04, settle: true, dur: 0.32 });
        if (sp.tag) { const u = seg(t, T(0.3), T(0.7), ease.outCubic); place(sp.tag.el, { r: -14 * (1 - u) * Math.cos((t - T(0.3)) * 9) - 3, op: u, origin: '0% 50%' }); }
        const u = seg(t, tArr, tClick - 0.12, ease.inOutCubic);
        const press = t >= tClick - 0.05 && t < tClick + 0.12 ? 0.86 : 1;
        const arc = Math.sin(u * Math.PI) * 50;
        const x = lerp(from[0], cp[0], u) + arc * 0.4, y = lerp(from[1], cp[1], u) - arc;
        cur.setAttribute('transform', `translate(${x.toFixed(1)},${y.toFixed(1)}) rotate(${(-8 * (1 - u)).toFixed(2)}) scale(${press})`);
        cur.setAttribute('opacity', seg(t, tArr - 0.1, tArr + 0.1).toFixed(3));
        const ru = seg(t, tClick, tClick + 0.45, ease.outCubic);
        gpose(rip, { ox: cp[0], oy: cp[1], s: 0.4 + ru * 0.9, op: t >= tClick ? 1 - ru : 0 });
        drawOn(top.D.l, seg(t, tLoop, tLoop + T(0.45), ease.inOutCubic));
        if (nt) { settleIn(nt.el, t, tNote, { r: L ? 3 * side : 2, settle: true, from: 1.12, rise: 0, spin: 4 }); drawOn(top.D.a, seg(t, tNote + 0.15, tNote + 0.45)); }
        P.camera(t, cam(t), { drift: 1.5 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ SCROLL
inkScene('kit:ink/SCROLL', {
  describe: 'A full-page product capture taped onto the page as a long sheet: the page scrolls smoothly inside its frame while a hand-drawn scrollbar thumb travels down and a handwritten "scroll" note points the way.',
  params: { image: { type: 'image', default: null, doc: '{asset, path, w, h, url, page_title, full_page} (asset = film asset name)' },
    scroll: { type: 'array', default: [0, 1], doc: '[from, to] scroll fractions' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, T = clockOf(ctx.dur), D = ctx.dur;
    const m = mediaOf(ctx, p.image);
    const vw = L ? 1180 : 900, vh = L ? 860 : 1260;
    const sc = vw / m.w, visFrac = clamp((vh / sc) / m.h, 0.05, 1);
    const s = tapedShot(ctx, P.doc, p.image, vw, vh, { crop: [0, 0, 1, visFrac], key: 'sl', tapes: 'top' });
    const sx = Math.round((W - s.w) / 2 - (L ? 60 : 0)), sy = Math.round((H - s.h) / 2 + (L ? 10 : 20));
    s.el.style.left = `${sx}px`; s.el.style.top = `${sy}px`;
    P.content.appendChild(s.el);
    const travel = Math.max(0, s.ih - vh);
    const [f0, f1] = Array.isArray(p.scroll) && p.scroll.length >= 2 ? [clamp(Number(p.scroll[0])), clamp(Number(p.scroll[1]))] : [0, 1];
    // hand-drawn scrollbar to the right of the sheet
    const bx = sx + s.w + 34, by = sy + 30, bh2 = s.h - 60;
    const th = Math.max(70, bh2 * visFrac);
    const bar = layer(P, form(['rect', bx, by, 26, bh2, 13], 'cream', 'sl:track', { sw: 2.8 }) +
      `<g data-k="thumb">${form(['rect', bx + 4, by + 4, 18, th - 8, 9], 'terra', 'sl:thumb', { sw: 2.4 })}</g>` +
      (L ? arrow([bx + 120, by + 120], [bx + 120, by + 330], 'sl:ar', { bend: 16, draw: 'a', sw: 4.2 }) : ''), 'top');
    const lab = L ? text(P, 'ik-hand', 'scroll', bx + 70, by + 30, 'font-size:54px;transform:rotate(-6deg);', 'top') : null;
    const ro = L ? [bx + 170, sy + s.h + 30] : [W - 190, sy + s.h + 300], rs = L ? 0.9 : 1.0;
    const A = layer(P, `<g data-k="bot"><g transform="translate(${ro[0]},${ro[1]}) scale(${rs})">${robot('r', { pose: 'point', arms: { r: 160 } }).markup}</g></g>`, 'top');
    const s0 = T(0.5), s1 = Math.max(s0 + 0.6, D - T(0.4));
    const cam = P.track([[0, [W / 2, H / 2 + 10, 1.0]], [D + 0.3, [W / 2 - (L ? 30 : 0), H / 2, 1.04]]]);
    return {
      cues: [{ t: 0.04, sfx: 'move', gain_db: -12 }, { t: s0, sfx: 'move', gain_db: -16 }],
      render(t) {
        settleIn(s.el, t, -0.15, { r: L ? -0.6 : -0.4, rise: 60, spin: -2, from: 1.03, dur: 0.32 });
        const u = lerp(f0, f1, seg(t, s0, s1, ease.inOutCubic));
        if (s.img) s.img.style.transform = `translate(0px,${(-u * travel).toFixed(2)}px)`;
        gpose(bar.K.thumb[0], { y: u * (bh2 - th), op: seg(t, T(0.2), T(0.45)) });
        if (lab) { writeOn(lab, seg(t, T(0.3), T(0.6))); drawOn(bar.D.a, seg(t, T(0.5), T(0.85))); }
        const rp = popIn(t, T(0.3), 0.3, 0.9);
        gpose(A.K.bot[0], { ox: ro[0], oy: ro[1], s: rp.s, op: rp.op, y: Math.sin(t * 2.2) * 2 });
        blink(A.K, 'r', t, 'happy', 0.8);
        P.camera(t, cam(t), { drift: 1.4 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ BEFORE_AFTER
inkScene('kit:ink/BEFORE_AFTER', {
  describe: 'The money shot: before and after as two paper panels on one page; the before lands with a terracotta cross, a hand-drawn arrow sweeps across, the after slaps on with a teal tick and sparkles; handwritten "before" / "after" labels.',
  params: { before: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
    after: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const bw = L ? 780 : 860, bh = L ? 600 : 560;
    const Bb = heroBlock(ctx, P, p.before || {}, bw, bh, 'ba:b');
    const Ba = heroBlock(ctx, P, p.after || {}, bw, bh, 'ba:a');
    const gap = L ? 150 : 170;
    const bx = L ? Math.round(W / 2 - gap / 2 - Bb.w) : Math.round((W - Bb.w) / 2), by = L ? Math.round(H / 2 - Bb.h / 2 + 40) : S.t + 120;
    const ax = L ? Math.round(W / 2 + gap / 2) : Math.round((W - Ba.w) / 2), ay = L ? Math.round(H / 2 - Ba.h / 2 + 40) : by + Bb.h + gap;
    Bb.el.style.left = `${bx}px`; Bb.el.style.top = `${by}px`;
    Ba.el.style.left = `${ax}px`; Ba.el.style.top = `${ay}px`;
    P.content.append(Bb.el, Ba.el);
    const lb = text(P, 'ik-hand', 'before', bx + 10, by - 92, 'font-size:68px;color:#6B5E53;transform:rotate(-4deg);');
    const la = text(P, 'ik-hand', 'after', ax + 10, ay - 92, 'font-size:68px;color:#2C5D57;transform:rotate(-3deg);');
    const a0 = L ? [bx + Bb.w + 18, by + Bb.h * 0.45] : [W / 2 - 40, by + Bb.h + 22];
    const a1 = L ? [ax - 18, ay + Ba.h * 0.45] : [W / 2 - 40, ay - 22];
    const top = layer(P, arrow(a0, a1, 'ba:ar', { bend: L ? -60 : 50, draw: 'a', sw: 5.5, head: 28 }) +
      stroke(['path', `M${bx + Bb.w - 120},${by + 40} L${bx + Bb.w - 30},${by + 120} M${bx + Bb.w - 30},${by + 40} L${bx + Bb.w - 120},${by + 120}`], 'ba:x', { sw: 9, stroke: 'terra', draw: 'x' }) +
      `<circle data-k="tkbg" cx="${ax + Ba.w - 70}" cy="${ay + 70}" r="58" fill="${C.cream}" opacity="0"/>` + tick(ax + Ba.w - 70, ay + 76, 74, 'ba:tk', { draw: 'tk', sw: 10 }) +
      `<g data-k="spk">${sparkle(ax + Ba.w + 26, ay - 20, 18)}${sparkle(ax - 30, ay + Ba.h + 10, 12, 'teal')}${sparkle(ax + Ba.w * 0.5, ay - 40, 10, 'terra')}</g>`, 'top');
    const tA = T(0.95), tT = T(1.45);
    const cam = P.track([[0, L ? [bx + Bb.w / 2 + 120, H / 2, 1.08] : [W / 2, by + Bb.h / 2 + 120, 1.06]], [tA, L ? [W / 2 - 60, H / 2, 1.02] : [W / 2, H / 2 - 60, 1.0]], [D + 0.4, L ? [W / 2 + 20, H / 2, 1.0] : [W / 2, H / 2 + 20, 1.0]]]);
    return {
      cues: [{ t: 0.04, sfx: 'appear', gain_db: -10 }, { t: T(0.5), sfx: 'fail', gain_db: -16 }, { t: tA, sfx: 'move', gain_db: -12 }, { t: tA + 0.3, sfx: 'appear', gain_db: -8 }, { t: tT, sfx: 'pass', gain_db: -8 }],
      render(t) {
        settleIn(Bb.el, t, -0.1, { r: -2, rise: 40, from: 1.05, settle: true, dur: 0.3 });
        Bb.update(t, T(0.1));
        css(Bb.el, { filter: `saturate(${(1 - 0.55 * seg(t, T(0.45), T(0.8))).toFixed(3)})` });
        writeOn(lb, seg(t, T(0.15), T(0.45)));
        drawOn(top.D.x, seg(t, T(0.5), T(0.75), ease.inOutCubic));
        drawOn(top.D.a, seg(t, tA, tA + T(0.35), ease.inOutCubic));
        settleIn(Ba.el, t, tA + 0.25, { r: 1.5, rise: 40, from: 1.08, settle: true, dur: 0.3 });
        Ba.update(t, tA + 0.35);
        writeOn(la, seg(t, tA + 0.4, tA + 0.7));
        drawOn(top.D.tk, seg(t, tT, tT + 0.3, ease.inOutCubic));
        top.K.tkbg[0].setAttribute('opacity', (0.9 * seg(t, tT - 0.1, tT + 0.05)).toFixed(3));
        css(top.K.spk[0], { opacity: (seg(t, tT + 0.1, tT + 0.3) * (0.8 + 0.2 * Math.sin(t * 5))).toFixed(3) });
        P.camera(t, cam(t), { drift: 1.8 });
      },
    };
  },
});
