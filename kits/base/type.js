// Hype kits/base — stage typography blocks: kinetic lines, count-up numerals, quotes, CTA pill.
// Shared by base scenes, style kits and the type overlay kit.

import { h, css, words, pickEmphasis, ICONS } from './dom.js';
import { seg, ease, clamp, entrance, exitAt } from './motion.js';

/**
 * A kinetic line of masked words. emphasis: word index (-1 none, 'auto' = pickEmphasis).
 * update(t, t0, {stagger, dur, rise, blur, out}) — words rise + unblur with outQuint, per-word stagger
 * 60-90 ms (render-tech C2); `out` = exit time (faster, 0.3 s).
 */
export function kineticLine(text, { emphasis = -1, className = 'srb-h1', tag = 'div' } = {}) {
  const el = h(tag, className);
  const em = emphasis === 'auto' ? pickEmphasis(text) : emphasis;
  const ws = words(el, text, { emphasis: em });
  function update(t, t0, o = {}) {
    const stagger = o.stagger ?? 0.075, dur = o.dur ?? 0.55, rise = o.rise ?? 1.0, blur = o.blur ?? 6;
    ws.forEach((w, i) => {
      const extra = w.i === em ? (o.emDelay ?? 0.12) : 0;
      const st = entrance(t, t0 + i * stagger + extra, dur, 1, blur);
      const ex = o.out != null ? exitAt(t, o.out + i * 0.03, 0.3) : { u: 0, op: 1, y: 0, blur: 0 };
      const y = st.y * 100 * rise + ex.y * 4; // % of the word box: words rise out of their mask
      const b = st.blur + ex.blur;
      css(w.inner, { transform: `translate(0, ${y.toFixed(2)}%)`, opacity: (st.op * ex.op).toFixed(3),
        filter: b > 0.05 ? `blur(${b.toFixed(2)}px)` : 'none' });
    });
  }
  return { el, update, words: ws, emphasis: em };
}

/** Per-letter kinetic display word (titles): letters rise with a 30-40 ms stagger. */
export function kineticLetters(text, { className = 'srb-display' } = {}) {
  const el = h('div', className);
  const letters = [];
  for (const ch of Array.from(String(text))) {
    if (ch === ' ') { el.append(' '); continue; }
    if (ch === '\n') { el.appendChild(h('br')); continue; }     // a two-line title (titleFit)
    const m = h('span', 'srb-mask');
    const inner = h('span', 'srb-wi', { text: ch });
    m.appendChild(inner);
    el.appendChild(m);
    letters.push(inner);
  }
  function update(t, t0, o = {}) {
    const stagger = o.stagger ?? Math.min(0.035, 0.5 / Math.max(1, letters.length));
    letters.forEach((inner, i) => {
      const st = entrance(t, t0 + i * stagger, o.dur ?? 0.6, 1, o.blur ?? 8);
      const ex = o.out != null ? exitAt(t, o.out, 0.3) : { op: 1, y: 0, blur: 0 };
      css(inner, { transform: `translate(0, ${(st.y * 105).toFixed(2)}%)`, opacity: (st.op * ex.op).toFixed(3),
        filter: st.blur + ex.blur > 0.05 ? `blur(${(st.blur + ex.blur).toFixed(2)}px)` : 'none' });
    });
  }
  return { el, update };
}

/** Generic rise-in for a whole element (eyebrows, labels, pills). */
export function riseIn(el, t, t0, o = {}) {
  const st = entrance(t, t0, o.dur ?? 0.5, o.rise ?? 18, o.blur ?? 6);
  const ex = o.out != null ? exitAt(t, o.out, 0.3) : { op: 1, y: 0, blur: 0 };
  const b = st.blur + ex.blur;
  css(el, { opacity: (st.op * ex.op).toFixed(3), transform: `translate(0, ${(st.y + ex.y).toFixed(2)}px) ${o.extra || ''}`,
    filter: b > 0.05 ? `blur(${b.toFixed(2)}px)` : 'none' });
  return st.u;
}

