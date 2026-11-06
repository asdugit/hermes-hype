// Showreel kit "blueprint" — media scenes: HOOK, SCREEN, FEATURE, SCROLL, BEFORE_AFTER. A capture is drawn as a
// dimensioned view: the frame plots with its real pixel size, the screenshot is traced as line art by the pen and
// then develops like a cyanotype exposure into the real colours; detail circles + detail zooms for focus regions.

import { css } from '../base/dom.js';
import { prettyUrl } from '../base/media.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { bpScene, listing, codeHtml } from './sheet.js';
import { line, stroke, rectD, circleD, balloon, cloudD, delta, el, arrow, f1 } from './draw.js';
import { header, note, esc, fitS, stamp, frameDims, leaderTo } from './parts.js';
import { mediaPlates } from './media.js';

const IMAGE_DOC = { type: 'image', default: null, doc: '{asset, path, w, h, url, page_title, full_page} (asset = film asset name)' };

/**
 * A dimensioned view of an image inside rect R (fitted, centred). Returns {r (drawn rect), plates, st (stage times
 * filled by the caller), update(t)}. The frame + dims are queued on the plotter (plan them after calling).
 */
function view(ctx, F, S, img, R, o = {}) {
  const meta = img && typeof img === 'object' ? img : { asset: img };
  const iw = Number(meta.w) || 1440, ih = Number(meta.h) || 900;
  const crop = o.crop || [0, 0, 1, 1];
  const aw = iw * crop[2], ah = ih * crop[3];
  const sc = Math.min(R.w / aw, R.h / ah);
  const w = aw * sc, h = ah * sc;
  const r = { x: R.x + (R.w - w) / 2, y: R.y + (o.top ? 0 : (R.h - h) / 2), w, h };
  const plates = mediaPlates(ctx, F, meta, w, h, { crop });
  css(plates.el, { left: `${r.x}px`, top: `${r.y}px` });
  S.html.insertBefore(plates.el, S.html.firstChild);
  const fd = frameDims(S, r, { wLabel: o.dims === false ? '' : `${Math.round(iw)} px`, hLabel: o.dims === false ? '' : `${Math.round(ih * crop[3])} px`, off: 30 });
  return { r, plates, fd, meta, update: (t, st) => plates.update(t, st) };
}

/** Listing for a content dict (terminal / code / diff) inside rect R; queued on the plotter from t0. */
function contentListing(S, c, R, t0, o = {}) {
  const P = S.P;
  const kind = c.kind || 'code';
  let rows;
  if (kind === 'terminal') rows = [{ g: '$', text: String(c.cmd || ''), cls: 'cmd' }, ...(c.output || []).slice(-(o.maxRows || 8)).map((s) => ({ g: '', text: String(s), cls: '' }))];
  else if (kind === 'diff') {
    rows = [];
    for (const hk of c.hunks || []) for (const [op, text] of hk.lines || []) rows.push({ g: op === '-' ? '\u2212' : op === '+' ? '+' : '', text: String(text), cls: op === '+' ? 'add' : op === '-' ? 'del' : '', html: codeHtml(String(text), c.lang, c.path) });
    rows = rows.slice(0, o.maxRows || 10);
  } else rows = (c.lines || []).slice(0, o.maxRows || 10).map((s, i) => ({ g: String((Number(c.start) || 1) + i), text: String(s), html: codeHtml(String(s), c.lang, c.path) }));
  const fs = o.fs || 22, rowH = Math.round(fs * 1.85);
  const ls = listing(S, rows, { x: R.x, y: R.y, w: R.w, fs, rowH, gut: kind === 'terminal' ? 40 : 56, pad: 16 });
  P.add(stroke(S.svg, rectD(ls.x, ls.y, ls.w, ls.h), 'thin'), { at: [t0, t0 + 0.3] });
  ls.rowEls.forEach((r, i) => P.letter(r.e, ls.rowBox(i), { at: [t0 + 0.2 + i * 0.06, t0 + 0.32 + i * 0.06] }));
  return { ls, end: t0 + 0.32 + rows.length * 0.06, kind };
}

