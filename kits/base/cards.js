// Hype kits/base — paper cards: PROBLEM chat bubble, PLAN checklist, MONTAGE tool cards.

import { h, css, cls, ICONS, kindIcon, clock, fitSize } from './dom.js';
import { seg, ease, clamp, spring } from './motion.js';

/**
 * The user's prompt as a chat card; text types letter by letter (human input) with a caret.
 * Layout is fixed from frame 0 (the untyped tail is transparent) so lines never jump.
 * o: {width, maxLines, typeAt:[t0,t1], label}
 */
export function chatBlock(data, o = {}) {
  const width = o.width || 1300;
  const pad = 52;
  let text = String(data.text || '').trim();
  if (data.truncated && !/[.!?…]$/.test(text)) text += '\u2026';
  const fs = o.fontSize || fitSize(text, width - pad * 2, o.maxLines || 5, 50, 30, 0.47);
  const el = h('div', 'srb-card srb-chat');
  const head = h('div', 'srb-card-h');
  head.style.cssText = `padding:${pad - 8}px ${pad}px 0;gap:18px;`;
  const av = h('div', 'srb-avatar', { text: 'You' });
  av.style.cssText = 'width:64px;height:64px;font-size:23px;letter-spacing:0;text-transform:none;';
  head.append(av, h('span', '', { text: o.label || 'Prompt' }));
  const body = h('div', 'srb-prompt-text');
  body.style.cssText = `padding:28px ${pad}px ${pad}px;font-size:${fs}px;line-height:1.3;`;
  const shown = h('span', '');
  const caret = h('span', '');
  caret.style.cssText = `display:inline-block;width:${Math.round(fs * 0.09)}px;height:${Math.round(fs * 1.05)}px;margin:0 2px -${Math.round(fs * 0.18)}px;background:var(--sr-accent);border-radius:2px;`;
  const rest = h('span', '');
  rest.style.color = 'transparent';
  body.append(shown, caret, rest);
  el.append(head, body);
  el.style.width = width + 'px';
  const typeAt = o.typeAt || [0.3, 2.2];
  const cues = [];
  const nt = Math.min(14, Math.max(3, Math.round((typeAt[1] - typeAt[0]) / 0.11)));
  for (let k = 0; k < nt; k++) cues.push({ t: typeAt[0] + (k + 0.15) * (typeAt[1] - typeAt[0]) / nt, sfx: 'type', gain_db: -15 });
  // estimated height (for layout before measure): lines * lh
  const perLine = Math.max(1, Math.floor((width - pad * 2) / (fs * 0.47)));
  const estLines = Math.ceil(text.length / perLine);
  const estH = pad - 8 + 60 + 28 + estLines * fs * 1.3 + pad;
  function update(t) {
    const u = seg(t, typeAt[0], typeAt[1]);
    // human typing: slightly uneven cadence (deterministic wobble), word boundaries breathe
    const wob = u > 0 && u < 1 ? 0.012 * Math.sin(u * 47.0) : 0;
    const n = Math.round(clamp(u + wob) * text.length);
    if (shown.__n !== n) { shown.__n = n; shown.textContent = text.slice(0, n); rest.textContent = text.slice(n); }
    const blink = (u > 0 && u < 1) || Math.floor(t * 1.8) % 2 === 0;
    css(caret, { opacity: blink ? '1' : '0' });
  }
  return { el, w: width, h: estH, fs, update, cues, measure: () => el.offsetHeight || estH };
}

function statusOf(s) {
  const v = String(s || '').toLowerCase();
  if (/complete|done|finished|✓/.test(v)) return 'done';
  if (/progress|active|doing|current|running/.test(v)) return 'active';
  if (/cancel|skip|drop/.test(v)) return 'cancelled';
  return 'todo';
}

/**
 * Checklist card. data = PLAN {items:[{text,status}], more}. Done items tick in on a cadence,
 * the active item spins and gets a highlighter sweep. o: {width, rowH, startAt, tickEvery}
 */
