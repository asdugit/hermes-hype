// Hype kits/base — CODE and DIFF panel blocks (paper editor panels).
// A block is {el, w, h, update(t), rowTop(i), rowsRect(a, b), cues}; sizes in reference px.
// update(t) is a pure function of the shot-local time t.

import { h, css, cls, ICONS } from './dom.js';
import { clamp, seg, ease } from './motion.js';
import { highlight, wrapTokens } from './syntax.js';

export const MONO_ADV = 0.6; // Geist Mono advance width in em (letter-spacing 0 on code)

/** Panel title bar with a file icon, a path (dir dimmed, basename bold) and right-side items. */
export function pathBar(path, rightKids = [], icon = ICONS.file, maxChars = 60) {
  const bar = h('div', 'srb-bar');
  bar.appendChild(h('span', '', { html: icon }));
  const p = String(path || '');
  let shown = p;
  if (shown.length > maxChars) {
    const parts = shown.split('/');
    while (parts.length > 1 && ('…/' + parts.join('/')).length > maxChars) parts.shift();
    shown = '…/' + parts.join('/');
  }
  const cut = shown.lastIndexOf('/');
  const ps = h('span', 'srb-path');
  if (cut >= 0) ps.append(shown.slice(0, cut + 1));
  ps.appendChild(h('b', '', { text: cut >= 0 ? shown.slice(cut + 1) : shown }));
  bar.append(ps, h('span', 'srb-sp'));
  for (const k of rightKids) if (k) bar.appendChild(k);
  return bar;
}

function tokenSpans(parent, toks) {
  for (const [c, t] of toks) {
    if (!c) parent.appendChild(parent.ownerDocument.createTextNode(t));
    else parent.appendChild(h('span', 'tk-' + c, { text: t }));
  }
}

function wordEnds(s) {
  // indices just after each word (streaming unit = a word incl. its leading whitespace)
  const ends = [];
  const re = /\s*\S+/g;
  let m;
  while ((m = re.exec(s))) ends.push(m.index + m[0].length);
  return ends.length ? ends : [0];
}

/**
 * CODE panel. data = TimelineScene.data for CODE {path, lang, lines, start, focus:[a,b], total_lines, new_file}.
 * o: {width, fontSize, reveal:[t0,t1] (stream by words), focusAt, wrap (bool), caret (bool)}
 */
