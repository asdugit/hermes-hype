// Showreel kit "type": overlay scenes (screen-space type above shots): title, lower third, CTA pill,
// end lockup, kinetic words, speedrun split timer. Theme-token driven like kits/base (p.theme).
// Every overlay enters with rise + blur (outQuint, 0.5 s) and exits faster (0.3 s) before its t1.

import { defineDomScene, centerBox } from '../base/scene.js';
import { h, css, fitSize, clock } from '../base/dom.js';
import { seg, ease, clamp } from '../base/motion.js';
import { kineticLine, kineticLetters, riseIn, ctaPill } from '../base/type.js';
import { sr } from '../base/kit.js';

const THEME = { theme: { type: 'string', default: 'base', doc: 'theme tokens (style name)' },
  accent: { type: 'string', default: '', doc: 'project accent #RRGGBB' } };

/** Overlay frame: transparent (no stage background), type layer only. */
function overlay(F) {
  F.bg.style.display = 'none';
  F.el.style.background = 'transparent';
  return F;
}
const outAt = (dur) => Math.max(0.6, dur - 0.32);
const SCRIM = { scrim: { type: 'number', default: 0.62, doc: 'darkening behind the type for legibility over bright picture (0 = none)' } };

/** Soft stage-coloured scrim behind the type (under F.cam). shape: 'center' | 'left' | 'bottom'. */
function scrimLayer(F, amount, shape = 'center') {
  if (!(amount > 0)) return { update() {} };
  const el = h('div', 'srb-abs');
  const a = amount.toFixed(2), b = (amount * 0.45).toFixed(2);
  const c = (x) => `rgb(var(--sr-scrim-rgb) / ${x})`;
  const g = shape === 'left' ? `linear-gradient(90deg, ${c(a)} 0%, ${c(a)} 40%, ${c(0)} 78%)`
    : shape === 'bottom' ? `linear-gradient(180deg, ${c(0)} 40%, ${c(a)} 78%)`
    : shape === 'top' ? `linear-gradient(180deg, ${c(a)} 0%, ${c(a)} 22%, ${c(0)} 52%)`
    : `radial-gradient(${F.portrait ? '90% 42%' : '62% 56%'} at 50% 50%, ${c(a)}, ${c(b)})`;
  el.style.cssText = `left:0;top:0;width:${F.W}px;height:${F.H}px;background:${g};`;
  F.el.insertBefore(el, F.cam);
  return { update(t, o) { css(el, { opacity: (seg(t, -0.05, 0.4, ease.outCubic) * (1 - seg(t, o, o + 0.3))).toFixed(3) }); } };
}

// ------------------------------------------------------------------------------------- title
/** Typewriter line: letters appear one by one behind a caret; the untyped rest keeps its layout (invisible). */
function typeLine(text, dur) {
  const el = h('div', 'srb-h1');
  const shown = h('span'), caret = h('span'), rest = h('span');
  rest.style.visibility = 'hidden';
  caret.textContent = '_';
  el.append(shown, caret, rest);
  const cps = Math.max(10, Math.min(22, text.length / Math.max(0.6, Math.min(1.6, dur * 0.4))));
  const o = outAt(dur);
  return { el, update(t) {
    const n = Math.max(0, Math.min(text.length, Math.floor((t - 0.12) * cps)));
    if (shown.textContent !== text.slice(0, n)) { shown.textContent = text.slice(0, n); rest.textContent = text.slice(n); }
    caret.style.opacity = (n < text.length || Math.floor(t * 2.2) % 2 === 0) && t < o ? '1' : '0';
    el.style.opacity = (1 - seg(t, o, o + 0.3)).toFixed(3);
  } };
}

