// Hype kit "comic" — code pages: CODE, DIFF, TERMINAL (the frame-B page), MONTAGE (a strip being inked).

import { comicScene, snapIn } from './lib/page.js';
import { h, css, kindIcon, clock } from '../base/dom.js';
import { clamp } from '../base/motion.js';
import { codeBlock, diffBlock } from '../base/code.js';
import { termBlock } from '../base/term.js';
import { C, agentSvg, figure, burst, checkSvg } from './lib/art.js';
import { caption, sfx, slam, pop } from './lib/letter.js';

/** Rect of a block-local rect inside a panel, in page coords. */
const inPage = (pn, bx, by, r) => ({ x: pn.x + bx + r.x, y: pn.y + by + r.y, w: r.w, h: r.h });

// ------------------------------------------------------------------------------------- CODE
comicScene('kit:comic/CODE', {
  describe: 'Two-panel page: the agent hammers the keyboard (TAK TAK TAK!) while the real file streams into an inked editor panel; the camera glides to the editor and pushes onto the focus lines, which get a yellow marker.',
  params: {
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    lines: { type: 'array', default: [], doc: '<= 18 verbatim lines' }, start: { type: 'int', default: 1, doc: 'first line number' },
    focus: { type: 'array', default: [1, 1], doc: '[a, b] focus line numbers' },
  },
  build(ctx, p, F, P) {
    const L = !F.portrait, dur = ctx.dur;
    const R1 = L ? { x: 40, y: 40, w: 560, h: 1000 } : { x: 40, y: 200, w: 1000, h: 380 };
    const R2 = L ? { x: 626, y: 40, w: 1254, h: 1000 } : { x: 40, y: 606, w: 1000, h: 1274 };
    const p1 = P.panel(R1, { bg: 'action', rays: L ? [0.62, 0.62] : [0.7, 0.62], seed: 19 });
    const cap = caption('Hermes writes the code.', { x: 26, y: 26, white: true });
    p1.el.appendChild(cap.el);
    const ag = L ? figure(agentSvg({ pose: 'type', rim: 'cyan' }), -30, 560, 560) : figure(agentSvg({ pose: 'type', rim: 'cyan' }), -20, 70, 340);
    p1.el.appendChild(ag);
    const tak = sfx('TAK TAK TAK!', L ? { x: 40, y: 290, size: 92, color: C.white, rot: -8, stroke: 10 } : { x: 420, y: 150, size: 80, color: C.white, rot: -6, stroke: 9 });
    p1.el.appendChild(tak.el);
    const p2 = P.panel(R2, { bg: 'cyan' });
    const width = L ? R2.w - 90 : R2.w - 60;
    const reveal = [0.35, clamp(dur * 0.5, 1.2, 3.2)];
    const b = codeBlock(p, { width, fontSize: L ? 27 : 25, reveal, focusAt: reveal[1] + 0.1 });
    const bx = (R2.w - width) / 2, by = L ? Math.max(40, (R2.h - b.h) / 2) : 40;
    b.el.style.left = `${bx}px`; b.el.style.top = `${by}px`;
    p2.el.appendChild(b.el);
    const fr = inPage(p2, bx, by, b.focusRect());
    fr.x -= 10; fr.w = Math.min(width * 0.8, fr.w) + 20;
    const tGlide = L ? 0.9 : 0.8, tp = reveal[1] + 0.15;
    const r2v = { x: R2.x, y: R2.y, w: R2.w, h: Math.min(R2.h, b.h + 80) };
    const cam = P.track(L ? [[0, { x: R1.x, y: R1.y + 180, w: R1.w + 300, h: 700 }], [tGlide, { x: R1.x, y: R1.y + 180, w: R1.w + 300, h: 700 }],
      [tGlide + 0.55, R2], [tp, R2], [tp + 0.7, fr], [dur + 1, { ...fr, y: fr.y + 6 }]]
      : [[0, R1], [tGlide, R1], [tGlide + 0.55, r2v], [tp, r2v], [tp + 0.7, fr], [dur + 1, { ...fr, y: fr.y + 6 }]], 30, L ? 1.75 : 1.35);
    return {
      cues: [...b.cues, { t: 0.4, sfx: 'hit', gain_db: -12 }, { t: tGlide, sfx: 'move', gain_db: -14 }, { t: tp + 0.05, sfx: 'move', gain_db: -14 }],
      render(t) {
        P.spinRays(t);
        cap.update(t, 0.05);
        tak.update(t, 0.4);
        b.update(t);
        snapIn(b.el, t, 0.1, { rise: 40, from: 0.95 });
        P.camera(t, cam(t));
      },
    };
  },
});

