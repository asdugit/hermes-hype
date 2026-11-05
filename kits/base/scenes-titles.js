// Showreel kits/base — type-led scenes: TITLE, STATS, CALLOUT, END.

import { defineDomScene, flatCam, place, centerBox } from './scene.js';
import { h, css, fitSize } from './dom.js';
import { seg, ease, lerp, clamp } from './motion.js';
import { kineticLine, kineticLetters, riseIn, statsBlock, ctaPill, whoLabel } from './type.js';
import { COMMON, panelIn } from './scenes-panels.js';
import { contentBlock } from './scenes-media.js';

/** Display size for a title so it fits maxW on one line (Geist 600, tight tracking). */
export function titleSize(text, maxW, max = 220, min = 96) {
  return Math.round(clamp(maxW / (Math.max(3, String(text).length) * 0.56), min, max));
}

// ------------------------------------------------------------------------------------- TITLE
export const TITLE_DEF = {
  describe: 'Name + thesis: eyebrow, huge kinetic title, tagline with one emphasis word; optional product hero beside it.',
  params: {
    ...COMMON,
    title: { type: 'string', default: '', doc: 'product / film title' }, tagline: { type: 'string', default: '', doc: '<= 10 words' },
    product: { type: 'string', default: '', doc: 'product name (used when title is empty)' }, one_liner: { type: 'string', default: '', doc: 'unused on screen (VO material)' },
    eyebrow: { type: 'string', default: 'Introducing', doc: 'small mono line above the title ("" hides it)' },
    hero: { type: 'content', default: null, doc: 'optional product visual {kind:image|terminal|code|diff, ...}' },
  },
  build(ctx, p, F) {
    const L = F.portrait;
    const title = String(p.title || p.product || '').trim();
    const tagline = String(p.tagline || '').trim();
    const heroElsewhere = !!p._hero_elsewhere;
    const hasHero = heroElsewhere || !!(p.hero && (p.hero.asset || p.hero.kind));
    const centered = L || !hasHero;
    const maxW = L ? 860 : hasHero ? 860 : 1500;
    const ts = titleSize(title, maxW, L ? 200 : 220, L ? 90 : 110);
    const box = h('div', 'srb-abs');
    const eb = p.eyebrow ? h('div', 'srb-eyebrow', null, [h('i'), String(p.eyebrow)]) : null;
    const tl = kineticLetters(title, { className: 'srb-display' });
    tl.el.style.cssText = `font-size:${ts}px;white-space:nowrap;margin-top:${eb ? 40 : 0}px;`;
    const tgs = fitSize(tagline, maxW, 2, L ? 64 : 72, 52, 0.5);
    const tg = tagline ? kineticLine(tagline, { className: 'srb-h1', emphasis: 'auto' }) : null;
    if (tg) tg.el.style.cssText = `font-size:${tgs}px;margin-top:${Math.round(ts * 0.26)}px;max-width:${maxW}px;`;
    const rule = h('div', 'srb-rule');
    rule.style.cssText = `width:${Math.min(maxW, 220)}px;margin-top:${Math.round(ts * 0.2)}px;`;
    if (eb) box.appendChild(eb);
    box.append(tl.el);
    if (tg) box.appendChild(tg.el);
    box.appendChild(rule);
    if (centered) {
      box.style.cssText = `left:0;right:0;text-align:center;display:flex;flex-direction:column;align-items:center;top:${L ? (hasHero ? 330 : 700) : 330}px;`;
      if (tg) tg.el.style.textAlign = 'center';
    } else {
      box.style.cssText = `left:${F.safe.l + 20}px;top:${F.H / 2 - ts * 0.9 - 60}px;width:${maxW}px;`;
    }
    F.cam.appendChild(box);
    let hero = null;
    if (hasHero && !heroElsewhere) {
      const hw = L ? 900 : 900;
      hero = contentBlock(ctx, p.hero, { width: hw, maxH: L ? 760 : 700, fast: true, t0: 0 });
      const hx = L ? (F.W - hw) / 2 : F.W - F.safe.r - hw + 40;
      const hy = L ? 1020 : (F.H - hero.h) / 2;
      place(hero.el, hx, hy);
      F.cam.appendChild(hero.el);
    }
    const cues = [{ t: 0.55, sfx: 'appear', gain_db: -12 }];
    return {
      cues,
      render(t) {
        if (eb) riseIn(eb, t, 0.0);
        tl.update(t, 0.08);
        if (tg) tg.update(t, 0.42, { stagger: 0.075, emDelay: 0.16 });
        css(rule, { transform: `scaleX(${seg(t, 0.85, 1.45, ease.outQuint).toFixed(4)})` });
        if (hero) {
          hero.update(t);
          const u = panelIn(hero.el, t, -0.1, 1.0, { tilt: 18, rise: 70 });
          if (!L) css(hero.el, { transform: `perspective(2000px) translate3d(${((1 - u) * 60).toFixed(2)}px,0,0) rotateY(${(-16 + (1 - u) * -10).toFixed(3)}deg) rotateX(${(4 + (1 - u) * 10).toFixed(3)}deg)` });
        }
        const u = seg(t, 0, ctx.dur, ease.outCubic);
        flatCam(F, t, F.W / 2, F.H / 2, lerp(1, 1.035, u), { lift: F.caps ? 40 : 0 });
      },
    };
  },
};
defineDomScene('kit:base/TITLE', TITLE_DEF);

