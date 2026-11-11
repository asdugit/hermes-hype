// Auteur kit "ink" — work pages: CODE and DIFF on a legal pad, TERMINAL on the little machine, MONTAGE as index
// cards pegged on a clothesline.

import { inkScene } from './lib/page.js';
import { h, css } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { C, form, stroke, arrow, underline, drawOn, popIn, place, gpose, settleIn, writeOn, charSpans, typeTo, toolIcon,
  svgBox } from './lib/ink.js';
import { robot, setArm, blink, face, antenna } from './lib/cast.js';
import { legalPad, fileTab, codeLine, machine, indexCard } from './lib/props.js';
import { layer, text, clockOf } from './lib/scene.js';

const trunc = (s, n) => { s = String(s ?? '').replace(/\t/g, '    '); return s.length > n ? s.slice(0, n - 1) + '\u2026' : s; };

/** Mono size so the longest line fits `width` (>= min; longer lines are truncated). */
function monoFit(lines, width, max, min) {
  const n = Math.max(12, ...lines.map((l) => String(l).replace(/\t/g, '    ').length));
  return Math.round(clamp(width / (n * 0.6), min, max));
}

/** Highlighter swipe (mustard, multiply) markup for a row box. */
function swipe(x, y, w, hh, key) {
  return `<g data-k="${key}">${form(['rect', x, y, w, hh, 6], 'mustard', key, { sw: 0, fillOpacity: 0.5 })}</g>`;
}