export function codeBlock(data, o = {}) {
  const fs = o.fontSize || 26;
  const rowH = Math.round(fs * (o.lineHeight || 1.62));
  const width = o.width || 1300;
  const lines = Array.isArray(data.lines) ? data.lines.map(String) : [];
  const start = Number(data.start) || 1;
  const focus = Array.isArray(data.focus) ? data.focus.map(Number) : [0, -1];
  const lastNo = start + Math.max(0, lines.length - 1);
  const gutW = Math.round(fs * 0.86 * MONO_ADV * String(lastNo).length + 22 + 26);
  const maxChars = Math.max(16, Math.floor((width - gutW - 28) / (fs * MONO_ADV)));
  const lang = data.lang || '';
  const el = h('div', 'srb-panel srb-codepanel');
  el.appendChild(pathBar(data.path, [h('span', '', { text: lang || '' })], ICONS.file, Math.floor((width - 200) / 13.2)));
  const body = h('div', 'srb-code');
  body.style.cssText = `font-size:${fs}px;padding:${Math.round(rowH * 0.4)}px 0 ${Math.round(rowH * 0.55)}px;`;
  el.appendChild(body);
  const rows = [];
  lines.forEach((ln, i) => {
    const no = start + i;
    const toks = highlight(ln, lang, data.path);
    const parts = o.wrap === false ? [toks] : wrapTokens(toks, maxChars);
    parts.forEach((pt, j) => {
      const r = h('div', 'srb-row' + (j > 0 ? ' cont' : ''));
      r.style.height = rowH + 'px';
      const hl = h('div', 'srb-hl');
      const g = h('span', 'srb-g', { text: j === 0 ? String(no) : '\u21b5' });
      g.style.width = gutW + 'px';
      const t = h('span', 'srb-t');
      tokenSpans(t, pt);
      const flat = pt.map((x) => x[1]).join('');
      r.append(hl, g, t);
      body.appendChild(r);
      rows.push({ el: r, hl, t, len: flat.length, ends: flat.trim() ? wordEnds(flat) : [0], no, focus: no >= focus[0] && no <= focus[1] });
    });
  });
  const caret = h('span', 'srb-caret');
  if (o.caret !== false) body.appendChild(caret);
  const padTop = Math.round(rowH * 0.4);
  const hgt = 60 + padTop + rows.length * rowH + Math.round(rowH * 0.55);
  el.style.width = width + 'px';
  el.style.height = hgt + 'px';
  // streaming schedule: one unit per word (empty rows are one short unit)
  const units = [];
  rows.forEach((r, ri) => r.ends.forEach((e) => units.push([ri, e])));
  const reveal = o.reveal || [0, 0.0001];
  const focusAt = o.focusAt == null ? reveal[1] : o.focusAt;
  const cues = [];
  const nTicks = Math.min(10, Math.max(3, Math.round((reveal[1] - reveal[0]) / 0.16)));
  for (let k = 0; k < nTicks; k++) cues.push({ t: reveal[0] + (k + 0.3) * (reveal[1] - reveal[0]) / nTicks, sfx: 'type', gain_db: -14 });

  function update(t) {
    const u = seg(t, reveal[0], reveal[1]);
    const k = Math.floor(u * units.length + 1e-6);
    const shown = new Array(rows.length).fill(0);
    let cur = -1;
    for (let q = 0; q < k && q < units.length; q++) { const [ri, e] = units[q]; shown[ri] = e; cur = ri; }
    if (k >= units.length) for (let ri = 0; ri < rows.length; ri++) shown[ri] = rows[ri].len;
    const fu = seg(t, focusAt, focusAt + 0.45, ease.outQuint);
    rows.forEach((r, ri) => {
      css(r.t, { width: `${shown[ri]}ch` });
      const vis = ri <= Math.max(cur, k >= units.length ? rows.length : cur);
      css(r.el, { opacity: vis ? '1' : '0' });
      cls(r.el, 'focus', r.focus && fu > 0);
      css(r.hl, { transform: `scaleX(${r.focus ? fu.toFixed(4) : 0})` });
    });
    const typing = u > 0 && u < 1;
    const blink = typing || Math.floor(t * 1.8) % 2 === 0;
    if (cur >= 0 && u < 1 && o.caret !== false) {
      css(caret, { display: 'block', opacity: blink ? '1' : '0',
        transform: `translate(calc(${gutW}px + ${shown[cur]}ch), ${padTop + cur * rowH}px)`, height: `${Math.round(rowH * 0.7)}px`,
        top: `${Math.round(rowH * 0.15)}px`, left: '0' });
    } else css(caret, { display: 'none' });
  }

  return {
    el, w: width, h: hgt, update, cues, rowH,
    rowTop: (i) => 60 + padTop + i * rowH,
    /** rect (block px) covering display rows of source lines [a,b] (defaults to the focus lines) */
    focusRect(a = focus[0], b = focus[1]) {
      let i0 = rows.findIndex((r) => r.no >= a);
      let i1 = rows.length - 1 - [...rows].reverse().findIndex((r) => r.no <= b);
      if (i0 < 0) i0 = 0;
      if (i1 < i0) i1 = Math.min(rows.length - 1, i0 + 5);
      return { x: 0, y: 60 + padTop + i0 * rowH, w: width, h: (i1 - i0 + 1) * rowH };
    },
    rows: rows.length,
  };
}

/** Flatten DIFF hunks to rows [{op, text, header}] */
export function diffRows(data) {
  const out = [];
  for (const hk of data.hunks || []) {
    if (hk.header) out.push({ op: '@', text: String(hk.header) });
    for (const ln of hk.lines || []) out.push({ op: String(ln[0] || ' ')[0], text: String(ln[1] ?? '') });
  }
  return out;
}

/**
 * DIFF panel. data = DIFF {path, lang, hunks:[{header, lines:[[op,text]]}], adds, dels, truncated}.
 * Adds sweep an accent highlighter left->right; deletions strike through in a neutral tone (one accent).
 * o: {width, fontSize, reveal:[t0,t1], wrap}
 */
