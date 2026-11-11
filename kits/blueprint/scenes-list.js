// Hype kit "blueprint" — listing scenes: CODE (annotated listing), DIFF (revision cloud + REV B), TERMINAL
// (run listing + gauge drawing + PASS stamp), MONTAGE (parts list + detail views of the tool calls).

import { css } from '../base/dom.js';
import { clock } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { bpScene, listing, codeHtml } from './sheet.js';
import { line, stroke, rectD, circleD, dimension, balloon, cloudD, delta, el, arrow, f1, d as pd } from './draw.js';
import { header, note, esc, fitS, stamp, runNumbers, leaderTo } from './parts.js';

const base = (p) => String(p || '').replace(/^.*[\\/]/, '');

/** Vertical dimension at x spanning [ya, yb] with a rotated label; queued on the plotter. */
function vDim(S, x, ya, yb, label) {
  const P = S.P;
  const ext = (y) => line(S.svg, [[x - 12, y], [x + 26, y]], 'dim');
  [ext(ya), ext(yb), line(S.svg, [[x, ya], [x, yb]], 'dim')].forEach((e) => P.add(e));
  P.pop(arrow(S.svg, [x, ya], 0, -1)); P.pop(arrow(S.svg, [x, yb], 0, 1));
  const t = el(S.svg, 'text', { x: f1(x - 14), y: f1((ya + yb) / 2), 'text-anchor': 'middle', transform: `rotate(-90 ${f1(x - 14)} ${f1((ya + yb) / 2)})`,
    style: 'font:500 20px var(--bp-m);fill:var(--cyan);letter-spacing:.06em' });
  t.textContent = label;
  P.pop(t);
}