// ------------------------------------------------------------------------------------- DIFF
comicScene('kit:comic/DIFF', {
  describe: 'Diff page: rows ink in, deletions get a red-pen strike-through, additions a green fill with a SHNK! on the first add; a +N/-N burst slams; the camera pushes onto the change.',
  params: {
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    hunks: { type: 'array', default: [], doc: '[{header, lines:[[op, text]]}] <= 24 rows' },
    adds: { type: 'int', default: 0, doc: 'lines added' }, dels: { type: 'int', default: 0, doc: 'lines removed' },
  },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, dur = ctx.dur;
    const R = L ? { x: 40, y: 40, w: W - 80, h: H - 80 } : { x: 40, y: 200, w: W - 80, h: H - 240 };
    const pn = P.panel(R, { bg: 'magenta' });
    const width = L ? 1560 : 940;
    const nRows = (p.hunks || []).reduce((a, hk) => a + 1 + (hk.lines || []).length, 0);
    const reveal = [0.3, clamp(0.3 + nRows * 0.09, 0.9, dur * 0.45)];
    const b = diffBlock(p, { width, fontSize: L ? 28 : 27, reveal });
    const bx = (R.w - width) / 2, by = L ? Math.max(110, (R.h - b.h) / 2 + 30) : Math.max(150, Math.round((R.h - b.h - 520) / 2) + 60);
    b.el.style.left = `${bx}px`; b.el.style.top = `${by}px`;
    pn.el.appendChild(b.el);
    const cap = caption('The fix, in red ink and green.', { x: 30, y: L ? 28 : 40 });
    pn.el.appendChild(cap.el);
    const adds = Number(p.adds) || 0, dels = Number(p.dels) || 0;
    const tally = burst(P.doc, { w: L ? 300 : 260, h: L ? 200 : 180, spikes: 14, fill: 'yellow', seed: 71, shadow: 8, text: `+${adds} \u2212${dels}`, size: L ? 64 : 56 });
    tally.el.style.left = `${R.w - (L ? 330 : 280)}px`; tally.el.style.top = '10px';
    pn.el.appendChild(tally.el);
    // SHNK! on the first added row
    const rows = b.el.querySelectorAll('.srb-row');
    let firstAdd = -1;
    rows.forEach((r, i) => { if (firstAdd < 0 && r.classList.contains('add')) firstAdd = i; });
    const step = rows.length > 1 ? (reveal[1] - reveal[0]) / rows.length : 0;
    const tAdd = reveal[0] + Math.max(0, firstAdd) * step + 0.15;
    const shnk = sfx('SHNK!', L ? { x: bx + width - 420, y: by - 120, size: 96, color: C.green, rot: -8 } : { x: R.w - 420, y: by + b.h + 120, size: 110, color: C.green, rot: -8 });
    let pointer = null;
    if (!L && R.h - (by + b.h) > 480) {
      pointer = figure(agentSvg({ pose: 'point', rim: 'white', cape: 'blue' }), 30, R.h - 500, 470);
      pn.el.appendChild(pointer);
    }
    pn.el.appendChild(shnk.el);
    const cr = inPage(pn, bx, by, b.changedRect(L ? 9 : 12));
    cr.w = Math.min(cr.w, width * 0.85);
    const tp = reveal[1] + 0.25;
    const whole = R;
    const cam = P.track([[0, whole], [tp, whole], [tp + 0.7, cr], [dur + 1, { ...cr, y: cr.y + 6 }]], 40, L ? 1.6 : 1.06);
    return {
      cues: [...b.cues.filter((c) => c.t > tAdd + 0.2), ...(firstAdd >= 0 ? [{ t: tAdd, sfx: 'hit', gain_db: -8 }] : []),
        { t: reveal[0] + 0.1, sfx: 'appear', gain_db: -12 }, { t: tp + 0.05, sfx: 'move', gain_db: -14 }],
      render(t) {
        cap.update(t, 0.05);
        b.update(t);
        snapIn(b.el, t, 0.05, { rise: 30, from: 0.96 });
        const s = slam(t, reveal[0] + 0.1, { from: 1.7 });
        css(tally.el, { opacity: s.op.toFixed(3), transform: `rotate(7deg) scale(${s.s.toFixed(4)})` });
        if (firstAdd >= 0) shnk.update(t, tAdd);
        P.camera(t, cam(t));
      },
    };
  },
});