// --------------------------------------------------------------------------------------------- HOOK
bpScene('kit:blueprint/HOOK', {
  describe: 'Scroll-stopper: the hero artefact is plotted fast as a dimensioned view (frame, real pixel size, line-art trace by the pen) and the real capture develops inside it like a cyanotype; a test run gets a PASS stamp; <= 6 word headline lettered on top.',
  params: { hero: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...block data}' } },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
    const hero = p.hero || {};
    const label = String(p.label || '').trim();
    const lsz = L ? 66 : 64;
    let top = bx.y;
    let lab = null;
    if (label) {
      lab = S.text('bp-t', label, bx.x, bx.y + 6, { size: lsz, w: bx.w });
      lab.style.fontWeight = '600'; lab.style.whiteSpace = 'normal'; lab.style.lineHeight = '1.05';
      const nl = Math.ceil(label.length * lsz * 0.55 / bx.w);
      top = bx.y + nl * lsz * 1.05 + 50;
    }
    const kind = hero.kind || (hero.w ? 'image' : 'code');
    const R = { x: bx.x + (L ? 0 : 60), y: top + 10, w: bx.w - (L ? 0 : 120 + 200), h: bx.y + bx.h - top - (L ? 140 : 60) };
    let v = null, cl = null, st = null;
    if (kind === 'image') {
      v = view(ctx, F, S, hero, R);
      P.plan(0.05, { speed: 7000, gap: 0.01, maxDur: 0.6 });
    } else {
      const nr = kind === 'terminal' ? 1 + Math.min(8, (hero.output || []).length) : Math.min(8, (hero.lines || (hero.hunks || []).flatMap((x) => x.lines || [])).length);
      const fsH = L ? 26 : 34, hH = nr * Math.round(fsH * 1.85) + 32;
      cl = contentListing(S, hero, { x: R.x, y: R.y + Math.max(0, (R.h - hH) / 2 - 40), w: R.w, h: R.h }, 0.1, { fs: fsH, maxRows: 8 });
      if (hero.tests_passed || (kind === 'terminal' && hero.ok !== false)) st = stamp(S, hero.tests_passed ? 'PASS' : 'OK', R.x + R.w - 220, cl.ls.y - 26, { at: cl.end + 0.2, rot: -7 });
    }
    if (lab) P.letter(lab, { x: bx.x, y: bx.y + 6, w: Math.min(bx.w, label.length * lsz * 0.55), h: lsz }, { at: [0.25, 0.25 + clamp(label.length * 0.03, 0.4, 0.9)] });
    const stages = { trace: [0.35, 0.95], develop: [1.0, 1.7] };
    S.titleBlock({ title: fitS(String(hero.page_title || hero.path || hero.cmd || 'HERO'), 18), rev: p.rev || 'A' }, 1.2);
    S.camera([[0, [S.W / 2, S.H / 2, 1.06]], [1.6, [S.W / 2, S.H / 2, 1.0]], [dur + 1, [S.W / 2, S.H / 2, 1.02]]]);
    return {
      cues: [{ t: 0.05, sfx: 'build', gain_db: -12 }, { t: stages.develop[0], sfx: 'appear', gain_db: -8 }, ...(st ? [{ t: cl.end + 0.2, sfx: 'pass', gain_db: -4 }] : [])],
      render(t) {
        if (v) {
          const ut = v.update(t, stages);
          // the pen rides the trace edge while the line art is revealed
          if (ut > 0 && ut < 1) css(S.P.pen, { visibility: 'visible', transform: `translate(${(v.r.x + v.r.w * ut).toFixed(1)}px,${(v.r.y + v.r.h * (0.5 + 0.35 * Math.sin(ut * 9))).toFixed(1)}px)` });
        }
        if (st) st.update(t);
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- SCREEN / FEATURE
function screenBuild(ctx, p, F, S, feature) {
  const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
  const img = p.image || {};
  header(S, `View A \u00b7 ${fitS(String(img.page_title || 'screen'), 40)}`, prettyUrl(img.url || ''), bx.x, bx.y + 4, { size: 26, w: bx.w * 0.6 });
  const R = { x: bx.x + (L ? 0 : 40), y: bx.y + 110, w: bx.w - (L ? 0 : feature ? 560 : 280), h: bx.h - (L ? (feature ? 420 : 260) : 150) };
  const v = view(ctx, F, S, img, R);
  const tFrame = P.plan(0.08, { speed: 6000, gap: 0.01, maxDur: 0.6 });
  const stages = { trace: [0.25, 0.85], develop: [0.9, 1.5] };
  const bb = Array.isArray(p.bbox) && p.bbox.length === 4 ? p.bbox.map(Number) : [0.1, 0.1, 0.8, 0.8];
  const r = v.r;
  const fx = r.x + (bb[0] + bb[2] / 2) * r.w, fy = r.y + (bb[1] + bb[3] / 2) * r.h;
  const rad = Math.max(bb[2] * r.w, bb[3] * r.h) / 2 * 1.12 + 10;
  const tC = Math.max(1.55, tFrame);
  P.add(stroke(S.svg, circleD(fx, fy, rad, -Math.PI * 0.75), 'obj'), { at: [tC, tC + 0.45] });
  const bpos = [fx + rad * 0.72 + 30, fy - rad * 0.72 - 30];
  const lead = line(S.svg, [[fx + rad * 0.707, fy - rad * 0.707], [bpos[0] - 15, bpos[1] + 15]], 'lead');
  P.add(lead, { at: [tC + 0.45, tC + 0.55] });
  const b = balloon(S.svg, bpos[0], bpos[1], 'C');
  P.add(b.ring, { at: [tC + 0.5, tC + 0.6] }); P.pop(b.disc); P.pop(b.num);
  const dl = S.text('bp-part', 'Detail C', bpos[0] + 30, bpos[1] - 18);
  dl.style.cssText += 'background:var(--plate);padding:4px 8px;';
  P.letter(dl, { x: bpos[0] + 34, y: bpos[1] - 14, w: 120, h: 28 }, { at: [tC + 0.55, tC + 0.8] });
  const tZ = Math.max(tC + 0.75, Math.min(dur - 1.4, tC + 0.9));
  const z = clamp(Math.min((bx.w * 0.78) / (2 * rad), (bx.h * 0.74) / (2 * rad)), 1.6, 2.8);
  const cues = [{ t: 0.08, sfx: 'build', gain_db: -12 }, { t: stages.develop[0], sfx: 'appear', gain_db: -8 }, { t: tZ, sfx: 'move', gain_db: -12 }];
  let feat = null;
  if (feature) {
    const click = Array.isArray(p.click) && p.click.length === 2 ? p.click.map(Number) : [bb[0] + bb[2] / 2, bb[1] + bb[3] / 2];
    const qx = r.x + click[0] * r.w, qy = r.y + click[1] * r.h;
    const syncClick = Number(p._sync && p._sync.click);
    const tClick = Number.isFinite(syncClick) && syncClick > tZ + 0.4 && syncClick < dur - 0.5 ? syncClick : Math.min(tZ + 1.0, dur - 0.8);
    // click: a crosshair "pen-down" mark + two construction rings
    const mk = [line(S.svg, [[qx - 16, qy], [qx + 16, qy]], 'obj'), line(S.svg, [[qx, qy - 16], [qx, qy + 16]], 'obj')];
    mk.forEach((m) => P.add(m, { at: [tClick, tClick + 0.08] }));
    P.add(stroke(S.svg, circleD(qx, qy, 14), 'lead'), { at: [tClick + 0.02, tClick + 0.15] });
    const ring2 = stroke(S.svg, circleD(qx, qy, 30), 'cons');
    P.add(ring2, { at: [tClick + 0.08, tClick + 0.3] });
    // feature callout box near the detail circle, in the zoomed view's frame
    const name = String(p.feature || p.label || '').trim();
    const fsz = 30;
    // the callout sits on the sheet beside the view (right column on 16:9, below on 9:16), on a plate
    const boxW = L ? Math.min(bx.w, 80 + name.length * fsz * 0.56) : Math.min(470, Math.max(300, 60 + name.length * fsz * 0.56));
    const nl = Math.ceil(name.length * fsz * 0.56 / (boxW - 40));
    const fhB = 42 + nl * fsz * 1.25;
    const cxB = L ? bx.x + (bx.w - boxW) / 2 : r.x + r.w + 60;
    const cyB = L ? r.y + r.h + 90 : clamp(fy - fhB / 2, r.y, r.y + r.h - fhB);
    const plate = S.text('bp-box', '', cxB, cyB);
    plate.style.cssText += `width:${boxW}px;height:${fhB}px;border:none;`;
    P.pop(plate, P.add(stroke(S.svg, rectD(cxB, cyB, boxW, fhB), 'thin'), { at: [tClick + 0.25, tClick + 0.45] }));
    S.html.insertBefore(plate, S.html.firstChild);
    const ft = S.text('bp-note', '', cxB + 20, cyB + 14, { html: `<span class="tag">Feature</span>${esc(name)}`, size: fsz, w: boxW - 36 });
    P.letter(ft, { x: cxB + 20, y: cyB + 14, w: Math.min(boxW - 40, name.length * fsz * 0.5), h: fhB - 28 }, { at: [tClick + 0.35, tClick + 0.8] });
    const fl = line(S.svg, L ? [[cxB + boxW / 2, cyB], [cxB + boxW / 2, (cyB + qy) / 2], [qx, (cyB + qy) / 2], [qx, qy]] : [[cxB, cyB + fhB / 2], [cxB - 30, cyB + fhB / 2], [qx, qy]], 'lead');
    P.add(fl, { at: [tClick + 0.3, tClick + 0.45] });
    cues.push({ t: tClick, sfx: 'click', gain_db: -4 });
    feat = { tClick, union: { x0: Math.min(fx - rad, cxB) - 30, y0: Math.min(fy - rad, cyB, bpos[1] - 40) - 30, x1: Math.max(fx + rad, cxB + boxW, bpos[0] + 200) + 30, y1: Math.max(fy + rad, cyB + fhB) + 30 } };
  }
  S.titleBlock({ title: fitS(String(img.page_title || 'VIEW A'), 18), rev: p.rev || 'A' }, stages.develop[1]);
  // detail zoom: frame the detail circle, its balloon label and (FEATURE) the callout box together
  const U = feat ? feat.union : { x0: fx - rad - 20, y0: Math.min(fy - rad, bpos[1] - 40) - 20, x1: Math.max(fx + rad, bpos[0] + 200) + 20, y1: fy + rad + 20 };
  const zz = clamp(Math.min((S.W - 2 * S.bd - 60) / (U.x1 - U.x0), (S.H - 2 * S.bd - 60) / (U.y1 - U.y0)), 1.15, z);
  const ux = (U.x0 + U.x1) / 2, uy = (U.y0 + U.y1) / 2;
  const cx0 = S.W / 2, cy0 = S.H / 2;
  S.camera([[0, [cx0, cy0, 1.0]], [tZ, [cx0, cy0, 1.01]], [tZ + 0.8, [ux, uy, zz]], [dur + 1, [ux + 4, uy + 4, zz * 1.02]]]);
  return { cues, render(t) { v.update(t, stages); void feat; } };
}

bpScene('kit:blueprint/SCREEN', {
  describe: 'A capture as a dimensioned view: the frame plots with the real pixel size, the pen traces the page as line art, the real screenshot develops inside it; a DETAIL C circle draws on the focus box and the camera zooms into it (>= 1.6x).',
  params: { image: IMAGE_DOC, bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'focus box [x,y,w,h] as image fractions' } },
  build(ctx, p, F, S) { return screenBuild(ctx, p, F, S, false); },
});

bpScene('kit:blueprint/FEATURE', {
  describe: 'As SCREEN, then on the detail view: a pen-down crosshair marks the click (construction rings), a FEATURE callout box letters the feature name on a leader to the region.',
  params: {
    image: IMAGE_DOC, feature: { type: 'string', default: '', doc: 'feature name (<= 6 words)' },
    bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'feature region [x,y,w,h] (image fractions)' },
    click: { type: 'array', default: [0.5, 0.5], doc: 'click point [x,y] (image fractions)' },
  },
  build(ctx, p, F, S) { return screenBuild(ctx, p, F, S, true); },
});

// --------------------------------------------------------------------------------------------- SCROLL
bpScene('kit:blueprint/SCROLL', {
  describe: 'A full-page capture as a long elevation: the page frame plots with its full pixel height dimensioned, the top develops, then the camera pans down the sheet along the page with a section marker A-A riding the view.',
  params: { image: IMAGE_DOC, scroll: { type: 'array', default: [0, 1], doc: '[from, to] scroll fractions' } },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
    const img = p.image || {};
    const iw = Number(img.w) || 1440, ih = Number(img.h) || 2400;
    header(S, `Elevation \u00b7 full page \u00b7 ${Math.round(iw)} \u00d7 ${Math.round(ih)}`, prettyUrl(img.url || ''), bx.x, bx.y + 4, { size: 26, w: bx.w * 0.6 });
    // the page column: show the page at a width that makes it ~2.2 frames tall, cropped to fit the sheet height
    const colW = L ? bx.w - 160 : 760;
    const visH = bx.h - 140;
    const fullH = ih * colW / iw;
    const span = Math.min(fullH, visH * 2.4);
    const sc0 = clamp(Number((p.scroll || [0, 1])[0]) || 0), sc1 = clamp(Number((p.scroll || [0, 1])[1] ?? 1));
    const cropY = (fullH > span ? sc0 * (fullH - span) : 0) / fullH;
    const crop = [0, cropY, 1, span / fullH];
    // the sheet camera pans; the page column is laid out longer than the frame inside the sheet's own coordinates
    const R = { x: L ? bx.x + 40 : bx.x + (bx.w - colW) / 2 - 120, y: bx.y + 110, w: colW, h: span };
    const v = view(ctx, F, S, img, R, { crop, top: true, dims: false });
    P.plan(0.08, { speed: 9000, gap: 0.01, maxDur: 0.5 });
    // height dimension of the full page (real px) on the right
    const r = v.r;
    const hx = r.x + r.w + 60;
    [line(S.svg, [[r.x + r.w + 6, r.y], [hx + 14, r.y]], 'dim'), line(S.svg, [[hx, r.y], [hx, r.y + r.h]], 'dim')].forEach((e) => P.add(e, { at: [0.5, 0.8] }));
    P.pop(arrow(S.svg, [hx, r.y], 0, -1));
    const hl = S.text('bp-lbl', `${Math.round(ih)} px`, hx + 16, r.y + 40);
    P.letter(hl, { x: hx + 16, y: r.y + 40, w: 90, h: 24 }, { at: [0.7, 0.9] });
    // section marker A-A following the view centre
    const secL = line(S.svg, [[r.x - 50, 0], [r.x + r.w + 30, 0]], 'ctr');
    const ta = S.text('bp-part', 'A', r.x - 84, 0);
    const stages = { trace: [0.2, 0.7], develop: [0.75, 1.3] };
    const tS = 1.3, tE = Math.max(tS + 1, dur - 0.4);
    const y0 = S.H / 2, y1 = Math.max(y0, r.y + r.h - visH / 2 + 40);
    S.camera([[0, [S.W / 2, y0, 1.0]], [tS, [S.W / 2, y0, 1.0]], [tE, [S.W / 2, y1, 1.0]], [dur + 1, [S.W / 2, y1, 1.0]]]);
    S.titleBlock({ title: fitS(String(img.page_title || 'ELEVATION'), 18), rev: p.rev || 'A' }, 1.3);
    // the sheet must be as long as the page: stretch the sheet, borders and grid
    const extra = Math.max(0, r.y + r.h + 140 - S.H);
    if (extra > 0) {
      S.sheet.style.height = `${S.H + extra}px`;
      for (const e of S.sheet.querySelectorAll('.bp-border-in, .bp-border-out')) e.style.height = `${parseFloat(e.style.height) + extra}px`;
      for (const e of S.sheet.querySelectorAll('.bp-zone')) if (parseFloat(e.style.top) > S.H / 2 && parseFloat(e.style.left) > 0 && /^\d$/.test(e.textContent)) e.style.top = `${parseFloat(e.style.top) + extra}px`;
    }
    return {
      cues: [{ t: 0.08, sfx: 'build', gain_db: -12 }, { t: tS, sfx: 'move', gain_db: -12 }],
      render(t) {
        v.update(t, stages);
        const u = seg(t, tS, tE, ease.inOutQuad);
        const yy = lerp(y0, y1, u);
        css(secL, { visibility: t > tS - 0.2 ? 'visible' : 'hidden', transform: `translate(0px,${yy.toFixed(1)}px)`, strokeDasharray: '26 7 4 7' });
        secL.removeAttribute('pathLength');
        css(ta, { top: `${(yy - 34).toFixed(1)}px`, visibility: t > tS - 0.2 ? 'visible' : 'hidden' });
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- BEFORE_AFTER
bpScene('kit:blueprint/BEFORE_AFTER', {
  describe: 'Rev A vs Rev B: the before state is drawn as REV A, then REV B plots beside it (below on 9:16) and gets the revision cloud and delta; the title block stamps REV B.',
  params: {
    before: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
    after: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...}' },
  },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
    const gap = L ? 70 : 80;
    const top = bx.y + 70;
    const side = L ? { w: bx.w, h: (bx.h - 140 - gap) / 2 } : { w: (bx.w - gap) / 2, h: bx.h - 170 };
    const R = (i) => (L ? { x: bx.x, y: top + i * (side.h + gap), w: side.w, h: side.h } : { x: bx.x + i * (side.w + gap), y: top, w: side.w, h: side.h });
    const tA = 0.1, tB = clamp(dur * 0.38, 1.3, 2.2);
    const mk = (c, i, t0, label) => {
      const r = R(i);
      const k = S.text('bp-kick', label, r.x, r.y - 40);
      P.letter(k, { x: r.x, y: r.y - 40, w: 260, h: 22 }, { at: [t0, t0 + 0.2] });
      const kind = (c && c.kind) || 'code';
      if (kind === 'image') {
        const v = view(ctx, F, S, c, { x: r.x, y: r.y, w: r.w, h: r.h - 30 }, { dims: false });
        P.plan(t0, { speed: 8000, maxDur: 0.4 });
        const st = { trace: [t0 + 0.2, t0 + 0.6], develop: [t0 + 0.6, t0 + 1.1] };
        return { rect: v.r, update: (t) => v.update(t, st) };
      }
      const cl = contentListing(S, c || {}, { x: r.x, y: r.y, w: r.w, h: r.h }, t0, { fs: L ? 22 : 22, maxRows: L ? 7 : 9 });
      return { rect: { x: cl.ls.x, y: cl.ls.y, w: cl.ls.w, h: cl.ls.h }, update() {} };
    };
    const A = mk(p.before, 0, tA, 'Rev A \u00b7 before');
    const B = mk(p.after, 1, tB, 'Rev B \u00b7 after');
    const tCl = tB + 1.15;
    const rb = B.rect;
    P.add(stroke(S.svg, cloudD(rb.x - 14, rb.y - 14, rb.x + rb.w + 14, rb.y + rb.h + 14, 30), 'cloud'), { at: [tCl, tCl + 0.6] });
    const dl = delta(S.svg, rb.x + rb.w + 14, rb.y - 18, 26, 'B');
    P.pop(dl.tri); P.pop(dl.text);
    S.titleBlock({ title: 'REV A \u2192 REV B', rev: 'B' }, tCl + 0.6);
    S.camera([[0, [S.W / 2, S.H / 2, 1]], [dur + 1, [S.W / 2 + (L ? 0 : 20), S.H / 2 + (L ? 20 : 0), 1.025]]]);
    return {
      cues: [{ t: tA, sfx: 'type', gain_db: -12 }, { t: tB, sfx: 'cut', gain_db: -10 }, { t: tCl + 0.6, sfx: 'hit', gain_db: -6 }],
      render(t) { A.update(t); B.update(t); },
    };
  },
});

export { leaderTo, note, lerp };