export function planBlock(data, o = {}) {
  const width = o.width || 1100;
  const items = (data.items || []).slice(0, 6);
  const rowH = o.rowH || 92;
  const pad = 48;
  const el = h('div', 'srb-card srb-plan');
  const head = h('div', 'srb-card-h');
  head.style.cssText = `position:absolute;left:${pad}px;top:${pad - 6}px;right:${pad}px;`;
  const doneN = items.filter((it) => statusOf(it.status) === 'done').length;
  head.append(h('span', '', { html: ICONS.list }), h('span', '', { text: 'Plan' }), h('span', 'srb-sp'));
  const count = h('span', '', { text: `${doneN}/${items.length + (Number(data.more) || 0)}` });
  count.style.marginLeft = 'auto';
  head.appendChild(count);
  el.appendChild(head);
  const list = h('div', '');
  const top0 = pad + 56;
  list.style.cssText = `position:absolute;left:${pad}px;right:${pad}px;top:${top0}px;`;
  el.appendChild(list);
  const startAt = o.startAt ?? 0.15;
  const tickEvery = o.tickEvery ?? 0.42;
  const rows = items.map((it, i) => {
    const st = statusOf(it.status);
    const row = h('div', `srb-item ${st}`);
    row.style.cssText = `top:${i * rowH}px;height:${rowH}px;`;
    const box = h('span', 'srb-box');
    const chk = h('span', '', { html: ICONS.check });
    chk.style.cssText = 'position:absolute;inset:0;';
    if (st === 'done') box.appendChild(chk);
    const spin = h('span', 'srb-spin');
    if (st === 'active') box.appendChild(spin);
    const txtWrap = h('span', '');
    txtWrap.style.cssText = 'position:relative;min-width:0;';
    const sweep = h('span', 'srb-sweep');
    const txt = h('span', 'srb-itxt', { text: String(it.text || '') });
    txt.style.position = 'relative';
    if (st === 'cancelled') { txt.style.textDecoration = 'line-through'; txt.style.color = 'var(--sr-ink-3)'; }
    if (st === 'active') txtWrap.appendChild(sweep);
    txtWrap.appendChild(txt);
    row.append(box, txtWrap);
    list.appendChild(row);
    return { row, box, chk, spin, sweep, st };
  });
  const more = Number(data.more) || 0;
  let moreEl = null;
  if (more > 0) {
    moreEl = h('div', 'srb-card-h', { text: `+ ${more} more` });
    moreEl.style.cssText = `position:absolute;left:${pad + 62}px;top:${top0 + items.length * rowH + 8}px;`;
    el.appendChild(moreEl);
  }
  const hgt = top0 + items.length * rowH + (more ? 56 : 0) + pad - 12;
  el.style.width = width + 'px';
  el.style.height = hgt + 'px';
  const cues = [];
  let k = 0;
  const tickT = rows.map((r) => (r.st === 'done' ? startAt + 0.55 + tickEvery * k++ : null));
  const activeT = startAt + 0.55 + tickEvery * k;
  tickT.forEach((tt) => { if (tt != null) cues.push({ t: tt, sfx: 'appear', gain_db: -10 }); });
  function update(t) {
    rows.forEach((r, i) => {
      const e = seg(t, startAt + i * 0.08, startAt + i * 0.08 + 0.5, ease.outQuint);
      css(r.row, { opacity: clamp(e * 1.6).toFixed(3), transform: `translate(0, ${((1 - e) * 22).toFixed(2)}px)`,
        filter: e < 0.98 ? `blur(${((1 - e) * 5).toFixed(2)}px)` : 'none' });
      if (r.st === 'done') {
        const s = spring(t - tickT[i], 3.2);
        css(r.chk, { transform: `scale(${s.toFixed(4)})`, opacity: t >= tickT[i] ? '1' : '0' });
        css(r.box, { background: t >= tickT[i] ? 'var(--sr-accent)' : 'transparent',
          boxShadow: t >= tickT[i] ? 'none' : 'inset 0 0 0 2.5px var(--sr-rule)', transform: `scale(${(1 + 0.18 * Math.sin(Math.PI * clamp((t - tickT[i]) / 0.3))).toFixed(4)})` });
      }
      if (r.st === 'active') {
        css(r.spin, { transform: `rotate(${(t * 300) % 360}deg)` });
        css(r.sweep, { transform: `scaleX(${seg(t, activeT, activeT + 0.6, ease.outCubic).toFixed(4)})` });
      }
    });
    if (moreEl) css(moreEl, { opacity: seg(t, startAt + 0.5, startAt + 0.9).toFixed(3) });
    const doneNow = tickT.filter((x) => x != null && t >= x).length;
    if (count.__n !== doneNow) { count.__n = doneNow; count.textContent = `${doneNow}/${items.length + more}`; }
  }
  return { el, w: width, h: hgt, update, cues, rowH, top0 };
}

/** One MONTAGE tool card: {id, t, kind, tool, arg, clipped}. Returns {el, w, h}. */
export function toolCard(item, o = {}) {
  const w = o.width || 520, hh = o.height || 210;
  const el = h('div', 'srb-card srb-toolcard');
  el.style.cssText = `width:${w}px;height:${hh}px;padding:30px 34px;`;
  const top = h('div', 'srb-card-h');
  top.style.cssText = 'gap:14px;';
  const ic = h('span', '', { html: kindIcon(item.kind) });
  const tool = h('span', 'srb-tool', { text: String(item.tool || item.kind || '').replace(/_/g, ' ') });
  const when = h('span', 'srb-when', { text: clock(item.t) });
  when.style.marginLeft = 'auto';
  top.append(ic, tool, when);
  const arg = h('div', 'srb-arg', { text: String(item.arg || '') + (item.clipped ? '\u2026' : '') });
  arg.style.cssText = `margin-top:${Math.round(hh * 0.2)}px;`;
  el.append(top, arg);
  return { el, w, h: hh };
}