defineDomScene('kit:type/title', {
  kind: 'type-title',
  describe: 'Kinetic title card over the picture: optional eyebrow, a big line (one emphasis word), optional sub line.',
  params: {
    ...THEME,
    text: { type: 'string', default: '', doc: 'main line (<= 7 words)' },
    sub: { type: 'string', default: '', doc: 'secondary line (<= 10 words)' },
    eyebrow: { type: 'string', default: '', doc: 'small mono caps line above' },
    align: { type: 'string', default: 'center', doc: 'center | left' },
    band: { type: 'string', default: '', doc: "'' = centred | top | bottom: the text sits in that band (the picture keeps the rest)" },
    emphasis: { type: 'any', default: 'auto', doc: "'auto' (last long word), word index, or -1 for none" },
    size: { type: 'int', default: 0, doc: 'font px at 1080p (0 = fit)' },
    reveal: { type: 'string', default: '', doc: "'' = kinetic rise | 'type' = typewriter: the main line types on letter by letter (~16/s) behind a caret (noir)" },
    ...SCRIM,
  },
  build(ctx, p, F) {
    overlay(F);
    const dur = ctx.dur, L = F.portrait;
    const left = p.align === 'left' && !L;
    const band = p.band === 'top' || p.band === 'bottom' ? p.band : '';
    const sc = scrimLayer(F, p.scrim, band || (left ? 'left' : 'center'));
    const box = centerBox(F, 0);
    if (band) {     // e.g. 9:16 Blender HOOK/TITLE: the device sits low, the words high (never on the device)
      const bh = Math.round(F.H * (L ? 0.3 : 0.34));
      css(box, { height: `${bh}px`, top: band === 'top' ? `${F.safe.t}px` : `${F.H - F.safe.b - bh}px` });
    }
    if (left) { box.style.alignItems = 'flex-start'; box.style.textAlign = 'left'; box.style.paddingLeft = `${F.safe.l}px`; }
    const maxW = L ? 840 : left ? 1100 : 1500;
    const fs = p.size || fitSize(p.text, maxW, 2, L ? 120 : 150, 64, 0.5);
    const eb = p.eyebrow ? h('div', 'srb-eyebrow', null, [h('i'), String(p.eyebrow)]) : null;
    if (eb) eb.style.fontSize = '26px';
    const line = p.reveal === 'type' ? typeLine(String(p.text || ''), dur)
      : kineticLine(String(p.text || ''), { className: 'srb-h1', emphasis: p.emphasis });
    line.el.style.cssText = `font-size:${fs}px;max-width:${maxW}px;letter-spacing:-0.04em;line-height:1.02;text-shadow:0 6px 40px rgba(0,0,0,.45);`;
    const sub = p.sub ? kineticLine(String(p.sub), { className: 'srb-h1 srb-soft', emphasis: -1 }) : null;
    if (sub) sub.el.style.cssText = `font-size:${Math.round(Math.max(40, fs * 0.38))}px;margin-top:${Math.round(fs * 0.3)}px;max-width:${maxW}px;`;
    if (eb) { eb.style.marginBottom = `${Math.round(fs * 0.3)}px`; box.appendChild(eb); }
    box.appendChild(line.el);
    if (sub) box.appendChild(sub.el);
    const o = outAt(dur);
    return {
      cues: [{ t: 0.05, sfx: 'appear', gain_db: -12 }],
      render(t) {
        sc.update(t, o);
        if (eb) riseIn(eb, t, 0, { out: o });
        line.update(t, 0.08, { out: o });
        if (sub) sub.update(t, 0.4, { out: o, stagger: 0.06 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- lower third
defineDomScene('kit:type/lower-third', {
  kind: 'type-lower',
  describe: 'Lower third: accent bar + name + one line, slides in at the bottom-left (bottom band on 9:16).',
  params: {
    ...THEME,
    title: { type: 'string', default: '', doc: 'name / label (<= 5 words)' },
    sub: { type: 'string', default: '', doc: 'detail line (<= 9 words)' },
  },
  build(ctx, p, F) {
    overlay(F);
    const dur = ctx.dur, L = F.portrait;
    const box = h('div', 'srb-abs');
    const bar = h('div', 'srb-rule');
    bar.style.cssText = 'position:absolute;left:0;top:6px;bottom:6px;width:6px;height:auto;transform-origin:50% 100%;';
    const t1 = h('div', 'srb-h1', { text: String(p.title || '') });
    t1.style.cssText = `font-size:${L ? 64 : 64}px;letter-spacing:-0.03em;text-shadow:0 4px 24px rgba(0,0,0,.5);`;
    const t2 = p.sub ? h('div', 'srb-label', { text: String(p.sub) }) : null;
    if (t2) t2.style.cssText = 'margin-top:14px;font-size:28px;text-transform:none;letter-spacing:.01em;color:var(--sr-fg-2);';
    const inner = h('div', '');
    inner.style.cssText = 'padding-left:34px;';
    inner.append(t1);
    if (t2) inner.append(t2);
    box.append(bar, inner);
    const bottom = L ? F.safe.b + 30 : F.safe.b + 40;
    box.style.cssText = `left:${F.safe.l}px;bottom:${bottom}px;`;
    const shade = h('div', 'srb-abs');
    shade.style.cssText = `left:0;right:0;bottom:0;height:${bottom + 300}px;background:linear-gradient(180deg,rgb(var(--sr-scrim-rgb) / 0),rgb(var(--sr-scrim-rgb) / .82) 62%);`;
    F.ov.append(shade, box);
    const o = outAt(dur);
    return {
      cues: [{ t: 0.05, sfx: 'appear', gain_db: -14 }],
      render(t) {
        css(bar, { transform: `scaleY(${(seg(t, 0, 0.4, ease.outQuint) * (1 - seg(t, o, o + 0.3))).toFixed(4)})` });
        riseIn(t1, t, 0.1, { out: o, rise: 22 });
        if (t2) riseIn(t2, t, 0.22, { out: o, rise: 16 });
        css(shade, { opacity: (seg(t, 0, 0.4) * (1 - seg(t, o, o + 0.3))).toFixed(3) });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- CTA
defineDomScene('kit:type/cta', {
  kind: 'type-cta',
  describe: 'Call-to-action pill: "$ command" (or a link) in mono with an accent caret, optional label above.',
  params: {
    ...THEME,
    text: { type: 'string', default: '', doc: 'command or URL' },
    label: { type: 'string', default: '', doc: 'small line above (e.g. "Try it")' },
    at: { type: 'string', default: 'bottom', doc: 'bottom | center' },
    ...SCRIM,
  },
  build(ctx, p, F) {
    overlay(F);
    const dur = ctx.dur, L = F.portrait;
    const sc = scrimLayer(F, p.scrim * 0.8, p.at === 'center' ? 'center' : 'bottom');
    const size = clamp(Math.floor(((L ? 840 : 1400) - 120) / (String(p.text).length + 3) / 0.6), 22, 36);
    const pill = ctaPill(String(p.text || ''), { size });
    const box = h('div', 'srb-abs');
    box.style.cssText = p.at === 'center' ? `left:0;right:0;top:${F.H / 2 - 60}px;display:flex;flex-direction:column;align-items:center;`
      : `left:0;right:0;bottom:${F.safe.b + (L ? 40 : 30)}px;display:flex;flex-direction:column;align-items:center;`;
    const lab = p.label ? h('div', 'srb-eyebrow', null, [h('i'), String(p.label)]) : null;
    if (lab) { lab.style.marginBottom = '22px'; lab.style.fontSize = '26px'; box.appendChild(lab); }
    box.appendChild(pill.el);
    F.ov.appendChild(box);
    const o = outAt(dur);
    return {
      cues: [{ t: 0.1, sfx: 'appear', gain_db: -10 }],
      render(t) {
        sc.update(t, o);
        pill.update(t);
        const u = seg(t, 0.05, 0.55, ease.outBackSoft);
        riseIn(pill.el, t, 0.05, { out: o, extra: `scale(${(0.9 + 0.1 * u).toFixed(4)})` });
        if (lab) riseIn(lab, t, 0, { out: o });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- end lockup
defineDomScene('kit:type/end-lockup', {
  kind: 'type-end',
  describe: 'End lockup overlay: product name, tagline, CTA pill, URL and the small credit line (thumbnail frame).',
  params: {
    ...THEME,
    title: { type: 'string', default: '', doc: 'product name' }, tagline: { type: 'string', default: '', doc: 'one line' },
    cta: { type: 'string', default: '', doc: 'command / link' }, url: { type: 'string', default: '', doc: 'URL' },
    credit: { type: 'string', default: 'made with Hermes \u00b7 Showreel', doc: 'credit line' },
    scrim: { type: 'number', default: 0.55, doc: 'darkening of the picture behind (0..1)' },
  },
  build(ctx, p, F) {
    overlay(F);
    const L = F.portrait;
    const scrim = h('div', 'srb-abs');
    scrim.style.cssText = `inset:0;background:radial-gradient(70% 60% at 50% 48%, rgb(var(--sr-scrim-rgb) / ${p.scrim}), rgb(var(--sr-scrim-rgb) / ${Math.min(1, p.scrim + 0.25)}));`;
    F.el.insertBefore(scrim, F.cam);
    const col = centerBox(F, L ? -60 : -30);
    const ts = Math.round(clamp((L ? 840 : 1400) / (Math.max(3, String(p.title).length) * 0.56), 90, L ? 190 : 200));
    const tl = kineticLetters(String(p.title || ''), { className: 'srb-display' });
    tl.el.style.cssText = `font-size:${ts}px;white-space:nowrap;`;
    col.appendChild(tl.el);
    const tg = p.tagline ? kineticLine(String(p.tagline), { className: 'srb-h1 srb-soft', emphasis: -1 }) : null;
    if (tg) { tg.el.style.cssText = `font-size:${fitSize(p.tagline, L ? 840 : 1300, 2, 60, 44, 0.5)}px;margin-top:${Math.round(ts * 0.2)}px;`; col.appendChild(tg.el); }
    const pill = p.cta ? ctaPill(String(p.cta), { size: clamp(Math.floor(((L ? 840 : 1400) - 120) / (String(p.cta).length + 3) / 0.6), 22, 34) }) : null;
    if (pill) { pill.el.style.marginTop = `${Math.round(ts * 0.38)}px`; col.appendChild(pill.el); }
    const url = p.url ? h('div', 'srb-urltext', { text: String(p.url).replace(/^https?:\/\//, '') }) : null;
    if (url) { url.style.marginTop = '36px'; col.appendChild(url); }
    const credit = h('div', 'srb-credit', { text: String(p.credit || '') });
    credit.style.cssText = `position:absolute;left:0;right:0;text-align:center;bottom:${L ? F.safe.b - 40 : F.safe.b - 20}px;`;
    F.ov.appendChild(credit);
    return {
      cues: pill ? [{ t: 0.8, sfx: 'appear', gain_db: -10 }] : [],
      render(t) {
        css(scrim, { opacity: seg(t, 0, 0.6, ease.outCubic).toFixed(3) });
        tl.update(t, 0.1);
        if (tg) tg.update(t, 0.45);
        if (pill) { pill.update(t); riseIn(pill.el, t, 0.75); }
        if (url) riseIn(url, t, 0.95);
        riseIn(credit, t, 1.1, { rise: 10 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- kinetic words
defineDomScene('kit:type/kinetic', {
  kind: 'type-kinetic',
  describe: 'Kinetic words: lines appear one at a time (each leaves before the next arrives); rise, blur or slam.',
  params: {
    ...THEME,
    lines: { type: 'array', default: [], doc: 'lines (<= 7 words each); or use text' },
    text: { type: 'string', default: '', doc: 'single line alternative to lines' },
    style: { type: 'string', default: 'rise', doc: 'rise | blur | slam' },
    emphasis: { type: 'any', default: 'auto', doc: "'auto', word index or -1" },
    align: { type: 'string', default: 'center', doc: 'center | left' },
    ...SCRIM,
  },
  build(ctx, p, F) {
    overlay(F);
    const dur = ctx.dur, L = F.portrait;
    const sc = scrimLayer(F, p.scrim, p.align === 'left' && !L ? 'left' : 'center');
    const lines = (p.lines && p.lines.length ? p.lines : [p.text]).map(String).filter(Boolean);
    const per = dur / Math.max(1, lines.length);
    const box = centerBox(F, 0);
    if (p.align === 'left' && !L) { box.style.alignItems = 'flex-start'; box.style.paddingLeft = `${F.safe.l}px`; box.style.textAlign = 'left'; }
    const items = lines.map((s, i) => {
      const k = kineticLine(s, { className: 'srb-h1', emphasis: p.emphasis });
      const fs = fitSize(s, L ? 840 : 1500, 2, L ? 110 : 132, 64, 0.5);
      k.el.style.cssText = `position:absolute;font-size:${fs}px;max-width:${L ? 840 : 1500}px;letter-spacing:-0.04em;text-shadow:0 6px 40px rgba(0,0,0,.45);`;
      box.appendChild(k.el);
      return { k, t0: i * per, t1: (i + 1) * per };
    });
    const style = String(p.style || 'rise');
    return {
      cues: items.map((it) => ({ t: it.t0 + 0.05, sfx: style === 'slam' ? 'hit' : 'appear', gain_db: style === 'slam' ? -8 : -14 })),
      render(t) {
        sc.update(t, outAt(dur));
        for (const it of items) {
          const last = it === items[items.length - 1];
          const o = last ? outAt(dur) : it.t1 - 0.3;
          const vis = t >= it.t0 - 0.05 && t < o + 0.35;
          css(it.k.el, { visibility: vis ? 'visible' : 'hidden' });
          if (!vis) continue;
          if (style === 'slam') {
            const u = seg(t, it.t0, it.t0 + 0.22, ease.outCubic);
            css(it.k.el, { transform: `scale(${(1.35 - 0.35 * u).toFixed(4)})`, opacity: clamp(u * 2 * (1 - seg(t, o, o + 0.3))).toFixed(3) });
            it.k.update(t, it.t0 - 1, {});
          } else {
            it.k.update(t, it.t0, { out: o, stagger: style === 'blur' ? 0.04 : 0.075, blur: style === 'blur' ? 14 : 6, rise: style === 'blur' ? 0.25 : 1 });
          }
        }
      },
    };
  },
});

// ------------------------------------------------------------------------------------- speedrun timer
defineDomScene('kit:type/speedrun-timer', {
  kind: 'type-timer',
  describe: 'Speedrun HUD (compact corner plate): live session clock (time-lapse of the real session) and the latest split, which swaps in at its film time.',
  params: {
    ...THEME,
    splits: { type: 'array', default: [], doc: '[{label, session_t, film_t}] film_t relative to this overlay' },
    total_s: { type: 'number', default: 0, doc: 'real session duration (final time)' },
    title: { type: 'string', default: '', doc: 'run name (product)' },
  },
  build(ctx, p, F) {
    overlay(F);
    const dur = ctx.dur, L = F.portrait;
    const splits = (p.splits || []).slice(0, 7);
    const hud = h('div', 'srb-abs');
    hud.style.cssText = L ? `left:${F.safe.l}px;top:${F.safe.t}px;` : `right:${F.safe.r}px;top:${F.safe.t}px;`;
    hud.style.cssText += 'padding:20px 26px 18px;border-radius:18px;background:rgba(10,11,13,.86);box-shadow:0 0 0 1px rgba(255,255,255,.1),0 24px 60px rgba(0,0,0,.5);min-width:340px;';
    const name = h('div', 'srb-eyebrow', null, [h('i'), String(p.title || 'Any%')]);
    name.style.fontSize = '24px';
    const timer = h('div', 'srb-timer', { text: '0:00' });
    timer.style.cssText = 'font-size:64px;font-weight:600;margin:10px 0 6px;letter-spacing:-0.02em;';
    const slot = h('div', '');
    slot.style.cssText = `position:relative;height:${splits.length ? 42 : 0}px;overflow:hidden;`;
    hud.append(name, timer, slot);
    const rows = splits.map((s) => {
      const r = h('div', '');
      r.style.cssText = 'position:absolute;left:0;right:0;top:0;display:flex;justify-content:space-between;gap:28px;font:500 27px/1.5 var(--sr-f-mono);color:#C9CDD3;white-space:nowrap;';
      const a = h('span', '', { text: String(s.label || '') });
      const b = h('span', '', { text: clock(s.session_t) });
      b.style.color = 'var(--sr-accent)';
      r.append(a, b);
      slot.appendChild(r);
      return { r, s };
    });
    F.ov.appendChild(hud);
    // session clock: piecewise linear through the splits (film_t -> session_t), so it is exact at each split
    const pts = [[0, 0], ...splits.map((s) => [Number(s.film_t) || 0, Number(s.session_t) || 0]), [dur, Number(p.total_s) || (splits.length ? Number(splits[splits.length - 1].session_t) : 0)]]
      .sort((x, y) => x[0] - y[0]);
    const sessionAt = (t) => {
      for (let i = 0; i < pts.length - 1; i++) {
        const [a0, b0] = pts[i], [a1, b1] = pts[i + 1];
        if (t <= a1) return b0 + (b1 - b0) * clamp((t - a0) / ((a1 - a0) || 1e-6));
      }
      return pts[pts.length - 1][1];
    };
    return {
      cues: [],
      render(t) {
        riseIn(hud, t, 0, { rise: 12 });
        const s = Math.max(0, sessionAt(t));
        const txt = clock(Math.floor(s));
        if (timer.__t !== txt) { timer.__t = txt; timer.textContent = txt; }
        // only the latest reached split shows; it rises in, the previous one leaves upward
        rows.forEach(({ r, s: sp }, i) => {
          const ft = Number(sp.film_t) || 0;
          const nx = i + 1 < rows.length ? Number(rows[i + 1].s.film_t) || 0 : Infinity;
          const u = seg(t, ft, ft + 0.35, ease.outQuint), v = seg(t, nx, nx + 0.3, ease.outCubic);
          css(r, { opacity: (t >= ft ? 1 - v : 0).toFixed(3), transform: `translate(0, ${((1 - u) * 42 - v * 42).toFixed(2)}px)` });
        });
      },
    };
  },
});

if (sr && typeof sr.defineKit === 'function') sr.defineKit('type', { kineticLine, kineticLetters, ctaPill, riseIn });
