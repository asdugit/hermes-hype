// Hype kit "terminal" — box-drawn panes on the character grid: terminal run, code listing, unified diff,
// plus odometer drums. Each builder returns {el, cols, rows, update(t), cues, ...}; update re-renders the pane's
// HTML from t (the DOM is only touched when the visible text changes).

import { h, css } from '../base/dom.js';
import { highlight } from '../base/syntax.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { sp, esc, len, fit, wrap, box, row, txt, typing, printing, blink, cursor, spin, lineH, splitDisplay } from './crt.js';

const FAIL_RE = /\b(fail(ed|ure|s)?|error|traceback|exception)\b/i;
const SUMMARY_RE = /\b\d+ (passed|failed|errors?)\b|\bok\b|\bpassed\b/i;

/** Numbers a test run's verbatim output states (pytest/jest-style summaries); [] when none. */
export function runNumbers(data) {
  const outp = (data.output || []).map(String).join('\n');
  const out = [];
  const p = /(\d+) passed/.exec(outp), f = /(\d+) failed/.exec(outp), s = /\bin ([\d.]+) ?s(ec(onds)?)?\b/.exec(outp);
  if (p) out.push({ display: p[1], label: 'passed' });
  if (f) out.push({ display: f[1], label: 'failed' });
  if (s) out.push({ display: s[1], label: 'seconds' });
  return out;
}

const tokCls = { k: 'h', f: 'h', n: 'h', s: 'm', c: 'd', p: '' };
function codeHtml(line, lang, path, mode) {
  if (mode === 'dim') return sp('d', line);
  return highlight(line, lang, path).map(([c, s]) => sp(mode === 'hot' && !c ? 'h' : tokCls[c] || '', s)).join('');
}

/** Visible row window that keeps rows [a, b] in view (whole-line steps). */
function windowFor(n, maxRows, a, b) {
  if (n <= maxRows) return 0;
  const mid = Math.round((a + b) / 2 - maxRows / 2);
  return clamp(mid, 0, n - maxRows);
}

// ------------------------------------------------------------------------------------------ terminal pane
/**
 * data = TERMINAL {cmd, output, exit_code, elapsed_s, ok, tests_passed, truncated_top}.
 * o: {inner, t0, cps, maxType, per, badgeAt, maxRows, wrapCmd, title, finalPrompt}
 */