// --------------------------------------------------------------------------------------------- CODE
bpScene('kit:blueprint/CODE', {
  describe: 'Annotated listing in a bordered detail box: the frame and gutter rule plot, lines letter in, a dimension brackets the focus range, margin notes land on leaders; non-focus lines fade to construction weight.',
  params: {
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    lines: { type: 'array', default: [], doc: '<= 18 verbatim lines' }, start: { type: 'int', default: 1, doc: 'first line number' },
    focus: { type: 'array', default: [1, 1], doc: '[a, b] focus line numbers' }, total_lines: { type: 'int', default: 0, doc: 'file length' },
    new_file: { type: 'bool', default: false, doc: 'file was created' },
  },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box;
    const lines = (p.lines || []).map((s) => String(s).replace(/\t/g, '    ').replace(/\s+$/, ''));
    const start = Number(p.start) || 1;
    const [fa, fb] = Array.isArray(p.focus) && p.focus.length >= 2 ? p.focus.map(Number) : [start, start];
    const maxRows = L ? 17 : 13;
    let w0 = 0;
    if (lines.length > maxRows) w0 = clamp(Math.round((fa + fb) / 2 - start - maxRows / 2), 0, lines.length - maxRows);
    const vis = lines.slice(w0, w0 + maxRows);
    const fi0 = clamp(fa - start - w0, 0, vis.length - 1), fi1 = clamp(fb - start - w0, fi0, vis.length - 1);
    const hd = header(S, `Detail B \u00b7 ${p.lang || 'listing'} \u00b7 L${fa}\u2013${fb}`, String(p.path || ''), bx.x, bx.y + 4, { path: true, w: L ? bx.w : 1180 });
    const fs = L ? 22 : 24, rowH = L ? 42 : 46;
    const lw = L ? bx.w : 1206;
    const rows = vis.map((s, i) => ({ g: String(start + w0 + i), text: s, html: codeHtml(s, p.lang, p.path), cls: '' }));
    const ls = listing(S, rows, { x: bx.x, y: bx.y + hd.h + 34, w: lw, fs, rowH, gut: L ? 62 : 70 });
    const P = S.P;
    P.add(stroke(S.svg, rectD(ls.x, ls.y, ls.w, ls.h), 'thin'));
    P.add(line(S.svg, [[ls.x + ls.gut - 8, ls.y], [ls.x + ls.gut - 8, ls.y + ls.h]], 'hid'));
    P.plan(0.15, { speed: 5200 });
    ls.rowEls.forEach((r, i) => P.letter(r.e, ls.rowBox(i)));
    const tRows = P.plan(0.45, { speed: 3400, gap: 0.01, maxDur: clamp(dur * 0.35, 0.8, 1.8) });
    // focus bracket + notes
    const ya = ls.rowTop(fi0) + 4, yb = ls.rowTop(fi1) + rowH - 4;
    vDim(S, ls.x - 30, ya, yb, `L${fa}\u2013${fb}`);
    const notes = [];
    const nx = L ? bx.x : 1410, nw = L ? bx.w : 400;
    const facts = [['Focus', `Lines <span class="m">${fa}\u2013${fb}</span>`]];
    if (p.total_lines) facts.push(['File', `<span class="m">${Number(p.total_lines)}</span> lines${p.new_file ? ', new file' : ''}`]);
    else if (p.new_file) facts.push(['File', 'New file']);
    if (p.lang) facts.push(['Language', esc(p.lang)]);
    let ny = L ? ls.y + ls.h + 60 : ls.y + 20;
    facts.forEach(([tag, html], i) => {
      const e = note(S, tag, html, nx, ny, nw);
      if (i === 0 && !L) leaderTo(S, [ls.x + ls.gut + Math.min(ls.maxChars, Math.max(...vis.slice(fi0, fi1 + 1).map((s) => s.length))) * ls.cw + 14, (ya + yb) / 2], nx, ny + 30);
      P.letter(e, { x: nx, y: ny, w: nw * 0.7, h: 60 });
      notes.push(e);
      ny += L ? 96 : 120;
    });
    const tFocus = P.plan(tRows + 0.1, { speed: 3000 });
    S.titleBlock({ title: base(p.path) || 'LISTING', rev: p.rev || 'A' }, tFocus);
    // camera: calm; a detail push onto the focus rows after the notes land
    const fy = (ya + yb) / 2;
    const zt = clamp((bx.h * 0.62) / (yb - ya + 120), 1.12, L ? 1.2 : 1.35);
    const cxz = Math.max(ls.x - 70 + S.W / (2 * zt), S.W / 2 - 200), cyz = lerp(S.H / 2, fy, 0.8);
    S.camera([[0, [S.W / 2, S.H / 2, 1]], [tFocus + 0.1, [S.W / 2, S.H / 2, 1.01]], [tFocus + 0.9, [cxz, cyz, zt]], [dur + 1, [cxz + 4, cyz + 4, zt * 1.02]]]);
    return {
      cues: [{ t: 0.15, sfx: 'type', gain_db: -12 }, { t: tRows, sfx: 'click', gain_db: -12 }, { t: tFocus + 0.1, sfx: 'move', gain_db: -14 }],
      render(t) {
        const dimOn = t >= tRows + 0.05;
        ls.rowEls.forEach((r, i) => css(r.e, { opacity: dimOn && (i < fi0 || i > fi1) ? '0.55' : '1' }));
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- DIFF
bpScene('kit:blueprint/DIFF', {
  describe: 'The diff as a revision: listing letters in, deleted rows are struck in redline, a revision cloud plots around the change (scallop by scallop), the REV B delta and title-block REV stamp in, WAS / NOW notes land on dog-leg leaders.',
  params: {
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    hunks: { type: 'array', default: [], doc: '[{header, lines:[[op, text]]}] <= 24 rows' },
    adds: { type: 'int', default: 0, doc: 'lines added' }, dels: { type: 'int', default: 0, doc: 'lines removed' },
  },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box;
    const rows0 = [];
    for (const hk of p.hunks || []) {
      rows0.push({ op: '@', text: String(hk.header || '@@') });
      for (const [op, text] of hk.lines || []) rows0.push({ op: op === '+' || op === '-' ? op : ' ', text: String(text).replace(/\t/g, '    ').replace(/\s+$/, '') });
    }
    const maxRows = L ? 16 : 12;
    const ch = rows0.map((r, i) => (r.op === '+' || r.op === '-' ? i : -1)).filter((i) => i >= 0);
    let w0 = 0;
    if (rows0.length > maxRows && ch.length) w0 = clamp(Math.round((ch[0] + ch[ch.length - 1]) / 2 - maxRows / 2), 0, rows0.length - maxRows);
    const vis = rows0.slice(w0, w0 + maxRows);
    const adds = Number(p.adds) || rows0.filter((r) => r.op === '+').length;
    const dels = Number(p.dels) || rows0.filter((r) => r.op === '-').length;
    const hd = header(S, `Detail B \u00b7 diff \u00b7 +${adds} \u2212${dels}`, String(p.path || ''), bx.x, bx.y + 4, { path: true, w: L ? bx.w : 1180 });
    const fs = L ? 22 : 24, rowH = L ? 44 : 46;
    const lw = L ? bx.w : 1206;
    const rows = vis.map((r) => ({ g: r.op === '-' ? '\u2212' : r.op === '+' ? '+' : '', text: r.text, cls: r.op === '+' ? 'add' : r.op === '-' ? 'del' : r.op === '@' ? 'hunk' : '',
      html: r.op === '@' ? null : codeHtml(r.text, p.lang, p.path) }));
    const ls = listing(S, rows, { x: bx.x, y: bx.y + hd.h + 34, w: lw, fs, rowH, gut: 66 });
    const P = S.P;
    P.add(stroke(S.svg, rectD(ls.x, ls.y, ls.w, ls.h), 'thin'));
    P.add(line(S.svg, [[ls.x + ls.gut - 8, ls.y], [ls.x + ls.gut - 8, ls.y + ls.h]], 'hid'));
    P.plan(0.12, { speed: 5200 });
    ls.rowEls.forEach((r, i) => P.letter(r.e, ls.rowBox(i)));
    const tRows = P.plan(0.4, { speed: 3600, gap: 0.01, maxDur: clamp(dur * 0.3, 0.7, 1.5) });
    // strikes through deleted rows (redline)
    vis.forEach((r, i) => { if (r.op === '-') P.add(line(S.svg, [[ls.textX, ls.rowY(i) + 1], [ls.textX + ls.rowBox(i).w, ls.rowY(i) + 1]], 'red')); });
    const tStrike = P.plan(tRows + 0.05, { speed: 2600 });
    // revision cloud on the changed rows (row boundaries) + delta
    const vch = vis.map((r, i) => (r.op === '+' || r.op === '-' ? i : -1)).filter((i) => i >= 0);
    let tCloud = tStrike;
    let cy0 = 0, cy1 = 0;
    if (vch.length) {
      cy0 = ls.rowTop(vch[0]) - 2; cy1 = ls.rowTop(vch[vch.length - 1]) + rowH + 2;
      const cx1 = ls.x + ls.w - 12;
      P.add(stroke(S.svg, cloudD(ls.x + 16, cy0, cx1, cy1, L ? 24 : 26), 'cloud'));
      tCloud = P.plan(tStrike + 0.05, { speed: 2400, maxDur: 0.8 });
      const dl = delta(S.svg, cx1, cy0 - 4, 26, p.rev || 'B');
      P.pop(dl.tri); P.pop(dl.text);
      vDim(S, ls.x - 30, cy0, cy1, `+${adds} / \u2212${dels}`);
      P.plan(tCloud, { speed: 3000 });
    }
    // notes: WAS (first deleted line), NOW (first added line), CHANGE (+/- counts)
    const firstDel = vis.findIndex((r) => r.op === '-'), firstAdd = vis.findIndex((r) => r.op === '+');
    const nx = L ? bx.x : 1410, nw = L ? bx.w : 400;
    let ny = L ? ls.y + ls.h + 50 : 312;
    const facts = [];
    if (firstDel >= 0) facts.push(['Was', `<span class="m">${esc(fitS(vis[firstDel].text.trim(), L ? 46 : 30))}</span>`, firstDel]);
    if (firstAdd >= 0) facts.push(['Now', `<span class="m">${esc(fitS(vis[firstAdd].text.trim(), L ? 46 : 30))}</span>`, firstAdd]);
    facts.push(['Change', `<span class="m">+${adds}</span> lines, <span class="m">\u2212${dels}</span> lines`, -1]);
    facts.forEach(([tag, html, ri]) => {
      const e = note(S, tag, html, nx, ny, nw);
      if (!L && ri >= 0) leaderTo(S, [ls.textX + ls.rowBox(ri).w + 14, ls.rowY(ri)], nx, ny + 30);
      P.letter(e, { x: nx, y: ny, w: nw * 0.7, h: 60 });
      ny += L ? 92 : 132;
    });
    const tNotes = P.plan(tCloud + 0.1, { speed: 3200 });
    if (!L) S.revTable([['A', 'first issue'], [p.rev || 'B', fitS(`${base(p.path)} +${adds} \u2212${dels}`, 24)]], 1410, 108, 454, tCloud);
    S.titleBlock({ title: base(p.path) || 'DIFF', rev: p.rev || 'B' }, tCloud);
    const fy = vch.length ? (cy0 + cy1) / 2 : S.H / 2;
    S.camera([[0, [S.W / 2, S.H / 2, 1]], [tNotes, [S.W / 2, S.H / 2, 1.01]], [dur + 1, [S.W / 2 - 20, lerp(S.H / 2, fy, 0.25), 1.06]]]);
    return {
      cues: [{ t: 0.12, sfx: 'type', gain_db: -12 }, { t: tRows, sfx: 'click', gain_db: -12 }, { t: tCloud, sfx: 'hit', gain_db: -6 }],
      render() {},
    };
  },
});

// --------------------------------------------------------------------------------------------- TERMINAL
bpScene('kit:blueprint/TERMINAL', {
  describe: 'A run as a test-bench drawing: the command letters in, output prints like a plotter, a gauge drawing (dial, ticks, needle) swings to the pass fraction stated by the output and a PASS / FAIL stamp thumps on.',
  params: {
    cmd: { type: 'string', default: '', doc: 'command line' }, output: { type: 'array', default: [], doc: '<= 12 verbatim output lines' },
    truncated_top: { type: 'bool', default: false, doc: 'output was cut at the top' }, exit_code: { type: 'int', default: null, doc: 'exit code' },
    elapsed_s: { type: 'number', default: null, doc: 'runtime seconds' }, ok: { type: 'bool', default: true, doc: 'run succeeded' },
    tests_passed: { type: 'bool', default: false, doc: 'PASS stamp' },
  },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box;
    const ok = p.ok !== false && (p.exit_code == null || Number(p.exit_code) === 0);
    const n = runNumbers(p);
    const hd = header(S, `Test bench \u00b7 ${n.passed != null ? 'pytest-style run' : 'run'}`, '', bx.x, bx.y + 4);
    const out = (p.output || []).map(String).slice(-(L ? 9 : 10));
    const rows = [{ g: '$', text: String(p.cmd || ''), cls: 'cmd' }, ...out.map((s) => ({ g: '', text: s, cls: '' }))];
    const fs = L ? 24 : 28, rowH = L ? 46 : 52;
    const lw = L ? bx.w : 940;
    const lh0 = rows.length * rowH + 44;
    const ly = L ? bx.y + hd.h + 20 : Math.max(bx.y + hd.h + 20, 470 - lh0 / 2);
    const ls = listing(S, rows, { x: bx.x, y: ly, w: lw, fs, rowH, gut: 50 });
    const P = S.P;
    P.add(stroke(S.svg, rectD(ls.x, ls.y, ls.w, ls.h), 'thin'));
    P.plan(0.12, { speed: 5200 });
    ls.rowEls.forEach((r, i) => P.letter(r.e, ls.rowBox(i), { factor: i === 0 ? 1.4 : 0.5 }));
    const tOut = P.plan(0.35, { speed: 2600, gap: 0.04, maxDur: clamp(dur * 0.32, 0.8, 1.6) });
    // gauge
    const R = L ? 210 : 230;
    const gx = L ? S.W / 2 : 1500, gy = L ? ls.y + ls.h + 120 + R : 470;
    const a0 = Math.PI * (5 / 6), a1 = Math.PI * (13 / 6); // 150deg .. 390deg (240deg sweep, opening down)
    const ang = (u) => a0 + (a1 - a0) * u;
    P.add(stroke(S.svg, circleD(gx, gy, R, a0, a1, 96), 'obj'));
    P.add(stroke(S.svg, circleD(gx, gy, R - 26, a0, a1, 96), 'thin'));
    for (let i = 0; i <= 20; i++) {
      const a = ang(i / 20), big = i % 5 === 0, r1 = R - (big ? 44 : 34);
      P.add(line(S.svg, [[gx + Math.cos(a) * (R - 26), gy + Math.sin(a) * (R - 26)], [gx + Math.cos(a) * r1, gy + Math.sin(a) * r1]], big ? 'thin' : 'cons'));
    }
    // pass band (last 10 %) as a hatched arc
    P.add(stroke(S.svg, circleD(gx, gy, R - 13, ang(0.9), a1, 24), 'ctr', { style: 'stroke-width:14px;stroke:rgba(121,211,255,.35)' }));
    const tDial = P.plan(Math.min(0.5, tOut * 0.5), { speed: 4200, gap: 0.004, maxDur: 0.9, track: 'main' });
    const tests = n.passed != null || n.failed != null;
    const frac = tests ? (n.passed || 0) / Math.max(1, (n.passed || 0) + (n.failed || 0)) : ok ? 1 : 0;
    const scale = tests ? ['0', '50', '100 %'] : ['FAIL', '', 'OK'];
    [[0, scale[0]], [0.5, scale[1]], [1, scale[2]]].forEach(([u, s]) => {
      if (!s) return;
      const a = ang(u), r = R - 78;
      const e = S.text('bp-lbl', s, gx + Math.cos(a) * r - 60, gy + Math.sin(a) * r - 12, { w: 120, align: 'center' });
      P.letter(e, { x: gx + Math.cos(a) * r - 20, y: gy + Math.sin(a) * r - 12, w: 40, h: 24 });
    });
    const capT = tests ? 'TESTS PASSING' : 'EXIT STATUS';
    const cap = S.text('bp-cap', capT, gx - 200, gy + R * 0.42, { w: 400, align: 'center' });
    P.letter(cap, { x: gx - 90, y: gy + R * 0.42, w: 180, h: 24 });
    P.plan(tDial, { speed: 3000 });
    // needle (rotating group), hub
    const needle = el(S.svg, 'g', {});
    line(needle, [[0, 0], [R - 40, 0]], 'obj');
    line(needle, [[0, 0], [-34, 0]], 'thin');
    const hub = el(S.svg, 'circle', { cx: gx, cy: gy, r: 12, class: 'balloon' });
    const syncPass = Number(p._sync && p._sync.pass);
    const tSwing = Number.isFinite(syncPass) && syncPass > tOut ? syncPass - 0.45 : Math.max(tOut + 0.1, tDial + 0.1);
    const tLand = tSwing + 0.55;
    // readouts from the output (verbatim numbers only)
    const reads = [];
    if (n.passed != null) reads.push(`${n.passed} passed`);
    if (n.failed != null) reads.push(`${n.failed} failed`);
    if (n.secs != null) reads.push(`${n.secs} s`);
    if (!reads.length) reads.push(p.exit_code == null ? (ok ? 'ok' : 'error') : `exit ${p.exit_code}`);
    const rd = S.text('bp-t', '', gx - 260, gy + R * 0.62, { w: 520, align: 'center', html: reads.map((r) => `<span style="font:500 30px var(--bp-m)">${esc(r)}</span>`).join('<span style="color:var(--line-3)"> \u00b7 </span>') });
    const st = stamp(S, p.tests_passed || (ok && !tests) ? 'PASS' : ok ? 'OK' : 'FAIL', gx + R * 0.35, gy - R * 1.12, { at: tLand + 0.05, red: !ok, rot: -8 });
    S.titleBlock({ title: fitS(String(p.cmd || 'RUN').split(/\s+/)[0], 18) + ' \u00b7 RUN', rev: p.rev || 'A' }, tLand + 0.05);
    S.camera([[0, [S.W / 2, S.H / 2, 1]], [dur + 1, [S.W / 2 + (L ? 0 : 16), S.H / 2 + 6, 1.03]]]);
    return {
      cues: [{ t: 0.15, sfx: 'type', gain_db: -12 }, { t: tSwing, sfx: 'move', gain_db: -12 }, { t: tLand + 0.05, sfx: ok ? 'pass' : 'fail', gain_db: -4 }],
      render(t) {
        const u = seg(t, tSwing, tLand, ease.outBack);
        const a = ang(clamp(frac * u, -0.02, 1.03));
        css(needle, { transform: `translate(${gx}px,${gy}px) rotate(${(a * 180 / Math.PI).toFixed(2)}deg)`, visibility: t >= tDial - 0.2 ? 'visible' : 'hidden' });
        css(hub, { visibility: t >= tDial - 0.2 ? 'visible' : 'hidden' });
        css(rd, { visibility: t >= tLand ? 'visible' : 'hidden' });
        st.update(t);
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- MONTAGE
const ICON = {
  terminal: (g, cx, cy) => [line(g, [[cx - 42, cy - 30], [cx + 42, cy - 30], [cx + 42, cy + 30], [cx - 42, cy + 30], [cx - 42, cy - 30]], 'obj'),
    line(g, [[cx - 26, cy - 10], [cx - 12, cy], [cx - 26, cy + 10]], 'thin'), line(g, [[cx - 4, cy + 12], [cx + 18, cy + 12]], 'thin')],
  page: (g, cx, cy) => [line(g, [[cx - 30, cy - 40], [cx + 14, cy - 40], [cx + 30, cy - 24], [cx + 30, cy + 40], [cx - 30, cy + 40], [cx - 30, cy - 40]], 'obj'),
    line(g, [[cx + 14, cy - 40], [cx + 14, cy - 24], [cx + 30, cy - 24]], 'thin'),
    ...[-8, 6, 20].map((dy) => line(g, [[cx - 18, cy + dy], [cx + 18, cy + dy]], 'cons'))],
  search: (g, cx, cy) => [stroke(g, circleD(cx - 8, cy - 8, 26), 'obj'), line(g, [[cx + 11, cy + 11], [cx + 36, cy + 36]], 'obj')],
  globe: (g, cx, cy) => [stroke(g, circleD(cx, cy, 36), 'obj'), line(g, [[cx - 36, cy], [cx + 36, cy]], 'thin'),
    stroke(g, `M${cx} ${cy - 36} C ${cx - 26} ${cy - 18}, ${cx - 26} ${cy + 18}, ${cx} ${cy + 36} C ${cx + 26} ${cy + 18}, ${cx + 26} ${cy - 18}, ${cx} ${cy - 36}`, 'thin')],
  camera: (g, cx, cy) => [line(g, [[cx - 40, cy - 22], [cx - 16, cy - 22], [cx - 8, cy - 32], [cx + 8, cy - 32], [cx + 16, cy - 22], [cx + 40, cy - 22], [cx + 40, cy + 28], [cx - 40, cy + 28], [cx - 40, cy - 22]], 'obj'),
    stroke(g, circleD(cx, cy + 2, 16), 'thin')],
  list: (g, cx, cy) => [-22, 0, 22].flatMap((dy) => [line(g, [[cx - 34, cy + dy], [cx - 26, cy + dy + 7], [cx - 14, cy + dy - 8]], 'thin'), line(g, [[cx - 4, cy + dy], [cx + 36, cy + dy]], 'obj')]),
  fork: (g, cx, cy) => [stroke(g, circleD(cx - 22, cy - 26, 7), 'thin'), stroke(g, circleD(cx + 22, cy - 26, 7), 'thin'), stroke(g, circleD(cx, cy + 30, 7), 'thin'),
    stroke(g, `M${cx - 22} ${cy - 19} C ${cx - 22} ${cy + 4}, ${cx} ${cy + 2}, ${cx} ${cy + 23} M${cx + 22} ${cy - 19} C ${cx + 22} ${cy + 4}, ${cx} ${cy + 2}, ${cx} ${cy + 23}`, 'obj')],
  gear: (g, cx, cy) => [stroke(g, circleD(cx, cy, 30), 'obj'), stroke(g, circleD(cx, cy, 10), 'thin'),
    ...Array.from({ length: 8 }, (_, i) => { const a = i * Math.PI / 4; return line(g, [[cx + Math.cos(a) * 30, cy + Math.sin(a) * 30], [cx + Math.cos(a) * 40, cy + Math.sin(a) * 40]], 'obj'); })],
};
const kindIcon = (k) => ({ terminal: 'terminal', file_write: 'page', file_patch: 'page', file_read: 'page', artifact: 'page', web_search: 'search',
  web_extract: 'globe', browser_nav: 'globe', screenshot: 'camera', product_capture: 'camera', image_generated: 'camera', todo: 'list', delegate: 'fork' })[k] || 'gear';

bpScene('kit:blueprint/MONTAGE', {
  describe: "The agent's tool calls as an assembly drawing: up to six detail views (one line-art part per tool kind, ballooned) plot on half-beats, and a parts list (item, tool, argument, session time) letters in row by row.",
  params: { items: { type: 'array', default: [], doc: '[{id, t, kind, tool, arg, clipped}] 3-16 tool calls' } },
  build(ctx, p, F, S) {
    const dur = ctx.dur, L = S.L, bx = S.box;
    const items = (p.items || []).slice(0, 16);
    const n = items.length;
    const hd = header(S, `Assembly \u00b7 ${n} tool calls`, 'Parts list', bx.x, bx.y + 4, { font: 'draw', size: 40 });
    const P = S.P;
    const nDet = Math.min(6, n);
    const cols = 3, R = L ? 104 : 96;
    const gx0 = L ? bx.x + 140 : bx.x + 130, gy0 = L ? bx.y + hd.h + 150 : bx.y + hd.h + 150;
    const stepX = L ? 280 : 270, stepY = L ? 300 : 290;
    const gap = clamp((dur * 0.62 - 0.3) / Math.max(1, n), 0.1, 0.32);
    const detail = [];
    for (let i = 0; i < nDet; i++) {
      const cx = gx0 + (i % cols) * stepX, cy = gy0 + Math.floor(i / cols) * stepY;
      const ring = stroke(S.svg, circleD(cx, cy, R), 'thin');
      const parts = ICON[kindIcon(items[i].kind)](S.svg, cx, cy - 8);
      const b = balloon(S.svg, cx + R * 0.72, cy - R * 0.72, i + 1, 19);
      const lbl = S.text('bp-lbl', fitS(String(items[i].tool || items[i].kind || ''), 16), cx - 130, cy + R + 14, { w: 260, align: 'center' });
      detail.push({ ring, parts, b, lbl, cx, cy });
    }
    // parts list table
    const tx = L ? bx.x : 1010, ty = L ? gy0 + 2 * stepY - 40 : bx.y + hd.h + 40, tw = L ? bx.w : 786;
    const rowH = L ? 46 : 48, maxRows = L ? 8 : 12;
    const shown = items.slice(0, maxRows);
    const colI = 64, colT = L ? 210 : 200, colS = 96;
    const rowsY = shown.map((_, i) => ty + rowH * (i + 1));
    const tableH = rowH * (shown.length + 1 + (n > maxRows ? 1 : 0));
    P.add(stroke(S.svg, rectD(tx, ty, tw, tableH), 'obj'));
    P.add(line(S.svg, [[tx, ty + rowH], [tx + tw, ty + rowH]], 'thin'));
    [colI, colI + colT, tw - colS].forEach((cx) => P.add(line(S.svg, [[tx + cx, ty], [tx + cx, ty + tableH]], 'thin')));
    const tTable = P.plan(0.1, { speed: 6000, gap: 0.01, maxDur: 0.5 });
    const head = (s, x, w, al = 'left') => { const e = S.text('bp-cap', s, x, ty + 14, { w, align: al }); e.style.fontSize = '17px'; P.letter(e, { x, y: ty + 10, w: Math.min(w, 120), h: 24 }, { at: [tTable, tTable + 0.15] }); };
    head('Item', tx + 8, colI - 16, 'center'); head('Tool', tx + colI + 14, colT - 20); head('Argument', tx + colI + colT + 14, tw - colI - colT - colS - 20); head('Time', tx + tw - colS + 10, colS - 20);
    const at = items.map((_, i) => 0.35 + i * gap);
    const cells = shown.map((it, i) => {
      const y = rowsY[i] + 11;
      const a = at[i];
      const mk = (cls, s, x, w, al) => { const e = S.text(cls, s, x, y, { w, align: al, nowrap: true }); e.style.overflow = 'hidden'; e.style.fontSize = L ? '20px' : '21px'; P.letter(e, { x, y, w: Math.min(w, 200), h: 26 }, { at: [a, a + 0.12] }); return e; };
      mk('bp-lbl', String(i + 1), tx, colI, 'center');
      mk('bp-lbl', fitS(String(it.tool || it.kind || ''), L ? 14 : 13), tx + colI + 14, colT - 20);
      const argW = tw - colI - colT - colS - 28;
      const e = mk('bp-t', fitS(String(it.arg || '').replace(/\s+/g, ' '), Math.floor(argW / 12.6)), tx + colI + colT + 14, argW);
      e.style.fontFamily = 'var(--bp-m)'; e.style.color = 'var(--line)';
      mk('bp-lbl', clock(it.t), tx + tw - colS + 10, colS - 20);
      if (i < shown.length - 1) P.add(line(S.svg, [[tx, rowsY[i] + rowH], [tx + tw, rowsY[i] + rowH]], 'cons'), { at: [a, a + 0.1] });
      return e;
    });
    if (n > maxRows) { const e = S.text('bp-lbl', `+ ${n - maxRows} more`, tx + colI + 14, ty + rowH * (shown.length + 1) + 11); P.letter(e, { x: tx + colI, y: ty + rowH * (shown.length + 1), w: 120, h: 26 }, { at: [at[maxRows] || at[n - 1], (at[maxRows] || at[n - 1]) + 0.12] }); }
    // detail views plot on the same beats
    detail.forEach((dt, i) => {
      const a = at[i];
      P.add(dt.ring, { at: [a, a + gap * 0.9] });
      dt.parts.forEach((pp, j) => P.add(pp, { at: [a + 0.05 + j * 0.03, a + gap * 0.9] }));
      P.add(dt.b.ring, { at: [a + gap * 0.5, a + gap * 0.9] });
      P.pop(dt.b.disc); P.pop(dt.b.num);
      P.letter(dt.lbl, { x: dt.cx - 60, y: dt.cy + R + 14, w: 120, h: 24 }, { at: [a + 0.05, a + 0.2] });
    });
    S.titleBlock({ title: 'ASSEMBLY \u00b7 TOOL CALLS', rev: p.rev || 'A' }, (at[n - 1] || 1) + 0.2);
    S.camera([[0, [S.W / 2, S.H / 2, 1]], [dur + 1, [S.W / 2 + 10, S.H / 2 + (L ? 30 : 8), 1.03]]]);
    return {
      cues: at.map((t) => ({ t, sfx: 'type', gain_db: -12 })),
      render() { void cells; },
    };
  },
});

export { pd };
