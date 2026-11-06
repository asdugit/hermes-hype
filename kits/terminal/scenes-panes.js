// Showreel kit "terminal" — pane scenes: TERMINAL, CODE, DIFF, MONTAGE, PROBLEM, PLAN.
// Layout is computed on the Plex Mono grid (advance 0.6 em, line-height 1.3); the "camera" is the terminal:
// whole-line scrolls, zoom by font-size steps, the cursor as the point of attention.

import { css } from '../base/dom.js';
import { clock } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { tubeScene } from './tube.js';
import { ADV, lineH, sp, esc, len, fit, wrap, box, row, txt, typing, printing, blink, cursor, spin, leader, gridFont } from './crt.js';
import { termPane, codePane, diffPane, runNumbers, odometer } from './pane.js';

/** Largest grid font whose `cols` x `rows` block fits `w` x `h` px (stepped sizes), else `min`. */
export function paneFont(cols, rows, w, h, max = 40, min = 22) {
  for (const s of [60, 50, 40, 36, 34, 30, 28, 26, 24, 22, 20]) {
    if (s > max || s < min) continue;
    if (cols * s * ADV <= w && rows * lineH(s) <= h) return s;
  }
  return min;
}

/** Columns that fit ~90 % of the lines (longer ones get an ellipsis) instead of the single longest line. */
export function p90(lengths, min = 40) {
  const s = lengths.slice().sort((a, b) => a - b);
  return Math.max(min, s.length ? s[Math.min(s.length - 1, Math.floor(s.length * 0.9))] : min);
}

/** Content box (x, y, w, h) below the status bar. */
export function contentBox(F, T) {
  const top = F.portrait ? T.M.t + 30 : T.M.t + 76;
  return { x: T.M.l, y: top, w: F.W - T.M.l - T.M.r, h: F.H - top - T.M.b };
}

/** Discrete zoom steps (terminal zoom): returns scale at t, jumping through `n` levels from 1 to z. */
export function zoomSteps(t, t0, z, n = 3, gap = 0.12) {
  if (t < t0 || z <= 1.001) return 1;
  const i = Math.min(n, Math.floor((t - t0) / gap) + 1);
  return Math.pow(z, i / n);
}