// ------------------------------------------------------------------------------------- STATS
export const STATS_DEF = {
  describe: 'Real session numbers only: 1-3 big numerals count up on the drop, mono labels, accent rule under the hero number.',
  params: {
    ...COMMON,
    stats: { type: 'array', default: [], doc: '[{key, label, value, display}] 1-3, computed from the session (never invented)' },
  },
  build(ctx, p, F) {
    const L = F.portrait;
    const sb = statsBlock(p.stats || [], { portrait: L, landAt: 0.12 });
    const label = String(p.label || '').trim();
    const eb = label ? h('div', 'srb-eyebrow', null, [h('i'), label]) : null;
    const box = centerBox(F, eb ? 20 : 0);
    box.style.alignItems = L ? 'center' : 'center';
    const inner = h('div', '');
    inner.style.cssText = 'display:flex;flex-direction:column;align-items:flex-start;text-align:left;';
    if (eb) { eb.style.marginBottom = '70px'; inner.appendChild(eb); }
    sb.el.style.position = 'relative';
    inner.appendChild(sb.el);
    box.appendChild(inner);
    return {
      cues: sb.cues,
      render(t) {
        sb.update(t);
        if (eb) riseIn(eb, t, 0.05);
        const u = seg(t, 0, ctx.dur, ease.outCubic);
        flatCam(F, t, F.W / 2, F.H / 2, lerp(1.04, 1.0, u), { lift: F.caps ? 40 : 0 });
      },
    };
  },
};
defineDomScene('kit:base/STATS', STATS_DEF);

// ------------------------------------------------------------------------------------- CALLOUT
export const CALLOUT_DEF = {
  describe: 'One quotable line, verbatim: emphasis-font quote words rise, accent rule, mono attribution; near-still camera.',
  params: {
    ...COMMON,
    text: { type: 'string', default: '', doc: 'verbatim quote (<= 12 words ideal)' },
    who: { type: 'string', default: 'agent', doc: 'user | agent | test' }, ref: { type: 'string', default: '', doc: 'event id' },
  },
  build(ctx, p, F) {
    const L = F.portrait;
    const text = String(p.text || '').trim();
    const maxW = L ? 860 : 1380;
    const fs = fitSize(text, maxW, L ? 6 : 3, L ? 92 : 104, 54, 0.42);
    const box = h('div', 'srb-abs');
    const qm = h('div', 'srb-quote srb-qm'); // glyph drawn by ::before: decorative, not QA text
    qm.style.cssText = `font-size:${Math.round(fs * 2.2)}px;line-height:1;height:${Math.round(fs * 1.1)}px;overflow:hidden;margin-bottom:${Math.round(fs * 0.25)}px;`;
    const q = kineticLine(text, { className: 'srb-quote', emphasis: -1 });
    q.el.style.cssText = `font-size:${fs}px;max-width:${maxW}px;`;
    const rule = h('div', 'srb-rule');
    rule.style.cssText = `width:120px;margin-top:${Math.round(fs * 0.5)}px;`;
    const who = h('div', 'srb-who', { text: whoLabel(p.who) });
    who.style.marginTop = '28px';
    box.append(qm, q.el, rule, who);
    box.style.cssText = `position:relative;width:${maxW}px;display:flex;flex-direction:column;align-items:flex-start;text-align:left;`;
    centerBox(F, 0).appendChild(box);
    const nW = text.split(/\s+/).length;
    const stagger = clamp(1.2 / Math.max(1, nW), 0.05, 0.09);
    return {
      cues: [],
      render(t) {
        riseIn(qm, t, 0.0, { rise: 20 });
        q.update(t, 0.12, { stagger, dur: 0.6, blur: 8 });
        css(rule, { transform: `scaleX(${seg(t, 0.3 + nW * stagger, 0.9 + nW * stagger, ease.outQuint).toFixed(4)})` });
        riseIn(who, t, 0.45 + nW * stagger);
        flatCam(F, t, F.W / 2, F.H / 2, 1 + 0.02 * seg(t, 0, ctx.dur), { drift: 1.0, lift: F.caps ? 50 : 0 });
      },
    };
  },
};
defineDomScene('kit:base/CALLOUT', CALLOUT_DEF);

