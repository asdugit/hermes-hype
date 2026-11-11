// Hype kit "blueprint" — lettering scenes: TITLE (general arrangement), PROBLEM (requirement spec), PLAN
// (numbered process flow), STATS (measurement readouts), CALLOUT (margin note), END (final title block, signed).

import { css } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { bpScene } from './sheet.js';
import { line, stroke, rectD, circleD, dimension, balloon, checkD, el, arrow, f1, P as OP, platePts, d as pd } from './draw.js';
import { header, note, esc, fitS, stamp, leaderTo } from './parts.js';

/** Font size (px) so `s` fits w px on `lines` lines (Space Grotesk caps ~0.62 em per char). */
const fitTitle = (s, w, max, min, per = 0.62, lines = 1) => {
  for (let z = max; z >= min; z -= 4) if (Math.ceil(String(s).length * z * per / w) <= lines) return z;
  return min;
};

/** Split a tagline so the last sentence (or last clause) can be set in the heavier weight. */
function taglineHtml(s) {
  const t = String(s || '').trim();
  const m = /^(.*?[.!?])\s+(.+)$/.exec(t);
  return m ? `${esc(m[1])} <b>${esc(m[2])}</b>` : esc(t);
}

// --------------------------------------------------------------------------------------------- TITLE
bpScene('kit:blueprint/TITLE', {
  describe: 'General-arrangement title sheet: construction lines (cap height, baseline) plot across the sheet, the product name is lettered huge with the pen riding the edge, the tagline and rule follow; an exploded plate stack balloons the name, purpose and tagline; the title block stamps REV A.',
  params: {
    title: { type: 'string', default: '', doc: 'product / film title' }, tagline: { type: 'string', default: '', doc: '<= 10 words' },
    product: { type: 'string', default: '', doc: 'product name (used when title is empty)' },
    one_liner: { type: 'string', default: '', doc: 'shown as the PURPOSE balloon' },
  },
  build(ctx, p, F, S) {
    const L = S.L, bx = S.box, P = S.P;
    const title = String(p.title || p.product || '').trim() || 'Untitled';
    const tw = L ? bx.w : 1040;
    const size = fitTitle(title.toUpperCase(), tw, L ? 150 : 156, 72, 0.64, L ? 2 : 1);
    const x = bx.x, y0 = L ? bx.y + 40 : bx.y + 60;
    const kick = S.text('bp-kick', `General arrangement \u00b7 ${fitS(String(p.product || title).toUpperCase(), 28)}`, x, y0);
    const ty = y0 + 58;
    const tEl = S.text('bp-title', title, x, ty, { size, w: tw });
    tEl.style.whiteSpace = L ? 'normal' : 'pre';
    const lines = L ? Math.ceil(title.length * size * 0.64 / tw) : 1;
    const capY = ty + size * 0.12, baseY = ty + size * 0.84;
    // construction: cap height + baseline across the sheet, labelled at the right
    const cx0 = S.bd + 10, cx1 = S.W - S.bd - 10;
    P.add(line(S.svg, [[cx0, capY], [cx1, capY]], 'cons'));
    P.add(line(S.svg, [[cx0, baseY], [cx1, baseY]], 'cons'));
    const t1 = P.plan(0.05, { speed: 7000, gap: 0.02 });
    P.letter(kick, { x, y: y0, w: 520, h: 22 });
    P.letter(tEl, { x, y: ty, w: Math.min(tw, title.length * size * 0.64), h: size * lines * 0.9 }, { factor: 0.35 });
    let y = ty + size * 0.92 * lines + 30;
    const tag = String(p.tagline || '').trim();
    let tgEl = null;
    if (tag) {
      tgEl = S.text('bp-sub', '', x, y, { html: taglineHtml(tag), size: L ? 44 : 40, w: L ? bx.w : 1020 });
      const tl = Math.ceil(tag.length * (L ? 44 : 40) * 0.5 / (L ? bx.w : 1020));
      P.letter(tgEl, { x, y, w: Math.min(L ? bx.w : 1020, tag.length * 20), h: 48 * tl });
      y += tl * (L ? 53 : 48) + 30;
    }
    P.add(line(S.svg, [[x, y], [x + 300, y]], 'obj'));
    P.add(line(S.svg, [[x + 300, y], [x + 640, y]], 'hid'));
    const tTitle = P.plan(t1, { speed: 2600, gap: 0.03 });
    // exploded plate stack (the product's identity as parts): name, purpose, tagline
    const parts = [['NAME', title], ...(p.one_liner ? [['PURPOSE', p.one_liner]] : []), ...(tag ? [['TAGLINE', tag]] : [])];
    const ANG = L ? -18 : -16;
    const ox = L ? 170 : 820, oy = L ? 1290 : 640;
    const g = el(S.svg, 'g', { transform: `translate(${ox} ${oy}) rotate(${ANG})` });
    const a = (Math.PI / 180) * ANG;
    const toSheet = (q) => [ox + q[0] * Math.cos(a) - q[1] * Math.sin(a), oy + q[0] * Math.sin(a) + q[1] * Math.cos(a)];
    P.add(line(g, [[-40, 0], [L ? 760 : 820, 0]], 'ctr'));
    const xs = parts.map((_, i) => 140 + i * (L ? 150 : 250));
    const pa = L ? 74 : 120, pb = L ? 96 : 150;
    xs.slice().reverse().forEach((px, j) => {
      const i = xs.length - 1 - j;
      el(g, 'path', { d: pd(platePts(px, pa, pb), true), class: 'fillsheet' });
      P.add(line(g, platePts(px, pa, pb), i === 0 ? 'obj' : 'thin'));
      P.add(line(g, [[pa, -pb], [pa, pb], [-pa, pb]].map(([u, v]) => OP(px + 7, u, v)), 'thin'));
      if (i === 0) P.add(line(g, [[-pa + 18, -pb + 22], [pa - 18, -pb + 22], [pa - 18, pb - 30], [-pa + 18, pb - 30], [-pa + 18, -pb + 22]].map(([u, v]) => OP(px, u, v)), 'thin'));
    });
    const tPlates = P.plan(0.45, { speed: 6000, gap: 0.01, maxDur: 0.6 });
    parts.forEach(([k, v], i) => {
      // 9:16: a label column right of the stack; 16:9: balloons in a row on a line under the stack (clear of the
      // title, tagline and the title block), vertical leaders from each plate's lower field
      const from = L ? toSheet(OP(xs[i], -20, -pb * 0.55)) : toSheet(OP(xs[i], 0, pb * 0.62));
      const to = L ? [620, 1000 + i * 120] : [from[0], Math.min(S.H - S.bd - 230, from[1] + 120)];
      const lead = line(S.svg, [from, [to[0], to[1] - 21]], 'lead');
      P.add(lead);
      P.pop(el(S.svg, 'circle', { cx: f1(from[0]), cy: f1(from[1]), r: 4, class: 'arrow' }));
      const b = balloon(S.svg, to[0], to[1], i + 1);
      P.add(b.ring); P.pop(b.disc); P.pop(b.num);
      const nm = S.text('bp-part', k, to[0] + 34, to[1] - 24);
      const vv = S.text('bp-lbl', fitS(v, L ? 20 : 22), to[0] + 34, to[1] + 8);
      P.letter(nm, { x: to[0] + 34, y: to[1] - 24, w: 110, h: 28 });
      P.letter(vv, { x: to[0] + 34, y: to[1] + 8, w: Math.min(300, String(v).length * 12), h: 24 });
    });
    const tEnd = P.plan(Math.max(tPlates, 0.9), { speed: 4200, gap: 0.02, maxDur: 0.7 });
    S.titleBlock({ title: `${fitS(title, 16)} \u00b7 GA`, rev: p.rev || 'A' }, Math.min(tEnd, (ctx.dur || 4) - 0.6));
    S.camera([[0, [S.W / 2, S.H / 2, 1.0]], [(ctx.dur || 4) + 1, [S.W / 2 - 8, S.H / 2, 1.018]]]);
    return { cues: [{ t: 0.05, sfx: 'build', gain_db: -14 }, { t: t1, sfx: 'type', gain_db: -12 }], render() {} };
  },
});