export function termPane(data, o) {
  const inner = o.inner;
  const cmd = String(data.cmd || '');
  const cmdLines = o.wrapCmd ? wrap(cmd, inner - 2, '  ') : [fit(cmd, inner - 2)];
  const ty = typing(cmdLines.join(''), o.t0 ?? 0.25, { cps: o.cps || 17, maxDur: o.maxType || 1.4, seed: 3 });
  let out = (data.output || []).map((s) => String(s).replace(/\t/g, '    ').replace(/\s+$/, ''));
  if (data.truncated_top) out = ['\u2026', ...out];
  const outRows = [];
  for (const ln of out) for (const w of wrap(ln, inner, '  ')) outRows.push(w);
  const runStart = ty.end + 0.22;
  const pr = printing(outRows.length, runStart, Math.min(o.per || 0.07, 1.3 / Math.max(1, outRows.length)));
  const ok = data.ok !== false && (data.exit_code == null || Number(data.exit_code) === 0);
  const tests = !!data.tests_passed;
  const summaryIdx = (() => { for (let i = outRows.length - 1; i >= 0; i--) if (SUMMARY_RE.test(outRows[i]) || FAIL_RE.test(outRows[i])) return i; return outRows.length - 1; })();
  const badge = tests ? ' PASS ' : !ok ? ' FAIL ' : '';
  const badgeAt = Math.max(pr.end + 0.12, o.badgeAt ?? 0);
  const maxRows = o.maxRows || 12;
  const title = o.title || (cmd.split(/\s+/)[0] || 'tty').replace(/^.*[\\/]/, '');
  const exitTxt = data.exit_code == null ? (ok ? 'ok' : 'err') : `exit ${data.exit_code}`;
  const elapsed = data.elapsed_s == null ? '' : ` \u00b7 ${Number(data.elapsed_s) < 10 ? Number(data.elapsed_s).toFixed(1) : Math.round(Number(data.elapsed_s))}s`;
  const el = h('pre', 'tm-pre');
  const cues = [...ty.cues({ every: 3 })];
  cues.push({ t: ty.end + 0.1, sfx: 'click', gain_db: -10 });
  if (badge) cues.push({ t: badgeAt, sfx: tests ? 'pass' : 'fail', gain_db: tests ? -4 : -8 });
  const lineCls = (s, i) => {
    if (i === summaryIdx && (tests || !ok)) return 'h';
    if (FAIL_RE.test(s)) return 'h';
    return '';
  };
  function rowsAt(t) {
    const rows = [txt('', '')];
    const n = ty.count(t);
    const curLine = (() => { let u = 0; for (let i = 0; i < cmdLines.length; i++) { if (n <= u + len(cmdLines[i])) return i; u += len(cmdLines[i]); } return cmdLines.length - 1; })();
    let used = 0;
    cmdLines.forEach((c, i) => {
      const shown = [...c].slice(0, clamp(n - used, 0, len(c))).join('');
      used += len(c);
      if (i > curLine) return;
      const cur = t < runStart && i === curLine ? cursor(t >= ty.at[0] - 0.05 || blink(t)) : '';
      rows.push(row((i === 0 ? sp('d', '$ ') : '') + sp('h', shown) + cur, (i === 0 ? 2 : 0) + len(shown) + (cur ? 1 : 0)));
    });
    const k = pr.count(t);
    if (k > 0) rows.push(txt('', ''));
    for (let i = 0; i < k; i++) {
      const s = outRows[i];
      const cls = lineCls(s, i);
      if (i === summaryIdx && badge && t >= badgeAt) rows.push(row(sp(cls || 'h', s) + '  ' + sp(blink(t - badgeAt, 4) || t - badgeAt > 0.5 ? 'ih' : 'h', badge), len(s) + 2 + len(badge)));
      else {
        const kv = /^(\S+)(\s{2,})(.*)$/.exec(s);
        rows.push(kv && !cls ? row(sp('m', kv[1]) + kv[2] + esc(kv[3]), len(s)) : txt(cls, s));
      }
    }
    if (o.finalPrompt !== false && t >= badgeAt + 0.05) rows.push(txt('', ''), row(sp('d', '$ ') + cursor(blink(t - badgeAt)), 3));
    else rows.push(txt('', ''));
    return rows;
  }
  // fixed height: the most rows the pane ever shows (so the box does not grow)
  const fullRows = Math.min(maxRows, 1 + cmdLines.length + 1 + outRows.length + (o.finalPrompt === false ? 1 : 2));
  function update(t) {
    let rows = rowsAt(t);
    if (rows.length > fullRows) rows = rows.slice(rows.length - fullRows); // scrolls in whole lines
    while (rows.length < fullRows) rows.push(txt('', ''));
    const right = t >= badgeAt ? exitTxt + elapsed : t >= runStart ? `${spin(t)} running` : '';
    el.set(box(title, inner, rows, { right }).join('\n'));
  }
  el.set = (html) => { if (el.__html !== html) { el.__html = html; el.innerHTML = html; } };
  return { el, cols: inner + 4, rows: fullRows + 2, update, cues, typeEnd: ty.end, runStart, printEnd: pr.end, badgeAt, tests, ok, summaryIdx };
}