// --------------------------------------------------------------------------------------------- TERMINAL
tubeScene('kit:terminal/TERMINAL', {
  describe: 'Native CRT terminal: the command types at a human cadence, verbatim output streams line by line in a box-drawn pane, the PASS line goes over-driven with an inverse block and a beep; test counts stated in the output roll on odometer drums.',
  params: {
    cmd: { type: 'string', default: '', doc: 'command line' }, output: { type: 'array', default: [], doc: '<= 12 verbatim output lines' },
    truncated_top: { type: 'bool', default: false, doc: 'output was cut at the top' }, exit_code: { type: 'int', default: null, doc: 'exit code' },
    elapsed_s: { type: 'number', default: null, doc: 'runtime seconds' }, ok: { type: 'bool', default: true, doc: 'run succeeded' },
    tests_passed: { type: 'bool', default: false, doc: 'PASS block + beep' },
  },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
    const nums = runNumbers(p);
    const stripH = nums.length ? (L ? nums.length * 150 + 40 : 230) : 0;
    const cmd = String(p.cmd || ''), outs = (p.output || []).map(String);
    const need = Math.max(len(cmd) + 2, ...outs.map((s) => len(s) + (p.tests_passed ? 8 : 0)), 30);
    const fs = L ? 34 : paneFont(need + 4, Math.min(12, outs.length) + 7, B.w, B.h - stripH, 40, 26);
    const maxCols = Math.floor(B.w / (fs * ADV)) - 4;
    const inner = clamp(need, Math.min(L ? 37 : 46, maxCols), maxCols);
    const syncPass = Number(p._sync && p._sync.pass);
    const pane = termPane(p, { inner, t0: 0.3, maxType: Math.min(1.5, dur * 0.3), wrapCmd: L, maxRows: L ? 16 : 12,
      badgeAt: Number.isFinite(syncPass) ? syncPass : 0 });
    const pw = pane.cols * fs * ADV, ph = pane.rows * lineH(fs);
    const total = ph + (stripH ? stripH + 40 : 0);
    const x = B.x + (B.w - pw) / 2, y = B.y + Math.max(0, (B.h - total) / 2);
    T.mount(pane.el, x, y, fs);
    const odos = nums.map((n, i) => {
      const o = odometer(n.display, L ? 116 : 124);
      T.scr.appendChild(o.el);
      const lbl = T.disp(0, 0, 26);
      lbl.className = 'tm-lbl';
      lbl.textContent = n.label;
      if (L) {
        css(o.el, { left: `${x}px`, top: `${y + ph + 40 + i * 150}px` });
        css(lbl, { left: `${x + 290}px`, top: `${y + ph + 40 + i * 150 + o.h / 2 - 16}px` });
      } else {
        const colW = pw / Math.max(1, nums.length);
        css(o.el, { left: `${x + i * colW}px`, top: `${y + ph + 40}px` });
        css(lbl, { left: `${x + i * colW}px`, top: `${y + ph + 40 + o.h + 14}px` });
      }
      return { o, lbl, i };
    });
    const rollAt = pane.badgeAt + 0.05;
    const cues = [...pane.cues];
    odos.forEach((d) => cues.push({ t: rollAt + 0.85 + d.i * 0.12, sfx: 'hit', gain_db: -10 }));
    T.bar('terminal', p.label || '');
    return {
      cues,
      render(t) {
        pane.update(t);
        for (const d of odos) {
          const a = t >= rollAt + d.i * 0.12 - 0.15;
          css(d.o.el, { visibility: a ? 'visible' : 'hidden' });
          css(d.lbl, { visibility: a ? 'visible' : 'hidden' });
          d.o.update(t, rollAt + d.i * 0.12, rollAt + 0.85 + d.i * 0.12 + d.o.digits * 0.12);
        }
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- CODE
tubeScene('kit:terminal/CODE', {
  describe: 'Code in a box-drawn pane with line numbers: the file prints line by line, the page jumps to the focus range in whole-line steps, focus lines go hot (rest dims), then the view zooms in font-size steps.',
  params: {
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    lines: { type: 'array', default: [], doc: '<= 18 verbatim lines' }, start: { type: 'int', default: 1, doc: 'first line number' },
    focus: { type: 'array', default: [1, 1], doc: '[a, b] focus line numbers' }, new_file: { type: 'bool', default: false, doc: 'file was created' },
  },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
    const lines = (p.lines || []).map(String);
    const gw = String((Number(p.start) || 1) + lines.length).length;
    const need = p90(lines.map((s) => len(s.replace(/\t/g, '    ').replace(/\s+$/, ''))), 40) + gw + 3;
    const maxRows = L ? 22 : 18;
    const fs = paneFont(need + 4, Math.min(maxRows, lines.length) + 2, B.w, B.h, L ? 26 : 34, L ? 22 : 24);
    const inner = Math.min(need, Math.floor(B.w / (fs * ADV)) - 4);
    const pane = codePane(p, { inner, t0: 0.25, maxRows, focusAt: clamp(dur * 0.42, 1.3, 2.6) });
    const pw = pane.cols * fs * ADV, ph = pane.rows * lineH(fs);
    const x = B.x + (B.w - pw) / 2, y = B.y + (B.h - ph) / 2;
    T.mount(pane.el, x, y, fs, T.clip(B));
    // zoom target: the focus rows fill ~55 % of the content height, left edge stays at the margin
    const fr = pane.focusRows, lh = lineH(fs);
    const fy = y + (1 + (fr[0] + fr[1]) / 2 + 0.5) * lh;
    const z = clamp((B.h * 0.5) / ((fr[1] - fr[0] + 1) * lh), 1, L ? 1.2 : 1.3);
    const tz = pane.focusAt + 0.45;
    T.bar('code', String(p.path || ''));
    return {
      cues: [...pane.cues, { t: tz, sfx: 'move', gain_db: -14 }],
      render(t) {
        pane.update(t);
        // scale about the pane's top-left (left edge stays put); the focus rows glide to the box centre as the steps land
        const s = zoomSteps(t, tz, z);
        const w = z > 1.001 ? (s - 1) / (z - 1) : 0;
        const ty = (B.y + B.h / 2 - (y + s * (fy - y))) * w;
        css(pane.el, { transform: s > 1 ? `translate3d(0,${ty.toFixed(1)}px,0) scale(${s.toFixed(4)})` : 'none' });
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- DIFF
tubeScene('kit:terminal/DIFF', {
  describe: '`diff -u` output in a box-drawn pane: hunks print one after another, deleted lines strike through and dim, added lines over-drive hot; the +/- counters in the pane title roll up.',
  params: {
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    hunks: { type: 'array', default: [], doc: '[{header, lines:[[op, text]]}] <= 24 rows' },
    adds: { type: 'int', default: 0, doc: 'lines added' }, dels: { type: 'int', default: 0, doc: 'lines removed' },
  },
  build(ctx, p, F, T) {
    const L = F.portrait, B = contentBox(F, T);
    const rowsAll = (p.hunks || []).reduce((a, hk) => a.concat([String(hk.header || '')], (hk.lines || []).map((l) => '  ' + String(l[1]))), []);
    const need = p90(rowsAll.map((s) => len(s.replace(/\t/g, '    ').replace(/\s+$/, ''))), 44);
    const maxRows = L ? 22 : 16;
    const fs = paneFont(need + 4, Math.min(maxRows, rowsAll.length) + 2, B.w, B.h, L ? 26 : 36, L ? 22 : 24);
    const inner = Math.min(need, Math.floor(B.w / (fs * ADV)) - 4);
    const pane = diffPane(p, { inner, t0: 0.25, maxRows });
    const pw = pane.cols * fs * ADV, ph = pane.rows * lineH(fs);
    T.mount(pane.el, B.x + (B.w - pw) / 2, B.y + (B.h - ph) / 2, fs);
    T.bar('diff', String(p.path || ''));
    return { cues: pane.cues, render(t) { pane.update(t); } };
  },
});

// --------------------------------------------------------------------------------------------- MONTAGE
tubeScene('kit:terminal/MONTAGE', {
  describe: "The agent's tool calls as a scrolling session log, one line per call (session clock, tool, argument); lines arrive on half-beats, the newest in inverse video, the log jumps up in whole lines.",
  params: { items: { type: 'array', default: [], doc: '[{id, t, kind, tool, arg, clipped}] 3-16 tool calls' } },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
    const items = (p.items || []).slice(0, 16);
    const n = items.length;
    const toolW = Math.min(16, Math.max(8, ...items.map((it) => len(String(it.tool || it.kind || '')))));
    const fs = L ? 26 : 32;
    const inner = Math.floor(B.w / (fs * ADV)) - 4;
    const maxRows = Math.max(4, Math.floor((B.h - 2 * lineH(fs)) / lineH(fs)) - 1);
    const visRows = Math.min(maxRows, n + 1);
    const gap = clamp((dur * 0.72 - 0.3) / Math.max(1, n), 0.1, 0.34);
    const at = items.map((_, i) => 0.3 + i * gap);
    const ph = (visRows + 2) * lineH(fs), pw = (inner + 4) * fs * ADV;
    const el = T.pre(B.x + (B.w - pw) / 2, B.y + (B.h - ph) / 2, fs);
    const fmt = (it) => {
      const tm = clock(it.t);
      const tool = fit(String(it.tool || it.kind || ''), toolW);
      const arg = String(it.arg || '').replace(/\s+/g, ' ');
      const head = `${tm.padStart(6, ' ')}  ${tool.padEnd(toolW, ' ')}  `;
      const a = fit(arg, Math.max(6, inner - len(head)));
      return { head, a, n: len(head) + len(a), tm, tool };
    };
    const lines = items.map(fmt);
    T.bar('session log', `${n} tool calls`);
    return {
      cues: at.map((t) => ({ t, sfx: 'type', gain_db: -12 })),
      render(t) {
        let k = 0;
        while (k < n && at[k] <= t) k++;
        const rows = [];
        const first = Math.max(0, k - visRows);
        for (let i = first; i < k; i++) {
          const l = lines[i];
          if (i === k - 1 && t - at[i] < Math.max(0.12, gap * 0.9)) rows.push(row(sp('ih', l.head + l.a), l.n));
          else rows.push(row(sp('d', l.tm.padStart(6, ' ') + '  ') + sp('m', l.tool.padEnd(toolW, ' ')) + '  ' + esc(l.a), l.n));
        }
        if (rows.length < visRows) rows.push(row(sp('d', '     ') + cursor(blink(t, 3, k < n)), 6));
        while (rows.length < visRows) rows.push(txt('', ''));
        el.set(box('session.log', inner, rows, { right: `${k}/${n}` }).join('\n'));
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- PROBLEM
tubeScene('kit:terminal/PROBLEM', {
  describe: "The user's request typed into the agent's prompt letter by letter (human input, key ticks) inside a box-drawn pane; long prompts scroll up in whole lines.",
  params: { text: { type: 'string', default: '', doc: 'verbatim prompt (redacted)' }, truncated: { type: 'bool', default: false, doc: 'adds an ellipsis' } },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
    const fs = L ? 34 : 40;
    const inner = Math.min(L ? 37 : 56, Math.floor(B.w / (fs * ADV)) - 4);
    const textAll = String(p.text || '') + (p.truncated ? ' \u2026' : '');
    const lines = wrap(textAll, inner - 2, '');
    const maxRows = L ? 14 : 9;
    const visRows = Math.min(maxRows, lines.length) + 2;
    const ty = typing(lines.join('\n'), 0.4, { cps: 19, maxDur: Math.max(0.8, dur * 0.62 - 0.4), seed: 11 });
    const pw = (inner + 4) * fs * ADV, ph = (visRows + 2) * lineH(fs);
    const el = T.pre(B.x + (B.w - pw) / 2, B.y + (B.h - ph) / 2, fs);
    T.bar('prompt', 'user');
    return {
      cues: ty.cues({ every: 3, max: 36 }),
      render(t) {
        const n = ty.count(t);
        const typed = [...ty.chars].slice(0, n).join('').split('\n');
        const rows = [txt('', '')];
        const body = typed.map((s, i) => row(sp(i === 0 ? 'd' : '', i === 0 ? '> ' : '  ') + sp('h', s), 2 + len(s)));
        const lastI = body.length - 1;
        body[lastI] = row(body[lastI].html + cursor(n < ty.n || blink(t - ty.end)), body[lastI].n + 1);
        const vis = body.slice(Math.max(0, body.length - (visRows - 1)));
        rows.push(...vis);
        while (rows.length < visRows) rows.push(txt('', ''));
        el.set(box('new session', inner, rows, { right: n < ty.n ? `${spin(t)} typing` : 'sent' }).join('\n'));
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- PLAN
tubeScene('kit:terminal/PLAN', {
  describe: "The agent's plan as a boot log: one service line per item with dot leaders; done items flip to [  OK  ] on the beat with a relay click, the active one runs in inverse with a spinner, pending ones WAIT.",
  params: { items: { type: 'array', default: [], doc: '[{text, status}] <= 6 (completed|in_progress|pending)' }, more: { type: 'int', default: 0, doc: 'hidden items count' } },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
    const items = (p.items || []).slice(0, 8);
    const fs = L ? 30 : 40;
    const inner = Math.min(L ? 40 : 54, Math.floor(B.w / (fs * ADV)) - 4);
    const per = clamp((dur * 0.5) / Math.max(1, items.length), 0.18, 0.42);
    const printAt = items.map((_, i) => 0.3 + i * 0.06);
    const flipAt = items.map((_, i) => 0.6 + i * per);
    const nRows = items.length + (p.more ? 1 : 0) + 2;
    const pw = (inner + 4) * fs * ADV, ph = (nRows + 2) * lineH(fs);
    const el = T.pre(B.x + (B.w - pw) / 2, B.y + (B.h - ph) / 2, fs);
    const done = items.filter((it) => it.status === 'completed').length;
    T.bar('plan', `${done}/${items.length + (Number(p.more) || 0)} done`);
    const cues = [];
    items.forEach((it, i) => { if (it.status !== 'pending') cues.push({ t: flipAt[i], sfx: it.status === 'completed' ? 'click' : 'appear', gain_db: -8 }); });
    return {
      cues,
      render(t) {
        const rows = [txt('', '')];
        items.forEach((it, i) => {
          if (t < printAt[i]) { rows.push(txt('', '')); return; }
          const flipped = t >= flipAt[i];
          let st = '[ WAIT ]', cls = 'f', lab = '';
          if (flipped && it.status === 'completed') { st = '[  OK  ]'; cls = 'm'; lab = 'm'; }
          else if (flipped && it.status === 'in_progress') { st = `[ RUN ${spin(t)}]`; cls = 'ih'; lab = 'h'; }
          rows.push(leader(String(it.text || ''), st, inner, cls, lab));
        });
        if (p.more) rows.push(t >= printAt[printAt.length - 1] ? txt('d', `+ ${p.more} more`) : txt('', ''));
        rows.push(txt('', ''));
        const k = flipAt.filter((x) => x <= t).length;
        el.set(box('plan', inner, rows, { right: `${Math.min(k, done)}/${items.length + (Number(p.more) || 0)}` }).join('\n'));
      },
    };
  },
});

export { seg, ease, lerp, typing, printing, gridFont };