/** The headline number of a test/command run from its output ("14 PASSED!" / "0.4 S!"). */
function runFact(p) {
  const out = (p.output || []).map(String);
  for (let i = out.length - 1; i >= 0; i--) {
    const m = /(\d+)\s+(passed|tests? passed|ok)\b/i.exec(out[i]);
    if (m) return `${m[1]} ${m[2].toUpperCase()}!`;
  }
  if (p.elapsed_s != null) return `${Number(p.elapsed_s) < 10 ? Number(p.elapsed_s).toFixed(1) : Math.round(Number(p.elapsed_s))} S!`;
  return '';
}

const CROSS_SVG = `<svg viewBox="0 0 100 100" width="100%" height="100%" style="overflow:visible"><path d="M14 14 L86 86 M86 14 L14 86" stroke="${C.ink}" stroke-width="34" stroke-linecap="square"/><path d="M14 14 L86 86 M86 14 L14 86" stroke="${C.red}" stroke-width="16" stroke-linecap="square"/></svg>`;

// ------------------------------------------------------------------------------------- TERMINAL
comicScene('kit:comic/TERMINAL', {
  describe: 'The frame-B page: the agent at the keyboard, the real command types and its output streams in an inked terminal, then the splash panel slams PASS! (tests) / DONE! (exit 0) / FAIL! with the key number in a burst; Z-path camera glide, page shake on the hit.',
  params: {
    cmd: { type: 'string', default: '', doc: 'command line' }, output: { type: 'array', default: [], doc: '<= 12 output lines' },
    truncated_top: { type: 'bool', default: false, doc: 'output was cut at the top' }, exit_code: { type: 'int', default: null, doc: 'exit code' },
    elapsed_s: { type: 'number', default: null, doc: 'runtime seconds' }, ok: { type: 'bool', default: true, doc: 'run succeeded' },
    tests_passed: { type: 'bool', default: false, doc: 'PASS! splash + chime' },
  },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, dur = ctx.dur;
    const R1 = L ? { x: 40, y: 40, w: 760, h: 560 } : { x: 40, y: 200, w: 1000, h: 330 };
    const R2 = L ? { x: 826, y: 40, w: 1054, h: 560 } : { x: 40, y: 556, w: 1000, h: 600 };
    const R3 = L ? { x: 40, y: 626, w: 1840, h: 414 } : { x: 40, y: 1182, w: 1000, h: 698 };
    const ok = p.ok !== false && (p.exit_code == null || Number(p.exit_code) === 0);
    const kind = p.tests_passed && ok ? 'pass' : ok ? 'ok' : 'fail';
    const p1 = P.panel(R1, { bg: 'cyan' });
    const cap1 = caption('Hermes runs it.', { x: 26, y: 26 });
    p1.el.appendChild(cap1.el);
    p1.el.appendChild(L ? figure(agentSvg({ pose: 'type', rim: 'yellow' }), -10, 150, 470) : figure(agentSvg({ pose: 'type', rim: 'yellow' }), 0, 40, 330));
    const tak = sfx('TAK TAK!', L ? { x: 330, y: 400, size: 80, color: C.white, rot: -8, stroke: 9 } : { x: 470, y: 180, size: 72, color: C.white, rot: -6, stroke: 9 });
    p1.el.appendChild(tak.el);
    const p2 = P.panel(R2, { bg: 'action', rays: [0.5, 0.5], seed: 7 });
    const lines = (p.output || []).map(String);
    const longest = Math.max(String(p.cmd || '').length + 2, ...lines.map((s) => s.length), 20);
    const tw = R2.w - (L ? 80 : 60);
    const fs = Math.round(clamp((tw - 60) / (longest * 0.6), 22, L ? 30 : 28));
    const cmdLen = String(p.cmd || '').length;
    const typeAt = [0.35, 0.35 + clamp(cmdLen * 0.03, 0.35, 1.0)];
    const streamAt = [typeAt[1] + 0.2, typeAt[1] + 0.2 + clamp(lines.length * 0.11, 0.2, 1.3)];
    const sync = Number(p._sync && p._sync.pass);
    const hitAt = Number.isFinite(sync) && sync >= streamAt[1] && sync < dur - 0.6 ? sync : Math.min(streamAt[1] + 0.35, Math.max(streamAt[1], dur - 1.3));
    const tb = termBlock(p, { width: tw, fontSize: fs, typeAt, streamAt, badgeAt: hitAt + 0.15, wrap: !L, maxRows: L ? Math.floor((R2.h - 190) / (fs * 1.6)) : 9 });
    const tx = (R2.w - tw) / 2, ty = Math.max(30, (R2.h - tb.h) / 2);
    tb.el.style.left = `${tx}px`; tb.el.style.top = `${ty}px`;
    p2.el.appendChild(tb.el);
    const p3 = P.panel(R3, { bg: kind === 'fail' ? 'grey' : kind === 'pass' ? 'splash' : 'blue', rays: L ? [0.42, 0.5] : [0.5, 0.4], seed: 3, spin: 5 });
    const word = kind === 'pass' ? 'PASS!' : kind === 'ok' ? 'DONE!' : 'FAIL!';
    const big = burst(P.doc, { w: L ? 860 : 820, h: L ? 420 : 460, spikes: 22, depth: 0.2, fill: 'white', seed: 12, shadow: 14 });
    big.el.style.left = `${L ? 260 : 90}px`; big.el.style.top = L ? '-10px' : '40px';
    p3.el.appendChild(big.el);
    const bigW = h('div', 'cx-sfx ext');
    bigW.style.cssText = `left:${L ? 380 : 170}px;top:${L ? 110 : 190}px;font-size:${L ? 190 : 170}px;color:${kind === 'fail' ? C.red : C.green};display:flex;align-items:center;gap:8px;`;
    const mark = h('div', '', { html: kind === 'fail' ? CROSS_SVG : checkSvg('green', 16) });
    mark.style.cssText = `width:${L ? 150 : 130}px;height:${L ? 150 : 130}px;margin-top:-20px;flex:none;`;
    bigW.append(mark, word);
    p3.el.appendChild(bigW);
    const fact = runFact(p);
    let small = null;
    if (fact) {
      small = burst(P.doc, { w: L ? 440 : 380, h: L ? 280 : 240, spikes: 13, depth: 0.25, fill: 'yellow', seed: 4, shadow: 10, text: fact, size: L ? 64 : 56 });
      small.el.style.left = `${L ? 1150 : 560}px`; small.el.style.top = L ? '40px' : '420px';
      p3.el.appendChild(small.el);
    }
    const passLine = lines.filter((s) => /\b\d+\s+passed\b/i.test(s)).slice(-1)[0] || '';
    const capText = kind === 'pass' && passLine ? passLine.trim() : `$ ${String(p.cmd || '').trim()}`;
    let cap3 = null;
    if (capText.length > 2 && capText.length <= 48) {
      cap3 = caption(capText, { x: 24, y: L ? R3.h - 80 : 24, mono: true, white: true });
      cap3.el.style.zIndex = '32';
      p3.el.appendChild(cap3.el);
    }
    if (kind !== 'fail') p3.el.appendChild(figure(agentSvg({ pose: 'hero', rim: 'white', cape: 'blue' }), R3.w - 330, L ? 30 : 330, L ? 280 : 300));
    const g1 = Math.min(typeAt[0] + 0.15, 0.6);
    const cam = P.track(L ? [[0, R1], [g1, R1], [g1 + 0.5, R2], [hitAt - 0.05, R2], [hitAt + 0.4, 'page'], [dur + 1, [W / 2, H / 2 + 4, 1.02]]]
      : [[0, R1], [g1, R1], [g1 + 0.5, R2], [hitAt - 0.05, R2], [hitAt + 0.4, { x: 40, y: 760, w: 1000, h: 1100 }], [dur + 1, { x: 40, y: 770, w: 1000, h: 1100 }]], 30, L ? 2.0 : 1.4);
    return {
      cues: [...tb.cues.filter((c) => c.sfx === 'type'), { t: g1, sfx: 'move', gain_db: -14 },
        { t: hitAt, sfx: kind === 'pass' ? 'pass' : kind === 'fail' ? 'fail' : 'hit', gain_db: kind === 'pass' ? -3 : -6 }],
      render(t) {
        P.spinRays(t);
        cap1.update(t, 0.0);
        tak.update(t, 0.42);
        tb.update(t);
        P.panelIn(p3, t, hitAt - 0.12, 'left');
        const s = slam(t, hitAt, { from: 1.8, dur: 0.15 });
        css(big.el, { opacity: s.op.toFixed(3), transform: `translate(${s.dx}px,${s.dy}px) scale(${s.s.toFixed(4)})` });
        const w = slam(t, hitAt + 0.06, { from: 1.9 });
        css(bigW, { opacity: w.op.toFixed(3), transform: `rotate(-4deg) scale(${w.s.toFixed(4)})` });
        if (small) { const q = slam(t, hitAt + 0.3, { from: 1.7 }); css(small.el, { opacity: q.op.toFixed(3), transform: `rotate(6deg) scale(${q.s.toFixed(4)})` }); }
        if (cap3) cap3.update(t, hitAt + 0.45);
        P.camera(t, cam(t), { shakes: [hitAt + 0.02], amp: 14 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- MONTAGE
const TONES = [['cyan', null], ['action', [0.7, 0.7]], ['magenta', null], ['splash', [0.3, 0.6]], ['paper', null], ['blue', [0.5, 0.9]]];

comicScene('kit:comic/MONTAGE', {
  describe: "Breadth of the agent's work as a strip being inked: one tiny panel per real tool call (icon, tool name in display lettering, the argument in mono, session clock) fills in on every half-beat while the camera tracks the row.",
  params: { items: { type: 'array', default: [], doc: '[{id, t, kind, tool, arg, clipped}] 3-16 tool calls' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, dur = ctx.dur;
    const items = (p.items || []).slice(0, 16);
    const n = Math.max(1, items.length);
    const cols = L ? (n <= 4 ? n : 4) : 2;
    const nr = Math.ceil(n / cols);
    const rows = Array.from({ length: nr }, (_, r) => [Array.from({ length: Math.min(cols, n - r * cols) }, () => 1), 1]);
    const rects = P.grid(rows, L ? { m: 40, g: 26 } : { m: 40, g: 26, top: 200, bottom: 40 });
    const step = clamp((dur - 1.1) / n, 0.22, 0.6);
    const t0 = 0.15;
    const cells = items.map((it, i) => {
      const [bg, rays] = TONES[i % TONES.length];
      const pn = P.panel(rects[i], { bg, rays: rays || [0.5, 0.5], seed: 30 + i });
      const box = h('div', 'cx-tool');
      const pw = rects[i].w, ph = rects[i].h;
      const ic = h('div', 'cx-icon', { html: kindIcon(it.kind) });
      const isz = Math.round(Math.min(ph * 0.34, 110));
      ic.style.cssText = `left:${pw - isz - 34}px;top:${Math.round(ph * 0.14)}px;width:${isz}px;height:${isz}px;background:${C.white};border:5px solid ${C.ink};border-radius:50%;padding:${Math.round(isz * 0.2)}px;box-shadow:5px 5px 0 ${C.ink};`;
      pn.el.appendChild(ic);
      const tn = h('div', 'cx-tn', { text: String(it.tool || it.kind || '').replace(/_/g, ' ').toUpperCase() });
      tn.style.fontSize = `${Math.round(clamp(pw / 8.5, 40, 64))}px`;
      const ta = h('div', 'cx-ta', { text: String(it.arg || '') + (it.clipped ? '\u2026' : '') });
      ta.style.maxWidth = `${pw - 56}px`;
      ta.style.fontSize = '26px';
      box.append(tn, ta);
      box.style.cssText = `left:26px;bottom:${Math.round(ph * 0.12)}px;max-width:${pw - 40}px;`;
      pn.el.appendChild(box);
      const tt = h('div', 'cx-tt', { text: clock(it.t) });
      tt.style.cssText += 'left:22px;top:20px;';
      pn.el.appendChild(tt);
      return { pn, ic, box, tt, at: t0 + i * step, r: Math.floor(i / cols) };
    });
    const block = (i) => {
      const r = Math.floor(i / cols), c = i % cols;
      const c0 = cols <= 2 ? 0 : Math.min(cols - 2, Math.floor(c / 2) * 2);
      const r0 = nr <= 2 ? 0 : Math.min(nr - 2, r);
      const rs = cells.filter((q, k) => { const rr = Math.floor(k / cols), cc = k % cols; return rr >= r0 && rr < r0 + 2 && cc >= c0 && cc < c0 + 2; }).map((q) => q.pn.rect);
      const x0 = Math.min(...rs.map((q) => q.x)), y0 = Math.min(...rs.map((q) => q.y));
      return { key: `${r0}:${c0}`, rect: { x: x0, y: y0, w: Math.max(...rs.map((q) => q.x + q.w)) - x0, h: Math.max(...rs.map((q) => q.y + q.h)) - y0 } };
    };
    const ks = [];
    let lastKey = null;
    cells.forEach((c, i) => {
      const b = block(i);
      if (b.key !== lastKey) {
        if (ks.length) ks.push([Math.max(ks[ks.length - 1][0] + 0.05, c.at - 0.32), ks[ks.length - 1][1]]);
        ks.push([Math.max(0, c.at - 0.05), b.rect]);
        lastKey = b.key;
      }
    });
    const tEnd = t0 + n * step;
    if (!ks.length) ks.push([0, 'page']);
    ks.push([Math.min(dur - 0.6, tEnd + 0.15), ks[ks.length - 1][1]], [Math.min(dur - 0.1, tEnd + 0.65), 'page'], [dur + 1, 'page']);
    ks.sort((a, b) => a[0] - b[0]);
    const cam = P.track(ks, 30, L ? 1.9 : 1.25);
    return {
      cues: cells.map((c) => ({ t: c.at + 0.05, sfx: 'appear', gain_db: -14 })),
      render(t) {
        P.spinRays(t);
        cells.forEach((c, i) => {
          P.panelIn(c.pn, t, c.at, i % 2 ? 'top' : 'left');
          const pp = pop(t, c.at + 0.12, 0.2, 0.6);
          css(c.ic, { opacity: pp.op.toFixed(3), transform: `rotate(${(i % 2 ? 6 : -6)}deg) scale(${pp.s.toFixed(4)})` });
          snapIn(c.box, t, c.at + 0.18, { rise: 20, from: 0.9, origin: '0 100%' });
          snapIn(c.tt, t, c.at + 0.1, { rise: 0, from: 0.8, origin: '0 0' });
        });
        P.camera(t, cam(t));
      },
    };
  },
});