export function diffBlock(data, o = {}) {
  const fs = o.fontSize || 26;
  const rowH = Math.round(fs * (o.lineHeight || 1.66));
  const width = o.width || 1300;
  const gutW = Math.round(fs * 1.9);
  const maxChars = Math.max(16, Math.floor((width - gutW - 28) / (fs * MONO_ADV)));
  const lang = data.lang || '';
  const src = diffRows(data);
  const el = h('div', 'srb-panel srb-diffpanel');
  const adds = Number(data.adds) || src.filter((r) => r.op === '+').length;
  const dels = Number(data.dels) || src.filter((r) => r.op === '-').length;
  const chipA = h('span', 'srb-chip add', { text: `+${adds}` });
  const chipD = h('span', 'srb-chip del', { text: `\u2212${dels}` });
  el.appendChild(pathBar(data.path, [chipA, chipD], ICONS.file, Math.floor((width - 320) / 13.2)));
  const body = h('div', 'srb-code');
  const padTop = Math.round(rowH * 0.35);
  body.style.cssText = `font-size:${fs}px;padding:${padTop}px 0 ${Math.round(rowH * 0.5)}px;`;
  el.appendChild(body);
  const rows = [];
  src.forEach((r, si) => {
    const toks = r.op === '@' ? [['', r.text]] : highlight(r.text, lang, data.path);
    const parts = o.wrap === false ? [toks] : wrapTokens(toks, r.op === '@' ? maxChars + 6 : maxChars);
    parts.forEach((pt, j) => {
      const kind = r.op === '+' ? 'add' : r.op === '-' ? 'del' : r.op === '@' ? 'hunk' : 'ctx';
      const row = h('div', `srb-row ${kind}${j > 0 ? ' cont' : ''}`);
      row.style.height = rowH + 'px';
      const hl = h('div', 'srb-hl');
      const g = h('span', 'srb-g', { text: j > 0 ? '\u21b5' : r.op === '+' ? '+' : r.op === '-' ? '\u2212' : '' });
      g.style.cssText = `width:${gutW}px;text-align:center;padding-right:0;`;
      const t = h('span', 'srb-t');
      tokenSpans(t, pt);
      const flat = pt.map((x) => x[1]).join('');
      const strike = h('span', 'srb-strike');
      if (kind === 'del') {
        const lead = flat.length - flat.trimStart().length;
        strike.style.cssText = `left:calc(${gutW}px + ${lead}ch);width:${Math.max(1, flat.trimEnd().length - lead)}ch;`;
      }
      row.append(hl, g, t);
      if (kind === 'del') row.appendChild(strike);
      body.appendChild(row);
      rows.push({ el: row, hl, t, strike, kind, len: flat.length, src: si });
    });
  });
  const hgt = 60 + padTop + rows.length * rowH + Math.round(rowH * 0.5);
  el.style.width = width + 'px';
  el.style.height = hgt + 'px';
  const reveal = o.reveal || [0, 0.0001];
  const n = rows.length;
  const step = n > 1 ? (reveal[1] - reveal[0]) / n : 0;
  const cues = [];
  rows.forEach((r, i) => { if (r.kind === 'add' && (i === 0 || rows[i - 1].kind !== 'add')) cues.push({ t: reveal[0] + i * step + 0.05, sfx: 'appear', gain_db: -14 }); });

  function update(t) {
    rows.forEach((r, i) => {
      const t0 = reveal[0] + i * step;
      const a = seg(t, t0, t0 + 0.32, ease.outQuint);
      if (r.kind === 'add') {
        const sw = seg(t, t0, t0 + 0.42, ease.outCubic);
        css(r.hl, { transform: `scaleX(${sw.toFixed(4)})` });
        css(r.t, { width: `${Math.ceil(r.len * clamp(sw * 1.08))}ch` });
        css(r.el, { opacity: a > 0 ? '1' : '0' });
      } else if (r.kind === 'del') {
        const st = seg(t, t0 + 0.12, t0 + 0.5, ease.outCubic);
        css(r.hl, { transform: 'scaleX(1)' });
        css(r.strike, { transform: `scaleX(${st.toFixed(4)})` });
        css(r.t, { width: `${r.len}ch` });
        css(r.el, { opacity: a.toFixed(3) });
      } else {
        css(r.hl, { transform: 'scaleX(1)' });
        css(r.t, { width: `${r.len}ch` });
        css(r.el, { opacity: (a * (r.kind === 'ctx' ? 0.92 : 1)).toFixed(3) });
      }
    });
    const c = seg(t, reveal[0] + 0.1, reveal[0] + 0.55, ease.outBackSoft);
    css(chipA, { transform: `scale(${(0.6 + 0.4 * c).toFixed(4)})`, opacity: clamp(c * 2).toFixed(3) });
    css(chipD, { transform: `scale(${(0.6 + 0.4 * c).toFixed(4)})`, opacity: clamp(c * 2).toFixed(3) });
  }

  // rect around the changed rows (the densest window of +/- rows)
  function changedRect(maxRows = 9) {
    const ch = rows.map((r) => (r.kind === 'add' || r.kind === 'del' ? 1 : 0));
    let best = -1, bi = 0;
    const win = Math.min(maxRows, rows.length);
    for (let s = 0; s + win <= rows.length; s++) {
      let c = 0;
      for (let q = s; q < s + win; q++) c += ch[q];
      if (c > best) { best = c; bi = s; }
    }
    // trim the window to its first/last changed row
    let a = bi, b = bi + win - 1;
    while (a < b && !ch[a]) a++;
    while (b > a && !ch[b]) b--;
    a = Math.max(0, a - 1); b = Math.min(rows.length - 1, b + 1);
    return { x: 0, y: 60 + padTop + a * rowH, w: width, h: (b - a + 1) * rowH };
  }

  return { el, w: width, h: hgt, update, cues, rowH, rows: n, changedRect, rowTop: (i) => 60 + padTop + i * rowH };
}