// --------------------------------------------------------------------------------------------- PROBLEM
bpScene('kit:blueprint/PROBLEM', {
  describe: "The user's request as a REQUIREMENT on a spec sheet: the note box plots, the prompt letters in character by character in Plex Mono (human input), a leader runs to an empty part outline marked TO BE DESIGNED.",
  params: { text: { type: 'string', default: '', doc: 'verbatim prompt (redacted)' }, truncated: { type: 'bool', default: false, doc: 'adds an ellipsis' } },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
    header(S, 'Requirement \u00b7 REQ-01 \u00b7 from the user', '', bx.x, bx.y + 4);
    const fs = L ? 30 : 32, cw = fs * 0.6;
    const boxW = L ? bx.w : 1020, cols = Math.floor((boxW - 64) / cw);
    const txt = String(p.text || '') + (p.truncated ? ' \u2026' : '');
    const words = txt.split(/\s+/);
    const lines = [];
    let cur = '';
    for (const w of words) { if ((cur + ' ' + w).trim().length > cols) { lines.push(cur); cur = w; } else cur = (cur + ' ' + w).trim(); }
    if (cur) lines.push(cur);
    const maxL = L ? 12 : 9;
    const shown = lines.slice(0, maxL);
    if (lines.length > maxL) shown[maxL - 1] = fitS(shown[maxL - 1] + ' \u2026', cols);
    const lh = Math.round(fs * 1.45);
    const bxX = bx.x, bxY = bx.y + 70, bH = shown.length * lh + 64;
    P.add(stroke(S.svg, rectD(bxX, bxY, boxW, bH), 'obj'));
    P.plan(0.1, { speed: 6000 });
    const body = S.text('bp-t', '', bxX + 32, bxY + 32, { w: boxW - 64 });
    body.style.font = `500 ${fs}px/${lh}px var(--bp-m)`;
    body.style.whiteSpace = 'pre';
    const all = shown.join('\n');
    const typeEnd = Math.min(dur * 0.62, 0.5 + all.length * 0.03);
    // empty part outline (hidden lines) + centre marks, leader from the box
    const pw = L ? 520 : 420, ph = L ? 300 : 320;
    const px = L ? bx.x + (bx.w - pw) / 2 : 1330, py = L ? bxY + bH + 170 : bxY + 40;
    P.add(stroke(S.svg, rectD(px, py, pw, ph), 'hid'), { at: [typeEnd * 0.6, typeEnd * 0.6 + 0.5] });
    P.add(line(S.svg, [[px - 30, py + ph / 2], [px + pw + 30, py + ph / 2]], 'ctr'), { at: [typeEnd * 0.6 + 0.3, typeEnd * 0.6 + 0.6] });
    P.add(line(S.svg, [[px + pw / 2, py - 30], [px + pw / 2, py + ph + 30]], 'ctr'), { at: [typeEnd * 0.6 + 0.35, typeEnd * 0.6 + 0.65] });
    const from = L ? [bxX + boxW / 2, bxY + bH] : [bxX + boxW, bxY + bH / 2];
    const to = L ? [px + pw / 2, py] : [px, py + ph / 2];
    const ld = line(S.svg, L ? [from, [from[0], (from[1] + to[1]) / 2], [to[0], (from[1] + to[1]) / 2], to] : [from, [from[0] + 60, from[1]], [to[0] - 60, to[1]], to], 'lead');
    P.add(ld, { at: [typeEnd + 0.05, typeEnd + 0.45] });
    P.pop(arrow(S.svg, to, L ? 0 : 1, L ? 1 : 0));
    const lbl = S.text('bp-part', 'Part 1 \u2014 to be designed', px, py + ph + 44, { w: pw + 80 });
    P.letter(lbl, { x: px, y: py + ph + 44, w: 320, h: 30 }, { at: [typeEnd + 0.4, typeEnd + 0.8] });
    S.titleBlock({ title: 'REQUIREMENT \u00b7 REQ-01', rev: p.rev || 'A' }, typeEnd + 0.5);
    S.camera([[0, [S.W / 2, S.H / 2, 1.0]], [dur + 1, [S.W / 2 - 30, S.H / 2 - 10, 1.05]]]);
    const n = [...all].length;
    const cues = [];
    for (let i = 0; i < Math.min(30, Math.floor(n / 3)); i++) cues.push({ t: 0.5 + (typeEnd - 0.5) * (i * 3) / n, sfx: 'type', gain_db: -14 });
    return {
      cues,
      render(t) {
        const k = Math.round(n * seg(t, 0.5, typeEnd));
        const s = [...all].slice(0, k).join('');
        const caret = t < typeEnd + 0.6 && Math.floor(t * 4) % 2 === 0 ? '<span style="color:var(--cyan)">\u258f</span>' : '';
        const htmlS = esc(s) + caret;
        if (body.__h !== htmlS) { body.__h = htmlS; body.innerHTML = htmlS; }
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- PLAN
bpScene('kit:blueprint/PLAN', {
  describe: "The plan as a numbered process flow on a centre line: each step's box plots on the beat (done = object line with a lettered check, active = cyan dashed and still being plotted, pending = construction), arrows advance to the active step.",
  params: { items: { type: 'array', default: [], doc: '[{text, status}] <= 6 (completed|in_progress|pending)' }, more: { type: 'int', default: 0, doc: 'hidden items count' } },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
    const items = (p.items || []).slice(0, 6);
    const n = Math.max(1, items.length);
    header(S, `Process flow \u00b7 ${items.length + (Number(p.more) || 0)} steps`, 'Plan', bx.x, bx.y + 4, { font: 'draw', size: 40 });
    const per = clamp((dur * 0.55) / n, 0.2, 0.5);
    const boxes = [];
    if (!L) {
      const gap = 56, bw = Math.min(330, (bx.w - (n - 1) * gap) / n), bh = 250;
      const totalW = n * bw + (n - 1) * gap, x0 = bx.x + (bx.w - totalW) / 2, cy = bx.y + 420;
      P.add(line(S.svg, [[bx.x - 20, cy], [bx.x + bx.w + 20, cy]], 'ctr'));
      items.forEach((it, i) => boxes.push({ it, x: x0 + i * (bw + gap), y: cy - bh / 2, w: bw, h: bh }));
    } else {
      const gap = 44, bw = bx.w - 120, bh = 130;
      const totalH = n * bh + (n - 1) * gap, y0 = bx.y + 120 + Math.max(0, (bx.h - 260 - totalH) / 2), cx = bx.x + 60 + bw / 2;
      P.add(line(S.svg, [[cx, y0 - 40], [cx, y0 + totalH + 40]], 'ctr'));
      items.forEach((it, i) => boxes.push({ it, x: bx.x + 60, y: y0 + i * (bh + gap), w: bw, h: bh }));
    }
    const t0 = P.plan(0.1, { speed: 8000 });
    const cues = [];
    const active = [];
    boxes.forEach((b, i) => {
      const a = t0 + 0.15 + i * per;
      const st = b.it.status;
      const cls = st === 'completed' ? 'obj' : st === 'in_progress' ? 'lead' : 'hid';
      const r = stroke(S.svg, rectD(b.x, b.y, b.w, b.h), cls);
      if (st === 'in_progress') { r.style.strokeWidth = '2.4px'; active.push({ r, a }); }
      P.add(r, { at: [a, a + per * 0.8] });
      const bl = balloon(S.svg, L ? b.x - 40 : b.x + b.w / 2, L ? b.y + b.h / 2 : b.y - 52, i + 1);
      P.add(bl.ring, { at: [a, a + 0.15] }); P.pop(bl.disc); P.pop(bl.num);
      const fs = L ? 30 : 30;
      const tx = S.text('bp-note', '', b.x + 22, b.y + 22, { w: b.w - 70, size: fs, html: esc(fitS(String(b.it.text || ''), L ? 60 : 64)) });
      tx.style.color = st === 'pending' ? 'var(--line-3)' : 'var(--line)';
      P.letter(tx, { x: b.x + 22, y: b.y + 22, w: Math.min(b.w - 70, 200), h: 60 }, { at: [a + 0.1, a + per * 0.9] });
      const stl = S.text('bp-lbl', st === 'completed' ? 'DONE' : st === 'in_progress' ? 'IN PROGRESS' : 'TO DO', b.x + 22, b.y + b.h - 40);
      stl.style.color = st === 'pending' ? 'var(--line-3)' : 'var(--cyan)';
      P.letter(stl, { x: b.x + 22, y: b.y + b.h - 40, w: 100, h: 22 }, { at: [a + per * 0.5, a + per * 0.9] });
      if (st === 'completed') P.add(stroke(S.svg, checkD(b.x + b.w - 34, b.y + 34, 30), 'obj'), { at: [a + per * 0.7, a + per] });
      if (i < boxes.length - 1) {
        const nb = boxes[i + 1];
        const A = L ? [b.x + b.w / 2 + 160, b.y + b.h] : [b.x + b.w, b.y + b.h / 2];
        const B = L ? [b.x + b.w / 2 + 160, nb.y] : [nb.x, nb.y + nb.h / 2];
        P.add(line(S.svg, [A, [B[0] - (L ? 0 : 4), B[1] - (L ? 4 : 0)]], 'thin'), { at: [a + per * 0.8, a + per] });
        P.pop(arrow(S.svg, B, L ? 0 : 1, L ? 1 : 0));
      }
      if (st !== 'pending') cues.push({ t: a + per * 0.8, sfx: st === 'completed' ? 'click' : 'appear', gain_db: -8 });
    });
    if (p.more) {
      const lb = boxes[boxes.length - 1];
      const e = S.text('bp-lbl', `+ ${p.more} more`, L ? lb.x : lb.x + lb.w - 120, lb.y + lb.h + 24);
      P.letter(e, { x: lb.x, y: lb.y + lb.h + 24, w: 100, h: 22 }, { at: [t0 + n * per, t0 + n * per + 0.2] });
    }
    S.titleBlock({ title: 'PLAN \u00b7 PROCESS FLOW', rev: p.rev || 'A' }, t0 + n * per + 0.1);
    S.camera([[0, [S.W / 2, S.H / 2, 1]], [dur + 1, [S.W / 2 + 10, S.H / 2, 1.02]]]);
    return {
      cues,
      render(t) {
        // the active step is still being drawn: its dashes crawl once it is plotted
        for (const a of active) if (t > a.a + 0.6) css(a.r, { strokeDasharray: '0.012 0.008', strokeDashoffset: (-(t * 0.02) % 1).toFixed(4) });
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- STATS
bpScene('kit:blueprint/STATS', {
  describe: 'Real session numbers as measurement readouts: big Plex Mono numerals count up (whole digits per frame) while their dimension lines extend outwards; caps labels underneath; never invented numbers.',
  params: { stats: { type: 'array', default: [], doc: '[{key, label, value, display}] 1-3, computed from the session' } },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
    const stats = (p.stats || []).slice(0, 3);
    const n = Math.max(1, stats.length);
    header(S, `Measurements \u00b7 ${String(p.label || 'session').toUpperCase()}`, '', bx.x, bx.y + 4);
    const size = L ? (n === 1 ? 210 : 160) : n === 1 ? 240 : n === 2 ? 210 : 190;
    const items = stats.map((s, i) => {
      const disp = String(s.display ?? s.value ?? '');
      const m = /^([^\d]*)(\d[\d,.]*)(.*)$/.exec(disp) || ['', '', '', disp];
      const colW = L ? bx.w : bx.w / n;
      const cx = L ? bx.x + bx.w / 2 : bx.x + colW * (i + 0.5);
      const cy = L ? bx.y + 200 + i * ((bx.h - 220) / n) + size * 0.4 : bx.y + bx.h * 0.5;
      const num = S.text('bp-num', '', cx - colW / 2, cy - size * 0.5, { w: colW, align: 'center' });
      num.style.fontSize = `${size}px`;
      const lbl = S.text('bp-cap', String(s.label || s.key || ''), cx - colW / 2, cy + size * 0.62, { w: colW, align: 'center' });
      lbl.style.fontSize = L ? '26px' : '24px';
      const at = 0.3 + i * 0.16;
      P.letter(lbl, { x: cx - 80, y: cy + size * 0.62, w: 160, h: 26 }, { at: [at + 0.4, at + 0.8] });
      const wN = Math.max(2, (m[2] || '').length) * size * 0.6 + (m[3] ? size * 0.36 * m[3].length * 0.6 : 0);
      const dm = dimension(S.svg, [cx - wN / 2, cy - size * 0.55], [cx + wN / 2, cy - size * 0.55], 30);
      return { s, m, num, lbl, at, dm, cx, cy, wN };
    });
    const t1 = (it) => it.at + 1.0;
    S.titleBlock({ title: 'MEASUREMENTS', rev: p.rev || 'A' }, Math.min(dur - 0.5, 1.6 + n * 0.16));
    S.camera([[0, [S.W / 2, S.H / 2, 1]], [dur + 1, [S.W / 2, S.H / 2 - 6, 1.025]]]);
    return {
      cues: items.map((it) => ({ t: t1(it), sfx: 'hit', gain_db: -6 })),
      render(t) {
        for (const it of items) {
          const u = seg(t, it.at, t1(it), ease.outCubic);
          const body = it.m[2] || '';
          const target = Number(body.replace(/,/g, '')) || 0;
          const dec = (body.split('.')[1] || '').length;
          let v = (target * u).toFixed(dec);
          if (body.includes(',')) v = Number(v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
          if (u >= 1) v = body;
          const htmlS = (t >= it.at ? `${esc(it.m[1] || '')}${esc(v)}${it.m[3] ? `<span class="bp-unit">${esc(it.m[3].trim())}</span>` : ''}` : '');
          if (it.num.__h !== htmlS) { it.num.__h = htmlS; it.num.innerHTML = htmlS; }
          // dimension extends outwards from the centre with the count
          const k = seg(t, it.at, t1(it), ease.outCubic);
          const [ext1, ext2, dl] = it.dm.parts;
          css(dl, { visibility: k > 0 ? 'visible' : 'hidden', strokeDasharray: `${(k * 0.5).toFixed(4)} 1`, strokeDashoffset: `${(-(0.5 - k * 0.5)).toFixed(4)}` });
          dl.setAttribute('pathLength', '1');
          for (const e of [ext1, ext2]) css(e, { visibility: k > 0.05 ? 'visible' : 'hidden' });
          for (const hd of it.dm.heads) css(hd, { visibility: k >= 1 ? 'visible' : 'hidden' });
        }
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- CALLOUT
bpScene('kit:blueprint/CALLOUT', {
  describe: 'One verbatim line as a margin note: the note box and its NOTE tab plot, the words letter in (Space Grotesk), a leader runs from the box into the drawing margin, mono attribution; the longest hold.',
  params: {
    text: { type: 'string', default: '', doc: 'verbatim quote (<= 12 words ideal)' }, who: { type: 'string', default: 'agent', doc: 'user | agent | test' },
    ref: { type: 'string', default: '', doc: 'event id' },
  },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
    const txt = String(p.text || '');
    const size = L ? 58 : txt.length > 60 ? 54 : 64;
    const w = L ? bx.w - 40 : 1280;
    const nl = Math.ceil(txt.length * size * 0.52 / (w - 80));
    const bh = nl * size * 1.18 + 80;
    const x = L ? bx.x + 20 : bx.x + (bx.w - w) / 2, y = L ? bx.y + (bx.h - bh) / 2 - 60 : bx.y + (bx.h - bh) / 2;
    P.add(stroke(S.svg, rectD(x, y, w, bh), 'thin'));
    const tab = S.text('', 'NOTE', x - 1, y - 30);
    tab.style.cssText += 'font:600 15px/1 var(--bp-m);letter-spacing:.2em;color:var(--sheet);background:var(--line);padding:7px 12px;';
    P.pop(tab);
    const q = S.text('bp-note', '', x + 40, y + 40, { html: esc(txt), size, w: w - 80 });
    q.style.lineHeight = '1.18';
    const lt = P.plan(0.15, { speed: 6000 });
    P.letter(q, { x: x + 40, y: y + 40, w: Math.min(w - 80, txt.length * size * 0.5), h: bh - 80 }, { at: [lt, lt + clamp(txt.length * 0.025, 0.5, 1.4)] });
    const who = S.text('bp-lbl', `\u2014 ${String(p.who || 'agent').toUpperCase()}${p.ref ? ' \u00b7 ' + p.ref : ''}`, x, y + bh + 22);
    P.letter(who, { x, y: y + bh + 22, w: 160, h: 24 }, { at: [lt + 1.0, lt + 1.3] });
    const lead = line(S.svg, [[x + w, y + bh / 2], [x + w + 90, y + bh / 2], [x + w + 140, y + bh / 2 + 70]], 'lead');
    if (!L) { P.add(lead, { at: [lt + 0.4, lt + 0.8] }); P.pop(el(S.svg, 'circle', { cx: x + w + 140, cy: y + bh / 2 + 70, r: 4.5, class: 'arrow' })); }
    S.titleBlock({ title: 'NOTE', rev: p.rev || 'A' }, lt + 1.2);
    S.camera([[0, [S.W / 2, S.H / 2, 1]], [dur + 1, [S.W / 2, S.H / 2, 1.03]]]);
    return { cues: [{ t: lt, sfx: 'type', gain_db: -12 }], render() {} };
  },
});

// --------------------------------------------------------------------------------------------- END
bpScene('kit:blueprint/END', {
  describe: 'End card as the final title block, enlarged: product name, tagline, the CTA in a boxed field, URL, "made with Hermes · Hype" as DRAWN BY, a plotted signature and the RELEASED stamp (speedrun: TIME = the PB).',
  params: {
    title: { type: 'string', default: '', doc: 'product name' }, cta: { type: 'string', default: '', doc: 'command or link to try it' },
    url: { type: 'string', default: '', doc: 'repo / site URL' }, credit: { type: 'string', default: 'made with Hermes \u00b7 Hype', doc: 'small credit line' },
    tagline: { type: 'string', default: '', doc: 'optional line under the title' }, pb_display: { type: 'string', default: '', doc: 'speedrun final time (PB)' },
  },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box, P = S.P;
    const title = String(p.title || '').trim() || 'Hype';
    const W = L ? bx.w : 1400, x = L ? bx.x : bx.x + (bx.w - W) / 2;
    const tsz = fitTitle(title.toUpperCase(), W - 80, L ? 120 : 140, 64, 0.64, L ? 2 : 1);
    const rows = [];
    const r1 = tsz * (L ? Math.ceil(title.length * tsz * 0.64 / (W - 80)) : 1) * 0.95 + 80;
    rows.push(['Title', r1]);
    if (p.tagline) rows.push(['Tagline', L ? 120 : 84]);
    if (p.cta) rows.push(['Try it', L ? 130 : 100]);
    if (p.pb_display) rows.push(['Time (PB)', 100]);
    rows.push(['last', L ? 150 : 96]);
    const H = rows.reduce((a, r) => a + r[1], 0);
    const y = L ? bx.y + Math.max(0, (bx.h - H - 120) / 2) : bx.y + (bx.h - H) / 2 - 10;
    P.add(stroke(S.svg, rectD(x, y, W, H), 'obj'));
    let yy = y;
    const cells = [];
    rows.forEach(([k, hh], i) => {
      if (i > 0) P.add(line(S.svg, [[x, yy], [x + W, yy]], 'thin'));
      cells.push([k, yy, hh]);
      yy += hh;
    });
    const t0 = P.plan(0.1, { speed: 7000, gap: 0.02 });
    const key = (s, cx, cy) => { const e = S.text('', s, cx, cy); e.style.cssText += 'font:500 15px/1 var(--bp-m);letter-spacing:.16em;color:var(--line-3);text-transform:uppercase;'; e.dataset.qa = 'off'; P.pop(e); return e; };
    let tl = t0;
    for (const [k, cy, hh] of cells) {
      if (k === 'Title') {
        key('Title', x + 22, cy + 16);
        const e = S.text('bp-title', title, x + 22, cy + 44, { size: tsz, w: W - 44 });
        e.style.whiteSpace = 'normal';
        P.letter(e, { x: x + 22, y: cy + 44, w: Math.min(W - 44, title.length * tsz * 0.64), h: hh - 60 }, { at: [tl, tl + 0.7], factor: 0.3 });
        tl += 0.6;
      } else if (k === 'Tagline') {
        key('Tagline', x + 22, cy + 14);
        const e = S.text('bp-sub', '', x + 22, cy + 36, { html: esc(p.tagline), size: L ? 36 : 38, w: W - 44 });
        P.letter(e, { x: x + 22, y: cy + 36, w: Math.min(W - 44, String(p.tagline).length * 19), h: 40 }, { at: [tl, tl + 0.4] });
        tl += 0.3;
      } else if (k === 'Try it') {
        key('Try it', x + 22, cy + 14);
        const e = S.text('bp-t', p.cta, x + 22, cy + 38, { w: W - 44, nowrap: !L });
        e.style.cssText += `font:500 ${L ? 32 : 40}px/1.15 var(--bp-m);color:var(--cyan);white-space:${L ? 'normal' : 'pre'};`;
        P.letter(e, { x: x + 22, y: cy + 38, w: Math.min(W - 44, String(p.cta).length * 24), h: 46 }, { at: [tl, tl + 0.45] });
        tl += 0.35;
      } else if (k === 'Time (PB)') {
        key('Time (PB)', x + 22, cy + 14);
        const e = S.text('bp-t', String(p.pb_display), x + 22, cy + 34);
        e.style.cssText += 'font:500 56px/1 var(--bp-m);color:var(--line);';
        P.letter(e, { x: x + 22, y: cy + 34, w: 220, h: 56 }, { at: [tl, tl + 0.3] });
        tl += 0.25;
      } else {
        const c1 = W * (L ? 0.46 : (p.url ? 0.46 : 0.3)), c2 = W * (L ? 0.84 : 0.88);
        P.add(line(S.svg, [[x + c1, cy], [x + c1, cy + hh]], 'thin'), { at: [t0, t0 + 0.1] });
        P.add(line(S.svg, [[x + c2, cy], [x + c2, cy + hh]], 'thin'), { at: [t0, t0 + 0.1] });
        key('URL', x + 22, cy + 14);
        const u = S.text('bp-t', fitS(String(p.url || ''), L ? 26 : 44), x + 22, cy + 40, { w: c1 - 44, nowrap: true });
        u.style.cssText += `font:500 ${L ? 22 : 26}px/1 var(--bp-m);`;
        P.letter(u, { x: x + 22, y: cy + 40, w: Math.min(c1 - 44, String(p.url || '').length * 15), h: 28 }, { at: [tl, tl + 0.3] });
        key('Drawn by', x + c1 + 18, cy + 14);
        const cr = S.text('bp-t', String(p.credit || ''), x + c1 + 18, cy + 40, { w: c2 - c1 - 30 });
        cr.style.cssText += `font:500 ${L ? 22 : 24}px/1.15 var(--bp-m);color:var(--line-2);white-space:normal;`;
        P.letter(cr, { x: x + c1 + 18, y: cy + 40, w: 260, h: 28 }, { at: [tl + 0.1, tl + 0.4] });
        key('Rev', x + c2 + 18, cy + 14);
        const rv = S.text('', 'A', x + c2 + 18, cy + 38);
        rv.style.cssText += 'font:600 34px/1 var(--bp-m);color:var(--redline);';
        P.pop(rv);
      }
    }
    // signature + RELEASED stamp
    const sy = y + H + 70, sx = x + W - (L ? 420 : 520);
    P.add(line(S.svg, [[sx, sy], [sx + (L ? 400 : 480), sy]], 'thin'), { at: [tl + 0.2, tl + 0.4] });
    const sig = `M${sx + 20} ${sy - 10} c 20 -40, 30 -40, 24 -6 s 10 16, 26 -18 c 8 -18, 14 6, 10 20 c 16 -30, 34 -34, 40 -10 c 6 18, 18 -14, 34 -8 c 14 6, 20 10, 44 -14`;
    P.add(stroke(S.svg, sig, 'obj'), { at: [tl + 0.4, tl + 0.95] });
    const sl = S.text('bp-lbl', 'APPROVED \u00b7 Hermes', sx, sy + 12);
    P.letter(sl, { x: sx, y: sy + 12, w: 180, h: 22 }, { at: [tl + 0.5, tl + 0.8] });
    const st = stamp(S, 'RELEASED', L ? x + 20 : x + 40, sy - 40, { at: tl + 1.05, rot: -6 });
    S.camera([[0, [S.W / 2, S.H / 2, 1.04]], [dur + 1, [S.W / 2, S.H / 2, 1.0]]]);
    return { cues: [{ t: t0, sfx: 'type', gain_db: -12 }, { t: tl + 1.05, sfx: 'hit', gain_db: -4 }], render(t) { st.update(t); } };
  },
});

export { seg, lerp };
