// Auteur kits/base — TERMINAL block (the one dark panel): command types, output streams line by
// line, then a PASS / exit badge pops. Pure function of t.

import { h, css, ICONS } from './dom.js';
import { seg, ease, clamp } from './motion.js';
import { MONO_ADV } from './code.js';

function wrapPlain(s, max) {
  if (s.length <= max) return [s];
  const out = [];
  let rest = s;
  while (rest.length > max) {
    let cut = rest.lastIndexOf(' ', max);
    if (cut < max * 0.4) cut = max;
    out.push(rest.slice(0, cut));
    rest = rest.slice(cut).replace(/^ +/, '');
  }
  if (rest) out.push(rest);
  return out;
}

const FAIL_RE = /\b(fail(ed|ure|s)?|error|traceback|exception|assert)/i;
const PASS_RE = /\b(\d+ passed|passed|ok\b|success|✓|done)/i;

/**
 * data = TERMINAL {cmd, output, truncated_top, exit_code, elapsed_s, ok, tests_passed}.
 * o: {width, fontSize, typeAt:[t0,t1], streamAt:[t0,t1], badgeAt, wrap, maxRows}
 */
export function termBlock(data, o = {}) {
  const fs = o.fontSize || 24;
  const rowH = Math.round(fs * 1.6);
  const width = o.width || 1100;
  const maxChars = Math.max(20, Math.floor((width - 56) / (fs * MONO_ADV)));
  const el = h('div', 'srb-term');
  const elapsed = data.elapsed_s == null ? '' : `${Number(data.elapsed_s) < 10 ? Number(data.elapsed_s).toFixed(1) : Math.round(Number(data.elapsed_s))} s`;
  const bar = h('div', 'srb-bar');
  bar.append(h('span', '', { html: ICONS.term }), h('span', 'srb-path', { text: o.title || 'terminal' }), h('span', 'srb-sp'));
  if (elapsed) bar.appendChild(h('span', '', { text: elapsed }));
  el.appendChild(bar);
  const out = h('div', 'srb-out');
  const padX = 28, padTop = Math.round(rowH * 0.45);
  out.style.cssText = `font-size:${fs}px;line-height:${rowH}px;padding:${padTop}px ${padX}px ${Math.round(rowH * 0.5)}px;`;
  el.appendChild(out);

  // unwrapped rows are cut to the visible columns with an ellipsis (a hard overflow cut reads as a glitch, and the
  // full-length text box made layout QA report 9000 px commands as running off the frame)
  // (5 % column margin: themes may swap in a slightly wider mono, e.g. Space Mono 0.612 em vs Geist Mono 0.6)
  const fit = (s, n) => { const m = Math.floor(n * 0.95); return s.length > m ? `${s.slice(0, Math.max(1, m - 1)).trimEnd()}\u2026` : s; };
  const cmd = String(data.cmd || '');
  const cmdParts = o.wrap ? wrapPlain(cmd, maxChars - 2) : [fit(cmd, maxChars - 2)];
  const rows = [];
  cmdParts.forEach((c, i) => {
    const line = h('div', 'srb-line srb-cmd');
    if (i === 0) line.appendChild(h('span', 'srb-prompt', { text: '$ ' }));
    else line.append('  ');
    const t = h('span', 'srb-t', { text: c });
    t.style.cssText = 'display:inline-block;overflow:hidden;vertical-align:top;white-space:pre;';
    line.appendChild(t);
    out.appendChild(line);
    rows.push({ el: line, t, len: c.length, cmd: true });
  });
  let outLines = (data.output || []).map(String);
  if (data.truncated_top) outLines = ['\u2026', ...outLines];
  const maxRows = o.maxRows || 14;
  const disp = [];
  for (const ln of outLines) for (const part of (o.wrap ? wrapPlain(ln, maxChars) : [fit(ln, maxChars)])) disp.push({ s: part, src: ln });
  const shown = disp.slice(Math.max(0, disp.length - (maxRows - rows.length)));
  for (const d of shown) {
    const fail = FAIL_RE.test(d.src) && !data.ok;
    const hi = !fail && PASS_RE.test(d.src);
    const line = h('div', 'srb-line' + (fail ? ' err' : hi ? ' hi' : ''), { text: d.s || ' ' });
    if (!o.wrap) line.style.cssText = `max-width:${width - padX * 2}px;text-overflow:clip;`;
    out.appendChild(line);
    rows.push({ el: line, out: true });
  }
  // badge
  const tests = !!data.tests_passed;
  const ok = data.ok !== false && (data.exit_code == null || Number(data.exit_code) === 0);
  const kind = tests && ok ? 'pass' : ok ? 'ok' : 'fail';
  const badge = h('span', `srb-badge ${kind}`);
  badge.innerHTML = (kind === 'fail' ? ICONS.cross : ICONS.check);
  badge.append(kind === 'pass' ? 'PASS' : kind === 'ok' ? `exit ${data.exit_code ?? 0}` : `exit ${data.exit_code ?? 1}`);
  const brow = h('div', '');
  brow.style.cssText = `display:flex;align-items:center;gap:18px;margin-top:${Math.round(rowH * 0.45)}px;height:50px;`;
  brow.appendChild(badge);
  if (kind === 'pass' && data.exit_code != null) brow.appendChild(h('span', 'srb-meta', { text: `exit ${data.exit_code}` }));
  out.appendChild(brow);
  const hgt = 60 + padTop + rows.length * rowH + Math.round(rowH * 0.45) + 50 + Math.round(rowH * 0.5);
  el.style.width = width + 'px';
  el.style.height = hgt + 'px';

  const typeAt = o.typeAt || [0.1, 0.1 + Math.min(1.1, cmd.length * 0.03)];
  const streamAt = o.streamAt || [typeAt[1] + 0.2, typeAt[1] + 0.2 + Math.min(1.6, shown.length * 0.13)];
  const badgeAt = o.badgeAt == null ? streamAt[1] + 0.25 : o.badgeAt;
  const cues = [];
  const nt = Math.min(8, Math.max(2, Math.round((typeAt[1] - typeAt[0]) / 0.12)));
  for (let k = 0; k < nt; k++) cues.push({ t: typeAt[0] + (k + 0.2) * (typeAt[1] - typeAt[0]) / nt, sfx: 'type', gain_db: -16 });
  cues.push({ t: badgeAt + 0.04, sfx: kind === 'pass' ? 'pass' : kind === 'fail' ? 'fail' : 'appear', gain_db: kind === 'pass' ? -4 : -10 });

  const cmdTotal = rows.filter((r) => r.cmd).reduce((a, r) => a + r.len, 0);
  const outRows = rows.filter((r) => r.out);
  function update(t) {
    const u = seg(t, typeAt[0], typeAt[1]);
    let left = Math.floor(u * cmdTotal + 1e-6);
    for (const r of rows) {
      if (!r.cmd) continue;
      const n = clamp(left, 0, r.len);
      left -= r.len;
      css(r.t, { width: `${n}ch` });
    }
    const n = outRows.length;
    outRows.forEach((r, i) => {
      const t0 = streamAt[0] + (n > 1 ? (i * (streamAt[1] - streamAt[0])) / n : 0);
      const a = seg(t, t0, t0 + 0.18, ease.outCubic);
      css(r.el, { opacity: a.toFixed(3), transform: `translate(0, ${((1 - a) * 8).toFixed(2)}px)` });
    });
    const b = seg(t, badgeAt, badgeAt + 0.42, ease.outBack);
    const bo = seg(t, badgeAt, badgeAt + 0.12);
    css(brow, { opacity: bo.toFixed(3), transform: `scale(${(0.7 + 0.3 * b).toFixed(4)})`, transformOrigin: '0 50%' });
  }
  return { el, w: width, h: hgt, update, cues, kind, badgeAt, rowH,
    outRect: () => ({ x: 0, y: 60, w: width, h: hgt - 60 }) };
}