// ------------------------------------------------------------------------------------------------ CODE
inkScene('kit:ink/CODE', {
  describe: 'The real file written out on a legal pad (ruled lines, terracotta margin) under a folded file tab: lines stream in like handwriting, a mustard highlighter swipes the focus lines, a handwritten note marks them and the camera pushes in; the robot presents from the corner.',
  params: { path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    lines: { type: 'array', default: [], doc: '<= 18 verbatim lines' }, start: { type: 'number', default: 1, doc: 'first line number' },
    focus: { type: 'array', default: null, doc: '[a, b] focus line numbers' }, new_file: { type: 'bool', default: null, doc: 'file was created' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const lines = (Array.isArray(p.lines) ? p.lines : []).slice(0, L ? 16 : 18).map((l) => String(l ?? ''));
    if (!lines.length) lines.push('');
    const start = Number(p.start) || 1;
    const maxW = L ? 1380 : 960, margin = 96;
    const fs = monoFit(lines, maxW - margin - 70, L ? 32 : 30, 22);
    const maxC = Math.floor((maxW - margin - 70) / (fs * 0.6));
    const lh = Math.round(fs * 1.5), top = 104;
    const longest = Math.max(...lines.map((l) => Math.min(maxC, l.length)));
    const pw = Math.round(clamp(margin + 60 + longest * fs * 0.6, L ? 900 : 860, maxW)), ph = top + lines.length * lh + 40;
    const px = L ? Math.round((W - pw) / 2 - 60) : Math.round((W - pw) / 2), py = L ? Math.max(140, Math.round((H - ph) / 2 + 30)) : Math.max(S.t + 120, Math.round((H - S.b - ph) / 2 + 60));
    const pad = legalPad(P.doc, pw, ph, { lh, top, margin, key: 'cd:pad' });
    pad.el.style.left = `${px}px`; pad.el.style.top = `${py}px`;
    const fa = Array.isArray(p.focus) && p.focus.length >= 2 ? [Number(p.focus[0]), Number(p.focus[1])] : null;
    const fi = fa ? [clamp(fa[0] - start, 0, lines.length - 1), clamp(fa[1] - start, 0, lines.length - 1)] : null;
    let swipeEl = null;
    if (fi) {
      const sw = svgBox(P.doc, 0, 0, pw, ph, swipe(margin + 8, top + fi[0] * lh - 4, Math.min(pw - margin - 30, 40 + Math.max(...lines.slice(fi[0], fi[1] + 1).map((l) => Math.min(maxC, l.length))) * fs * 0.6), (fi[1] - fi[0] + 1) * lh, 'hl'));
      pad.body.appendChild(sw.el);
      swipeEl = sw.el.querySelector('[data-k="hl"]');
    }
    const rows = lines.map((ln, i) => {
      const row = codeLine(trunc(ln, maxC), p.lang, p.path);
      row.style.cssText = `position:absolute;left:${margin + 26}px;top:${top + i * lh}px;font-size:${fs}px;line-height:${lh - 6}px;`;
      const num = h('div', 'ik-code-line', { text: String(start + i) });
      num.style.cssText = `position:absolute;left:0;width:${margin - 34}px;text-align:right;top:${top + i * lh + 3}px;font-size:${Math.round(fs * 0.72)}px;line-height:${lh - 6}px;color:#9A8B7C;`;
      num.setAttribute('data-qa', 'off');
      pad.body.append(num, row);
      return { row, num };
    });
    P.content.appendChild(pad.el);
    const tab = fileTab(P.doc, trunc(p.path || 'untitled', 54), { size: L ? 28 : 26, key: 'cd:tab' });
    tab.el.style.left = `${px + 40}px`; tab.el.style.top = `${py - tab.h + 6}px`;
    P.content.insertBefore(tab.el, pad.el);
    let note = null, ar = null;
    const fy = fi ? py + top + ((fi[0] + fi[1] + 1) / 2) * lh : 0;
    if (fi) {
      const lbl = fa[0] === fa[1] ? `line ${fa[0]}` : `lines ${fa[0]}\u2013${fa[1]}`;
      const nx = L ? Math.min(px + pw + 40, W - 330) : px + pw - 300, ny = L ? Math.min(fy - 120, H - 560) : py + ph + 40;
      note = text(P, 'ik-hand', lbl, nx, ny, `font-size:${L ? 52 : 54}px;transform:rotate(-4deg);`, 'top');
      ar = layer(P, L ? arrow([nx + 40, ny + 70], [Math.min(px + pw - 20, nx - 10), fy], 'cd:ar', { bend: -30, draw: 'a' })
        : arrow([nx + 60, ny], [nx, py + ph - 30], 'cd:ar', { bend: 30, draw: 'a' }), 'top');
    }
    let newN = null;
    if (p.new_file) newN = text(P, 'ik-hand', 'new file!', px + tab.w + 70, py - 70, 'font-size:50px;transform:rotate(-5deg);');
    const ro = L ? [Math.min(W - 150, px + pw + 150), H - 70] : [W - 170, H - S.b + 300], rs = L ? 0.9 : 0.95;
    const A = layer(P, `<g data-k="bot"><g transform="translate(${ro[0]},${ro[1]}) scale(${rs})">${robot('r', { pose: 'present' }).markup}</g></g>`);
    const n = rows.length;
    const w0 = T(0.25), w1 = Math.max(w0 + 0.4, Math.min(D * 0.55, w0 + n * 0.11));
    const tH = w1 + T(0.15);
    const focusRect = fi ? { x: px + margin - 20, y: py + top + fi[0] * lh - 30, w: Math.min(pw - margin, 120 + longest * fs * 0.6), h: (fi[1] - fi[0] + 1) * lh + 60 } : null;
    const zf = focusRect ? clamp(Math.min(W / (focusRect.w + 260), H / (focusRect.h + 360)), L ? 1.0 : 1.3, L ? 1.4 : 1.6) : 1;
    const page = [px + pw / 2 + (L ? 40 : 0), py + ph / 2 - 20, 1.0];
    const cam = P.track(focusRect ? [[0, [page[0], page[1] + 30, 0.98]], [w1, page], [D + 0.4, [Math.max(focusRect.x + focusRect.w / 2 + (L ? 60 : 0), px - 40 + W / (2 * zf)), focusRect.y + focusRect.h / 2, zf]]]
      : [[0, [page[0], page[1] + 30, 0.98]], [D + 0.4, page]]);
    const bot = A.K.bot[0];
    return {
      cues: [{ t: 0.05, sfx: 'move', gain_db: -14 }, { t: w0, sfx: 'type', gain_db: -12 }, ...(fi ? [{ t: tH, sfx: 'appear', gain_db: -14 }] : [])],
      render(t) {
        settleIn(pad.el, t, -0.2, { r: L ? -0.6 : -0.4, rise: 40, spin: 2, from: 0.97 });
        settleIn(tab.el, t, T(0.05), { r: -1.5, rise: 20, from: 0.9 });
        rows.forEach((r, i) => {
          const a = lerp(w0, w1, n > 1 ? i / n : 0);
          writeOn(r.row, seg(t, a, a + Math.max(0.1, ((w1 - w0) / n) * 1.4)));
          css(r.num, { opacity: seg(t, a - 0.05, a + 0.1).toFixed(3) });
        });
        if (swipeEl) swipeEl.style.clipPath = `inset(0 ${((1 - seg(t, tH, tH + 0.4, ease.inOutCubic)) * 100).toFixed(2)}% 0 0)`;
        if (note) { writeOn(note, seg(t, tH + 0.35, tH + 0.7)); drawOn(ar.D.a, seg(t, tH + 0.25, tH + 0.55)); }
        if (newN) writeOn(newN, seg(t, T(0.4), T(0.7)));
        const rp = popIn(t, T(0.3), 0.32, 0.9);
        gpose(bot, { ox: ro[0], oy: ro[1], s: rp.s, op: rp.op, y: Math.sin(t * 2.1) * 2 });
        setArm(A.K['r-armR'][0], 'r', 110 + Math.sin(t * 2.6) * 8);
        blink(A.K, 'r', t, 'happy', 0.2);
        P.camera(t, cam(t), { drift: 1.8 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ DIFF
inkScene('kit:ink/DIFF', {
  describe: 'The real diff marked up on a legal pad: removed lines are struck through with a red pen and fade, added lines are written in teal with "+" margin marks, the "+n \u2212m" tally is handwritten; the camera pushes to the change.',
  params: { path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    hunks: { type: 'array', default: [], doc: '[{header, lines:[[op, text]]}] <= 24 rows' }, adds: { type: 'number', default: 0, doc: 'lines added' },
    dels: { type: 'number', default: 0, doc: 'lines removed' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const rowsIn = [];
    for (const hk of Array.isArray(p.hunks) ? p.hunks : []) {
      if (hk && hk.header) rowsIn.push(['@', String(hk.header).replace(/^(@@[^@]*@@).*$/, '$1')]);
      for (const ln of (hk && hk.lines) || []) rowsIn.push([String((ln && ln[0]) || ' ')[0], String((ln && ln[1]) ?? '')]);
    }
    const rows0 = rowsIn.slice(0, L ? 15 : 17);
    if (!rows0.length) rows0.push([' ', '']);
    const maxW = L ? 1380 : 960, margin = 96;
    const fs = monoFit(rows0.map((r) => r[1]), maxW - margin - 70, rows0.length <= 10 ? 34 : L ? 32 : 30, 22);
    const maxC = Math.floor((maxW - margin - 70) / (fs * 0.6));
    const lh = Math.round(fs * 1.5), top = 104;
    const longest = Math.max(...rows0.map((r) => Math.min(maxC, r[1].length)));
    const pw = Math.round(clamp(margin + 60 + longest * fs * 0.6, L ? 900 : 860, maxW)), ph = top + rows0.length * lh + 40;
    const px = L ? Math.round((W - pw) / 2 - 40) : Math.round((W - pw) / 2), py = L ? Math.max(140, Math.round((H - ph) / 2 + 30)) : Math.max(S.t + 140, Math.round((H - S.b - ph) / 2 + 60));
    const pad = legalPad(P.doc, pw, ph, { lh, top, margin, key: 'df:pad' });
    pad.el.style.left = `${px}px`; pad.el.style.top = `${py}px`;
    let marks = '';
    const changes = [];
    rows0.forEach(([op, txt], i) => {
      const y = top + i * lh;
      if (op === '-') {
        const w = Math.min(pw - margin - 40, 30 + Math.min(maxC, txt.length) * fs * 0.6);
        marks += stroke(['line', margin + 20, y + lh * 0.42, margin + 26 + w, y + lh * 0.38], `df:s${i}`, { sw: 4.2, stroke: 'terra', roughness: 1.2, draw: `s${i}` });
        changes.push(i);
      } else if (op === '+') changes.push(i);
    });
    const mk = svgBox(P.doc, 0, 0, pw, ph, marks);
    const rows = rows0.map(([op, txt], i) => {
      const row = op === '@' ? h('div', 'ik-code-line', { text: trunc(txt, maxC) }) : codeLine(trunc(txt, maxC), p.lang, p.path);
      row.style.cssText = `position:absolute;left:${margin + 26}px;top:${top + i * lh}px;font-size:${op === '@' ? Math.round(fs * 0.8) : fs}px;line-height:${lh - 6}px;` +
        (op === '@' ? 'color:#9A8B7C;' : op === '+' ? 'color:#2C5D57;' : '');
      pad.body.appendChild(row);
      let mark = null;
      if (op === '+' || op === '-') {
        mark = h('div', 'ik-hand', { text: op === '+' ? '+' : '\u2212' });
        mark.style.cssText = `left:${margin - 64}px;top:${top + i * lh - 10}px;font-size:${Math.round(lh * 1.05)}px;color:${op === '+' ? '#2C5D57' : '#C2452B'};`;
        pad.body.appendChild(mark);
      }
      return { op, row, mark };
    });
    pad.body.appendChild(mk.el);
    P.content.appendChild(pad.el);
    const tab = fileTab(P.doc, trunc(p.path || 'changes', 54), { size: L ? 28 : 26, key: 'df:tab' });
    tab.el.style.left = `${px + 40}px`; tab.el.style.top = `${py - tab.h + 6}px`;
    P.content.insertBefore(tab.el, pad.el);
    const adds = Number(p.adds) || rows0.filter((r) => r[0] === '+').length, dels = Number(p.dels) || rows0.filter((r) => r[0] === '-').length;
    const tx = L ? Math.min(px + pw + 30, W - 300) : px + pw - 250, ty = L ? py + 40 : py - 150;
    const tally = h('div', 'ik-hand');
    tally.style.cssText = `left:${tx}px;top:${ty}px;font-size:${L ? 76 : 72}px;transform:rotate(-5deg);`;
    tally.append(h('span', '', { text: `+${adds} ` }), h('span', '', { text: `\u2212${dels}` }));
    tally.firstChild.style.color = '#2C5D57';
    P.top.appendChild(tally);
    const tl = layer(P, underline(tx, ty + (L ? 92 : 88), 190, 'df:ul', { draw: 'u', sw: 5 }), 'top');
    const MD = Array.from(mk.el.querySelectorAll('[data-d]'));
    const strikeOf = (i) => MD.filter((e) => e.getAttribute('data-d') === `s${i}`);
    const w0 = T(0.2), w1 = Math.min(D * 0.35, w0 + rows0.length * 0.05);
    const c0 = w1 + T(0.15), cStep = Math.min(T(0.3), (D * 0.42) / Math.max(1, changes.length));
    const tOf = new Map(changes.map((i, k) => [i, c0 + k * cStep]));
    const firstC = changes.length ? changes[0] : 0, lastC = changes.length ? changes[changes.length - 1] : rows0.length - 1;
    const fr = { x: px + margin - 40, y: py + top + firstC * lh - 40, w: Math.min(pw - margin + 40, 160 + longest * fs * 0.6), h: (lastC - firstC + 1) * lh + 80 };
    const zf = clamp(Math.min(W / (fr.w + 300), H / (fr.h + 380)), L ? 1.0 : 1.3, L ? 1.35 : 1.6);
    const page = [px + pw / 2 + (L ? 60 : 0), py + ph / 2 - 20, 1.0];
    const cam = P.track([[0, [page[0], page[1] + 30, 0.98]], [c0, page], [D + 0.4, [Math.max(fr.x + fr.w / 2 + (L ? 80 : 0), px - 40 + W / (2 * zf)), fr.y + fr.h / 2, zf]]]);
    const tT = c0 + changes.length * cStep + 0.1;
    return {
      cues: [{ t: 0.05, sfx: 'move', gain_db: -14 }, { t: w0, sfx: 'type', gain_db: -14 }, ...changes.slice(0, 4).map((i) => ({ t: tOf.get(i), sfx: 'type', gain_db: -12 })),
        { t: Math.min(tT, D - 0.2), sfx: 'appear', gain_db: -12 }],
      render(t) {
        settleIn(pad.el, t, -0.2, { r: L ? 0.5 : 0.3, rise: 40, spin: -2, from: 0.97 });
        settleIn(tab.el, t, T(0.05), { r: -1.5, rise: 20, from: 0.9 });
        rows.forEach((r, i) => {
          const tc = tOf.get(i);
          if (r.op === '+') { writeOn(r.row, seg(t, tc + 0.12, tc + 0.42)); if (r.mark) writeOn(r.mark, seg(t, tc, tc + 0.15)); }
          else {
            const a = lerp(w0, w1, i / rows.length);
            writeOn(r.row, seg(t, a, a + 0.12));
            if (r.op === '-') {
              drawOn(strikeOf(i), seg(t, tc, tc + 0.28, ease.inOutCubic));
              css(r.row, { opacity: (1 - 0.5 * seg(t, tc + 0.15, tc + 0.4)).toFixed(3) });
              if (r.mark) writeOn(r.mark, seg(t, tc, tc + 0.15));
            }
          }
        });
        writeOn(tally, seg(t, tT, tT + 0.35));
        drawOn(tl.D.u, seg(t, tT + 0.3, tT + 0.55));
        P.camera(t, cam(t), { drift: 1.8 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ TERMINAL
inkScene('kit:ink/TERMINAL', {
  describe: 'The real command on the little illustrated terminal machine: the command types, output streams line by line in cream mono on ink; on success the robot raises a tick flag and a PASS seal stamps on (chime), on failure it scratches its head and a FAIL seal lands.',
  params: { cmd: { type: 'string', default: '', doc: 'command line' }, output: { type: 'array', default: [], doc: '<= 12 output lines' },
    truncated_top: { type: 'bool', default: null, doc: 'output was cut at the top' }, exit_code: { type: 'number', default: null, doc: 'exit code' },
    elapsed_s: { type: 'number', default: null, doc: 'runtime seconds' }, ok: { type: 'bool', default: null, doc: 'run succeeded' },
    tests_passed: { type: 'bool', default: null, doc: 'shows the PASS seal + chime' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const out = (Array.isArray(p.output) ? p.output : []).map((s) => String(s ?? '')).slice(-(L ? 11 : 12));
    const fail = p.ok === false || (p.exit_code != null && Number(p.exit_code) !== 0) || p.tests_failed > 0;
    const pass = !fail && p.tests_passed === true;
    const mw = L ? 1180 : 960;
    const all = [`$ ${p.cmd || ''}`, ...out];
    const fs = monoFit(all, mw - 214, L ? 34 : 30, 20);
    const mh = Math.round(clamp(all.length * fs * 1.42 + 170, L ? 480 : 560, L ? 780 : 860));
    const mx = L ? 200 : (W - mw) / 2, my = L ? Math.round((H - mh) / 2 + 10) : Math.round((H - mh) / 2 - 170);
    const M = machine(P.doc, mw, mh, { key: 'tm:m' });
    M.el.style.left = `${mx}px`; M.el.style.top = `${my}px`;
    const maxC = Math.floor(M.screen.w / (fs * 0.6));
    const lh = Math.round(fs * 1.42);
    const maxRows = Math.floor(M.screen.h / lh);
    const shown = out.slice(-(maxRows - 1));
    const cmdRow = h('div', 'ik-code-line');
    cmdRow.style.cssText = `position:absolute;left:0;top:0;font-size:${fs}px;line-height:${lh}px;color:#FBF6EC;`;
    const pr = h('span', '', { text: '$ ' }); pr.style.color = '#E9B04A';
    const cmdT = h('span', '');
    cmdRow.append(pr, cmdT);
    const cmdSpans = charSpans(cmdT, trunc(p.cmd || '', maxC - 2));
    M.screen.el.appendChild(cmdRow);
    const outRows = shown.map((s, i) => {
      const r = h('div', 'ik-code-line', { text: trunc(s, maxC) || '\u00a0' });
      const bad = /fail|error|traceback|exception/i.test(s), good = /\bpass(ed)?\b|\bok\b|success/i.test(s);
      r.style.cssText = `position:absolute;left:0;top:${(i + 1) * lh}px;font-size:${fs}px;line-height:${lh}px;color:${bad ? '#F2A48A' : good ? '#C3DCC3' : '#E6DAC6'};`;
      M.screen.el.appendChild(r);
      return r;
    });
    P.content.appendChild(M.el);
    const sealTxt = fail ? (p.tests_passed === false || /fail/i.test(out.join(' ')) ? 'FAIL' : `exit ${p.exit_code ?? 1}`) : pass ? 'PASS' : `exit ${p.exit_code ?? 0}`;
    const sx = mx + mw - 170, sy = my - 70;
    const seal = svgBox(P.doc, sx, sy, 230, 230, `<circle cx="115" cy="115" r="96" fill="${C.cream}" fill-opacity=".86"/>` +
      form(['circle', 115, 115, 96], null, 'tm:seal1', { sw: 7, stroke: fail ? 'terra' : 'teal', noReg: true }) +
      form(['circle', 115, 115, 80], null, 'tm:seal2', { sw: 3, stroke: fail ? 'terra' : 'teal', noReg: true }) +
      (fail ? stroke(['path', 'M86,150 L144,170 M144,150 L86,170'], 'tm:x', { sw: 6, stroke: 'terra' })
        : stroke(['path', 'M88,158 L108,176 L146,140'], 'tm:tk', { sw: 7, stroke: 'tealD', keep: true })));
    const sealT = h('div', 'ik-seal', { text: sealTxt });
    sealT.style.cssText = `position:absolute;left:0;top:66px;width:230px;text-align:center;font-family:Inter,sans-serif;font-weight:800;font-size:${sealTxt.length > 4 ? 40 : 52}px;letter-spacing:.06em;color:${fail ? '#C2452B' : '#2C5D57'};`;
    seal.el.appendChild(sealT);
    P.top.appendChild(seal.el);
    let el = null;
    if (p.elapsed_s != null && Number(p.elapsed_s) > 0) el = text(P, 'ik-hand', `${Number(p.elapsed_s) < 10 ? Number(p.elapsed_s).toFixed(1) : Math.round(Number(p.elapsed_s))} s`, mx + 40, my + mh + 30, 'font-size:54px;transform:rotate(-3deg);color:#6B5E53;');
    const ro = L ? [mx + mw + 250, Math.min(1000, my + mh + 60)] : [W - 260, my + mh + 340], rs = L ? 1.15 : 1.1;
    const A = layer(P, `<g data-k="bot"><g transform="translate(${ro[0]},${ro[1]}) scale(${rs})">${robot('r', { pose: fail ? 'think' : 'flag', face: 'focus' }).markup}</g></g>`);
    const sync = p._sync && Number.isFinite(Number(p._sync.pass)) ? Number(p._sync.pass) : null;
    const c0 = T(0.25), c1 = c0 + Math.min(T(0.9), 0.045 * cmdSpans.length + 0.2);
    const o0 = c1 + T(0.12), oStep = Math.min(T(0.14), (D * 0.35) / Math.max(1, outRows.length));
    const tPass = sync != null && sync > o0 ? sync : Math.min(D - 0.5, o0 + outRows.length * oStep + T(0.15));
    const bot = A.K.bot[0], armR = A.K['r-armR'][0];
    const cam = P.track([[0, [mx + mw / 2 + (L ? 140 : 0), my + mh / 2 + (L ? 40 : 160), 0.97]], [tPass, [mx + mw / 2 + (L ? 160 : 0), my + mh / 2 + (L ? 30 : 160), 1.02]], [D + 0.4, [mx + mw / 2 + (L ? 190 : 0), my + mh / 2 + (L ? 10 : 140), 1.05]]]);
    return {
      cues: [{ t: c0, sfx: 'type', gain_db: -12 }, { t: tPass, sfx: fail ? 'fail' : 'pass', gain_db: -6 }, { t: tPass + 0.02, sfx: 'hit', gain_db: -12 }],
      render(t) {
        settleIn(M.el, t, -0.2, { r: -0.8, rise: 40, from: 0.96, spin: 2 });
        typeTo(cmdSpans, Math.floor(clamp((t - c0) / (c1 - c0)) * cmdSpans.length + (t >= c1 ? 1 : 0)));
        outRows.forEach((r, i) => { r.style.visibility = t >= o0 + i * oStep ? 'visible' : 'hidden'; });
        const sp = popIn(t, tPass, 0.22, 1.5);
        place(seal.el, { s: sp.s, op: sp.op, r: fail ? 8 : -10 });
        const rp = popIn(t, T(0.2), 0.32, 0.9);
        const hop = t > tPass && !fail ? Math.abs(Math.sin((t - tPass) * 7)) * 10 * Math.exp(-(t - tPass) * 1.5) : 0;
        gpose(bot, { ox: ro[0], oy: ro[1], s: rp.s, op: rp.op, y: -hop });
        if (fail) { setArm(armR, 'r', t >= tPass ? 160 + Math.sin(t * 14) * 8 : 40); face(A.K, 'r', t >= tPass ? 'wow' : 'focus'); }
        else {
          setArm(armR, 'r', lerp(30, 165, seg(t, tPass - 0.1, tPass + 0.2, ease.outBack)) + Math.sin(t * 5) * 4 * seg(t, tPass, tPass + 0.3));
          if (t >= tPass) blink(A.K, 'r', t, 'happy', 0.5); else face(A.K, 'r', 'focus');
        }
        antenna(A.K, 'r', t >= tPass && !fail ? 0.5 + 0.5 * Math.sin((t - tPass) * 10) : 0);
        for (const e of M.K['tm:m-led'] || []) e.setAttribute('opacity', t >= c0 && t < tPass ? (0.5 + 0.5 * Math.sin(t * 20)).toFixed(3) : '1');
        if (el) writeOn(el, seg(t, tPass + 0.1, tPass + 0.4));
        P.camera(t, cam(t), { drift: 2 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ MONTAGE
inkScene('kit:ink/MONTAGE', {
  describe: "Breadth of the agent's work: the real tool calls as index cards pegged on two clotheslines, each with a pictogram doodle and its argument; the camera pans along the lines card to card on the beat while the robot walks beneath.",
  params: { items: { type: 'array', default: [], doc: '[{id, t, kind, tool, arg, clipped}] 3-16 tool calls' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const items = (Array.isArray(p.items) ? p.items : []).slice(0, 16);
    if (!items.length) items.push({ tool: 'work', arg: '' });
    const n = items.length;
    const cw = L ? 540 : 560, chh = L ? 330 : 360, step = L ? 330 : 330;
    const lines = L ? [200, 560] : [560, 1080];
    const x0 = L ? 200 : 120;
    const xs = items.map((_, i) => x0 + i * step);
    const len = xs[n - 1] + cw + 260;
    const yAt = (k, x) => lines[k] + 14 * Math.sin(x / 170 + k * 2);
    let d = '';
    for (const k of [0, 1]) { d += `M-300,${yAt(k, -300).toFixed(1)}`; for (let x = -240; x <= len + 300; x += 60) d += ` L${x},${yAt(k, x).toFixed(1)}`; }
    const A = layer(P, `<path d="${d}" fill="none" stroke="${C.inkS}" stroke-width="3.5"/>`);
    P.bounds(-200, 0, Math.max(W, len + 200), H);
    const cards = items.map((it, i) => {
      const k = i % 2;
      const c = indexCard(P.doc, cw, chh, { tool: trunc(it.tool || it.kind || 'tool', 18), arg: trunc(it.arg || '', 64) },
        { icon: toolIcon(it.kind, it.tool), dot: ['peach', 'mint', 'sky', 'butter'][i % 4], key: `mo:c${i}` });
      const peg = svgBox(P.doc, cw / 2 - 16, -34, 32, 70, form(['rect', 4, 0, 24, 66, 6], 'woodD', `mo:p${i}`, { sw: 2.4 }) + `<path d="M16,8 V58" stroke="${C.wood}" stroke-width="3"/>`);
      c.el.appendChild(peg.el);
      c.el.style.left = `${xs[i]}px`; c.el.style.top = `${yAt(k, xs[i] + cw / 2) + 10}px`;
      P.content.appendChild(c.el);
      return c;
    });
    const ry = L ? 1078 : 1850, rsc = L ? 0.7 : 0.95;
    const R = layer(P, `<g data-k="bot"><g transform="scale(${rsc})">${robot('r', { pose: 'hold' }).markup}</g></g>`);
    const hx = L ? S.l - 40 : S.l - 40, hy = L ? S.t - 50 : S.t + 20;
    const head = h('div', 'ik-hand', { text: `${n} tool call${n === 1 ? '' : 's'}` });
    head.style.cssText = `left:${hx}px;top:${hy}px;font-size:${L ? 60 : 66}px;transform:rotate(-3deg);`;
    F.ov.appendChild(head);
    const hu = svgBox(P.doc, hx, hy + 72, 360, 30, underline(4, 12, 280, 'mo:hu', { draw: 'u', sw: 5 }));
    F.ov.appendChild(hu.el);
    const huD = hu.el.querySelectorAll('[data-d="u"]');
    const a0 = T(0.1), a1 = Math.max(a0 + 0.5, D - T(0.6));
    const at = items.map((_, i) => lerp(a0, a1, n > 1 ? i / (n - 1) : 0));
    const cy = H / 2 + (L ? 10 : 40);
    const camX = (i) => Math.max(W / 2, xs[i] + cw / 2 - (L ? W * 0.16 : 0));
    const keys = [[0, [W / 2, cy, 1.0]]];
    items.forEach((_, i) => keys.push([at[i] + 0.05, [camX(i), cy, 1.0]]));
    keys.push([D + 0.5, [camX(n - 1) + 40, cy, 1.0]]);
    const cam = P.track(keys.filter((k, i, arr) => !i || k[0] > arr[i - 1][0] + 0.05));
    const bot = R.K.bot[0];
    return {
      cues: [{ t: 0.04, sfx: 'move', gain_db: -14 }, ...at.filter((_, i) => i % 2 === 0).slice(0, 8).map((t) => ({ t, sfx: 'appear', gain_db: -15 }))],
      render(t) {
        cards.forEach((c, i) => {
          const sw = Math.sin(t * 2.1 + i * 1.3) * 1.4 * seg(t, at[i], at[i] + 0.4);
          settleIn(c.el, t, at[i] - 0.22, { r: sw + ((i % 3) - 1) * 1.6, rise: -30, from: 0.9, spin: -5, origin: '50% 0%', settle: true, dur: 0.3 });
        });
        const v = cam(t);
        const bx = v[0] - W / 2 + (L ? 260 : 200), walk = t * 7;
        bot.setAttribute('transform', `translate(${bx.toFixed(1)},${(ry - Math.abs(Math.sin(walk)) * 8).toFixed(1)}) rotate(${(Math.sin(walk) * 3).toFixed(2)})`);
        setArm(R.K['r-armL'][0], 'l', 150 + Math.sin(walk) * 10);
        setArm(R.K['r-armR'][0], 'r', 150 - Math.sin(walk) * 10);
        blink(R.K, 'r', t, 'happy', 0.6);
        writeOn(head, seg(t, 0, T(0.3)));
        drawOn(huD, seg(t, T(0.25), T(0.5)));
        P.camera(t, v, { drift: 2.2 });
      },
    };
  },
});