// ------------------------------------------------------------------------------------------ code pane
/** data = CODE {path, lang, lines, start, focus:[a,b], new_file}. o: {inner, t0, per, focusAt, maxRows} */
export function codePane(data, o) {
  const lines = (data.lines || []).map((s) => String(s).replace(/\t/g, '    ').replace(/\s+$/, ''));
  const start = Number(data.start) || 1;
  const last = start + Math.max(0, lines.length - 1);
  const gw = String(last).length;
  const inner = o.inner, cw = inner - gw - 3;
  const [fa, fb] = Array.isArray(data.focus) && data.focus.length >= 2 ? data.focus.map(Number) : [start, start];
  const fi0 = clamp(fa - start, 0, lines.length - 1), fi1 = clamp(fb - start, fi0, lines.length - 1);
  const pr = printing(lines.length, o.t0 ?? 0.2, Math.min(o.per || 0.045, 1.2 / Math.max(1, lines.length)));
  const focusAt = Math.max(o.focusAt ?? 0, pr.end + 0.15);
  const maxRows = o.maxRows || 16;
  const win0 = 0, win1 = windowFor(lines.length, maxRows, fi0, fi1);
  const name = String(data.path || 'file').replace(/^.*[\\/]/, '');
  const right = `${data.new_file ? 'new \u00b7 ' : ''}L${fa}\u2013${fb}`;
  const el = h('pre', 'tm-pre');
  el.set = (html) => { if (el.__html !== html) { el.__html = html; el.innerHTML = html; } };
  const cues = [{ t: focusAt, sfx: 'click', gain_db: -10 }];
  // the page jumps to the focus in whole-line steps (3 steps, 70 ms apart), never a smooth scroll
  const winAt = (t) => {
    if (win1 === win0 || t < focusAt) return win0;
    const steps = 3, u = Math.min(steps, Math.floor((t - focusAt) / 0.07) + 1) / steps;
    return Math.round(lerp(win0, win1, u));
  };
  function update(t) {
    const k = pr.count(t), w = winAt(t), lit = t >= focusAt;
    const rows = [];
    for (let i = w; i < Math.min(lines.length, w + maxRows); i++) {
      if (i >= k) { rows.push(txt('', '')); continue; }
      const isF = i >= fi0 && i <= fi1;
      const no = String(start + i).padStart(gw, ' ');
      const codeTxt = fit(lines[i], cw);
      const mode = !lit ? 'norm' : isF ? 'hot' : 'dim';
      const g = lit && isF ? sp('ih', no) : sp(lit ? 'f' : 'd', no);
      const cur = lit && i === fi1 ? cursor(blink(t - focusAt)) : '';
      rows.push(row(g + sp('d', ' \u2502 ') + codeHtml(codeTxt, data.lang, data.path, mode) + cur, gw + 3 + len(codeTxt) + (cur ? 1 : 0)));
    }
    while (rows.length < Math.min(maxRows, lines.length)) rows.push(txt('', ''));
    el.set(box(name, inner, rows, { right: lit ? right : `${Math.min(k, lines.length)}/${lines.length}` }).join('\n'));
  }
  return { el, cols: inner + 4, rows: Math.min(maxRows, lines.length) + 2, update, cues, focusAt, printEnd: pr.end, focusRows: [fi0 - win1, fi1 - win1] };
}

// ------------------------------------------------------------------------------------------ diff pane
/** data = DIFF {path, hunks:[{header, lines:[[op,text]]}], adds, dels}. o: {inner, t0, per, maxRows} */
export function diffPane(data, o) {
  const inner = o.inner;
  const rows0 = [];
  for (const hk of data.hunks || []) {
    rows0.push({ op: '@', text: String(hk.header || '@@') });
    for (const [op, text] of hk.lines || []) rows0.push({ op: op === '+' || op === '-' ? op : ' ', text: String(text).replace(/\t/g, '    ').replace(/\s+$/, '') });
  }
  const t0 = o.t0 ?? 0.2;
  // hunk by hunk: lines inside a hunk print fast, a short beat between hunks
  const at = [];
  let tt = t0;
  const per = Math.min(o.per || 0.05, 1.4 / Math.max(1, rows0.length));
  rows0.forEach((r, i) => { if (r.op === '@' && i > 0) tt += 0.22; at.push(tt); tt += per; });
  const printEnd = tt;
  const strikeAt = printEnd + 0.12, litAt = printEnd + 0.3;
  const changed = rows0.map((r, i) => (r.op === '+' || r.op === '-' ? i : -1)).filter((i) => i >= 0);
  const c0 = changed.length ? changed[0] : 0, c1 = changed.length ? changed[changed.length - 1] : 0;
  const maxRows = o.maxRows || 16;
  const win = windowFor(rows0.length, maxRows, c0, c1);
  const adds = Number(data.adds) || rows0.filter((r) => r.op === '+').length;
  const dels = Number(data.dels) || rows0.filter((r) => r.op === '-').length;
  const name = String(data.path || 'diff').replace(/^.*[\\/]/, '');
  const el = h('pre', 'tm-pre');
  el.set = (html) => { if (el.__html !== html) { el.__html = html; el.innerHTML = html; } };
  const cues = [{ t: strikeAt, sfx: 'click', gain_db: -12 }, { t: litAt, sfx: 'appear', gain_db: -10 }];
  function update(t) {
    const rows = [];
    for (let i = win; i < Math.min(rows0.length, win + maxRows); i++) {
      const r = rows0[i];
      if (t < at[i]) { rows.push(txt('', '')); continue; }
      const body = fit(r.text, inner - 2);
      if (r.op === '@') rows.push(txt('d', fit(r.text, inner)));
      else if (r.op === '-') rows.push(row(sp('m', '- ') + sp(t >= strikeAt ? 'd s' : 'm', body), 2 + len(body)));
      else if (r.op === '+') rows.push(row(sp('h', '+ ') + sp(t >= litAt ? 'h' : '', body), 2 + len(body)));
      else rows.push(row('  ' + sp('m', body), 2 + len(body)));
    }
    while (rows.length < Math.min(maxRows, rows0.length)) rows.push(txt('', ''));
    // counters roll up while the hunks print
    const u = seg(t, t0, printEnd, ease.outCubic);
    const right = `+${Math.round(adds * u)} \u2212${Math.round(dels * u)}`;
    el.set(box(name, inner, rows, { right, rightCls: 'h' }).join('\n'));
  }
  return { el, cols: inner + 4, rows: Math.min(maxRows, rows0.length) + 2, update, cues, printEnd, litAt, adds, dels };
}