/** Format a count-up value like the final display string ("1,234", "47 min", "1 h 05 min", "31.9"). */
export function countText(display, value, u) {
  const disp = String(display ?? value ?? '');
  const hm = /^(\d+) h (\d+) min$/.exec(disp);
  if (hm) {
    const total = (Number(hm[1]) * 60 + Number(hm[2])) * u;
    const m = Math.round(total);
    return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`;
  }
  const m = /^([^0-9]*)([0-9][0-9,]*(\.[0-9]+)?)(.*)$/.exec(disp);
  if (!m) return disp;
  const raw = m[2].replace(/,/g, '');
  const dec = (m[3] || '').length ? m[3].length - 1 : 0;
  const target = Number(raw);
  const v = target * u;
  let s = dec ? v.toFixed(dec) : String(Math.round(v));
  if (m[2].includes(',')) s = Number(s).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  return m[1] + s + m[4];
}

/**
 * Count-up progress for a stat so every frame reads as a real number: small targets (< 20) don't count at all
 * (they punch in at their final value), larger ones count from the first value with the same digit count
 * ("100 -> 516", never "1"), quantised to 15 Hz so digits never strobe. Returns the display string.
 */
export function countFrame(display, value, t, t0, dur = 0.7) {
  const disp = String(display ?? value ?? '');
  const m = /^([^0-9]*)([0-9][0-9,]*(\.[0-9]+)?)(.*)$/.exec(disp);
  const hm = /^(\d+) h (\d+) min$/.exec(disp);
  if (!m && !hm) return disp;
  const target = hm ? Number(hm[1]) * 60 + Number(hm[2]) : Number(m[2].replace(/,/g, ''));
  if (!(target >= 20)) return disp;
  const tq = Math.floor((t - t0) * 15) / 15;            // 15 Hz steps
  const u = clamp(tq / dur);
  if (u >= 1) return disp;
  const digits = String(Math.floor(target)).length;
  const lo = Math.pow(10, digits - 1);
  const frac = lo / target;                              // start where the digit count already matches
  return countText(disp, value, frac + (1 - frac) * ease.outCubic(u));
}

/**
 * STATS numerals: 1-3 {key,label,value,display}. Values count up (see countFrame: same digit count, 15 Hz,
 * small numbers punch in), labels rise, an accent rule draws under the hero number.
 * o: {portrait, size, landAt, gap}
 */
export function statsBlock(stats, o = {}) {
  const list = (stats || []).slice(0, 3);
  const el = h('div', 'srb-stats');
  const portrait = !!o.portrait;
  const n = Math.max(1, list.length);
  let size = o.size || (portrait ? (n === 1 ? 300 : n === 2 ? 230 : 196) : n === 1 ? 300 : n === 2 ? 250 : 210);
  const gap = o.gap ?? (portrait ? (n === 3 ? 56 : 90) : 120);
  if (o.maxW > 0) {
    // conservative width estimate of the final text (em), calibrated on the launch display face at 196 px
    // ("1 h 01 min" renders ~4.4 em): digits .6, letters .56, spaces .26, punctuation .3
    const em = (x) => [...String(x)].reduce((a, c) => a + (/\d/.test(c) ? 0.6 : /\s/.test(c) ? 0.26 : /[\w]/.test(c) ? 0.56 : 0.3), 0);
    const ems = list.map((x) => Math.max(em(x.display ?? x.value ?? ''), 1));
    const need = portrait ? Math.max(...ems) : ems.reduce((a, b) => a + b, 0);
    const room = portrait ? o.maxW : o.maxW - gap * (n - 1);
    if (need * size > room) size = Math.max(90, Math.floor(room / need));
  }
  el.style.cssText = `position:absolute;display:flex;${portrait ? 'flex-direction:column;align-items:flex-start;' : 'align-items:flex-end;'}gap:${gap}px;`;
  const items = list.map((s, i) => {
    const col = h('div', '');
    col.style.cssText = 'display:flex;flex-direction:column;align-items:flex-start;';
    const num = h('div', 'srb-num');
    num.style.fontSize = size + 'px';
    const rule = h('div', 'srb-rule');
    rule.style.cssText = `width:100%;margin-top:${Math.round(size * 0.12)}px;height:${Math.max(4, Math.round(size * 0.022))}px;`;
    const lab = h('div', 'srb-unit', { text: String(s.label || s.key || '') });
    lab.style.marginTop = `${Math.round(size * (i === 0 ? 0.1 : 0.22))}px`;
    col.append(num, ...(i === 0 ? [rule] : []), lab);
    el.appendChild(col);
    // reserve the final width so the row never re-flows while counting
    const fin = String(s.display ?? s.value ?? '');
    const ghost = h('div', '', { text: fin });
    ghost.style.cssText = 'height:0;overflow:hidden;visibility:hidden;';
    num.after(ghost);
    ghost.className = 'srb-num';
    ghost.style.fontSize = size + 'px';
    return { col, num, rule: i === 0 ? rule : null, lab, s };
  });
  const landAt = o.landAt ?? 0.15;
  const cues = [{ t: Math.max(0, landAt - 0.1), sfx: 'hit', gain_db: -2 }];
  items.forEach((it, i) => cues.push({ t: landAt + 0.25 + i * 0.18 + 0.85, sfx: 'appear', gain_db: -14 }));
  function update(t) {
    items.forEach((it, i) => {
      const t0 = landAt + i * 0.18;
      const st = entrance(t, t0, 0.55, 34, 10);
      const punch = 1 + 0.14 * (1 - seg(t, t0, t0 + 0.45, ease.outQuint));
      css(it.col, { opacity: st.op.toFixed(3), transform: `translate(0, ${st.y.toFixed(2)}px)`,
        filter: st.blur > 0.05 ? `blur(${st.blur.toFixed(2)}px)` : 'none' });
      css(it.num, { transform: `scale(${punch.toFixed(4)})`, transformOrigin: '0 85%' });
      const txt = countFrame(it.s.display, it.s.value, t, t0 + 0.05);
      if (it.num.__t !== txt) { it.num.__t = txt; it.num.textContent = txt; }
      if (it.rule) css(it.rule, { transform: `scaleX(${seg(t, t0 + 0.7, t0 + 1.3, ease.outQuint).toFixed(4)})` });
      riseIn(it.lab, t, t0 + 0.35, { rise: 14 });
    });
  }
  return { el, update, cues, size };
}

/** CTA pill: "$ <command>" in mono with an accent caret. */
export function ctaPill(cmd, o = {}) {
  const el = h('div', 'srb-pill');
  if (o.size) { el.style.fontSize = o.size + 'px'; el.style.height = Math.round(o.size * 2.6) + 'px'; }
  // a shell prompt only for a command ('npm start'), never for a URL or words ('Read the code on GitHub')
  const isCmd = o.prompt ?? (!/^https?:|^[\w.-]+\.[a-z]{2,}(\/|$)/i.test(String(cmd))
    && /^[a-z0-9_.\/@~-]+(?:\s|$)/.test(String(cmd).trim()));
  if (isCmd) el.appendChild(h('span', 'srb-prompt', { text: '$' }));
  el.appendChild(h('span', '', { text: String(cmd) }));
  const caret = h('span', 'srb-caret2');
  el.appendChild(caret);
  function update(t) { css(caret, { opacity: Math.floor(t * 1.8) % 2 === 0 ? '1' : '0.15' }); }
  return { el, update };
}

/** Attribution text for CALLOUT `who`. */
export function whoLabel(who) {
  return ({ user: 'You asked', agent: 'Hermes', test: 'Test run', hermes: 'Hermes' })[String(who || '').toLowerCase()] || String(who || '');
}

export { ICONS };