// ------------------------------------------------------------------------------------- END
export const END_DEF = {
  describe: 'End card (thumbnail frame): title lockup, CTA command pill, URL and the "made with Hermes · Showreel" credit; speedrun adds the PB time.',
  params: {
    ...COMMON,
    title: { type: 'string', default: '', doc: 'product name' }, cta: { type: 'string', default: '', doc: 'command or link to try it' },
    url: { type: 'string', default: '', doc: 'repo / site URL' }, credit: { type: 'string', default: 'made with Hermes \u00b7 Showreel', doc: 'small credit line' },
    tagline: { type: 'string', default: '', doc: 'optional line under the title' },
    pb_display: { type: 'string', default: '', doc: 'speedrun final time (shown as PB)' },
  },
  build(ctx, p, F) {
    const L = F.portrait;
    const title = String(p.title || '').trim();
    const ts = titleSize(title, L ? 860 : 1400, L ? 190 : 200, 90);
    const col = centerBox(F, L ? -60 : -30);
    let pb = null;
    if (p.pb_display) {
      pb = h('div', '');
      pb.style.cssText = 'display:flex;flex-direction:column;align-items:center;margin-bottom:56px;';
      const pl = h('div', 'srb-eyebrow', null, [h('i'), 'Final time \u00b7 PB']);
      const pn = h('div', 'srb-num', { text: String(p.pb_display) });
      pn.style.cssText = `font-size:${L ? 150 : 140}px;margin-top:40px;font-family:var(--sr-f-mono);letter-spacing:-0.04em;`;
      pb.append(pl, pn);
      col.appendChild(pb);
    }
    const tl = kineticLetters(title, { className: 'srb-display' });
    tl.el.style.cssText = `font-size:${ts}px;white-space:nowrap;`;
    col.appendChild(tl.el);
    let tg = null;
    if (p.tagline) {
      tg = kineticLine(String(p.tagline), { className: 'srb-h1 srb-soft', emphasis: -1 });
      tg.el.style.cssText = `font-size:${fitSize(p.tagline, L ? 860 : 1300, 2, 60, 44, 0.5)}px;margin-top:${Math.round(ts * 0.2)}px;max-width:${L ? 860 : 1300}px;`;
      col.appendChild(tg.el);
    }
    let pill = null;
    if (p.cta) {
      const cs = clamp(Math.floor(((L ? 840 : 1400) - 120) / (String(p.cta).length + 3) / 0.6), 22, 34);
      pill = ctaPill(String(p.cta), { size: cs });
      pill.el.style.marginTop = `${Math.round(ts * 0.38)}px`;
      col.appendChild(pill.el);
    }
    let url = null;
    if (p.url) {
      url = h('div', 'srb-urltext', { text: String(p.url).replace(/^https?:\/\//, '') });
      url.style.marginTop = '36px';
      col.appendChild(url);
    }
    const credit = h('div', 'srb-credit', { text: String(p.credit || '') });
    credit.style.cssText = `position:absolute;left:0;right:0;text-align:center;bottom:${L ? F.safe.b - 40 : F.safe.b - 20}px;`;
    F.ov.appendChild(credit);
    const pillAt = 0.75;
    return {
      cues: [...(pill ? [{ t: pillAt + 0.05, sfx: 'appear', gain_db: -10 }] : []), ...(pb ? [{ t: 0.1, sfx: 'pass', gain_db: -6 }] : [])],
      render(t) {
        if (pb) riseIn(pb, t, 0.0, { rise: 30 });
        tl.update(t, pb ? 0.25 : 0.05);
        if (tg) tg.update(t, 0.45);
        if (pill) { pill.update(t); const u = seg(t, pillAt, pillAt + 0.5, ease.outBackSoft); riseIn(pill.el, t, pillAt, { extra: `scale(${(0.9 + 0.1 * u).toFixed(4)})` }); }
        if (url) riseIn(url, t, pillAt + 0.2);
        riseIn(credit, t, pillAt + 0.4, { rise: 10 });
        flatCam(F, t, F.W / 2, F.H / 2, lerp(1.03, 1.0, seg(t, 0, 1.6, ease.outCubic)), { drift: 1.2, lift: F.caps ? 40 : 0 });
      },
    };
  },
};
defineDomScene('kit:base/END', END_DEF);

export { panelIn };