// ------------------------------------------------------------------------------------------ odometer
/**
 * Odometer drums for a display string ("14", "47 min", "31.9"): each digit is a drum that rolls from 0 with
 * per-digit inertia (the last digit spins longest) and settles with a click. size = VT323 px.
 * update(t, t0, t1) rolls between t0 and t1. Returns {el, w, h, update, settle (time of the last click)}.
 */
export function odometer(display, size) {
  const { pre, body, unit } = splitDisplay(display);
  const el = h('div', 'tm-odo');
  el.style.fontSize = `${size}px`;
  const cellH = Math.round(size * 0.96), digitH = Math.round(size * 0.66), cellW = Math.round(size * 0.5);
  el.style.height = `${cellH}px`;
  const digits = [];
  const chars = [...body];
  const nDig = chars.filter((c) => /\d/.test(c)).length;
  let place = nDig - 1;
  if (pre) el.appendChild(h('span', 'tm-unit', { text: pre, style: `margin:0 .12em 0 0;` }));
  for (const c of chars) {
    if (!/\d/.test(c)) { el.appendChild(h('span', 'tm-sep', { text: c, style: `width:${Math.round(size * 0.3)}px;` })); continue; }
    const cell = h('span', 'tm-cell');
    cell.style.cssText = `width:${cellW}px;height:${cellH}px;`;
    const drum = h('span', 'tm-drum');
    drum.dataset.qa = 'off';        // rolling reels: digits pass and peek out of the cell by design (QA: proxy below)
    for (let i = 0; i <= 11; i++) {
      const b = h('b', '', { text: String((i + 9) % 10) });
      b.style.cssText = `height:${digitH}px;line-height:${digitH}px;`;
      drum.appendChild(b);
    }
    cell.appendChild(drum);
    el.appendChild(cell);
    digits.push({ drum, target: Number(c), place: place-- });
  }
  if (unit.trim()) el.appendChild(h('span', 'tm-unit', { text: unit.trim(), style: `font-size:${Math.round(size * 0.42)}px;align-self:flex-end;margin-bottom:${Math.round(size * 0.12)}px;margin-left:.3em;` }));
  if (digits.length) {             // layout-QA proxy: the settled number, transparent, over the drums
    const qa = h('span', 'tm-odo-qa', { text: body });
    qa.style.cssText = `position:absolute;left:${pre ? '1em' : '0'};top:0;height:${cellH}px;line-height:${cellH}px;color:transparent;text-shadow:none;white-space:pre;pointer-events:none;`;
    el.appendChild(qa);
  }
  const value = Number(chars.filter((c) => /\d/.test(c)).join('')) || 0;
  function update(t, t0, t1) {
    for (const d of digits) {
      // digit d.place: lower places settle later (inertia); position = floor(v / 10^place) with a roll near carries
      const end = t1 - d.place * 0.12;
      const u = seg(t, t0, end, ease.outCubic);
      const v = value * u, q = Math.pow(10, d.place);
      const whole = Math.floor(v / q), frac = (v / q) - whole;
      const roll = d.place === 0 ? frac : clamp((frac - 0.9) / 0.1);
      const pos = (whole + roll) % 10;
      const settled = t >= end;
      const p = settled ? d.target : pos;
      const off = -(p + 1) * digitH + (cellH - digitH) / 2;
      css(d.drum, { transform: `translate3d(0,${off.toFixed(2)}px,0)` });
      // settled: the shown digit is lit, its neighbours peek out of the drum as faint ghosts
      const key = settled ? d.target + 1 : -1;
      if (d.lit !== key) {
        d.lit = key;
        Array.from(d.drum.children).forEach((b, i) => { b.className = key < 0 || i === key ? '' : 'g'; });
      }
    }
  }
  const settle = (t1) => t1;
  return { el, h: cellH, update, settle, digits: digits.length, unit };
}

export { lineH };