/** Terminal font size from its content: short outputs get big type so the panel carries the frame. */
export function termFont(c, portrait, base = 26) {
  const rows = 1 + (c.output || []).length;
  const longest = Math.max(String(c.cmd || '').length + 2, ...(c.output || []).map((s) => String(s).length));
  let fs = rows <= 3 ? 38 : rows <= 5 ? 34 : rows <= 8 ? 30 : base;
  const maxW = portrait ? 940 : 1560;
  if (!portrait) fs = Math.min(fs, Math.max(base, Math.floor((maxW - 70) / (longest * 0.6))));
  else {
    // keep tabular output on one line when it can stay >= 22 px; otherwise wrap at 24 px
    const longestOut = Math.max(20, ...(c.output || []).map((s) => String(s).length));
    const fit = Math.floor((maxW - 60) / (longestOut * 0.6));
    fs = fit >= 22 ? Math.min(fs, fit) : Math.min(fs, 24);
  }
  return fs;
}

/** Terminal panel width that hugs its longest line (landscape) or the safe width (portrait). */
export function termWidth(c, fs, portrait) {
  if (portrait) return 960;
  const longest = Math.max(String(c.cmd || '').length + 2, ...(c.output || []).map((s) => String(s).length), 30);
  return Math.round(Math.min(1560, Math.max(1000, longest * fs * 0.6 + 90)));
}
