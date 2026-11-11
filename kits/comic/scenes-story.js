// Hype kit "comic" — story pages: TITLE (cover), PROBLEM, PLAN, STATS, CALLOUT, END (back cover).

import { comicScene, snapIn } from './lib/page.js';
import { h, css, fitSize, visLen } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { countText, whoLabel } from '../base/type.js';
import { TITLE_DEF, STATS_DEF, CALLOUT_DEF, END_DEF } from '../base/scenes-titles.js';
import { C, agentSvg, userSvg, figure, skyline, burst, burstSvg, checkSvg, svgEl } from './lib/art.js';
import { caption, balloon, balloonSize, fitBalloon, sfx, masthead, headline, pop, slam } from './lib/letter.js';
import { heroBlock } from './lib/print.js';

const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o[k]).map((k) => [k, o[k]]));

/** Split a line into two balanced lines at a word boundary (for ribbons / mastheads). */
function twoLines(s) {
  const ws = String(s).split(/\s+/).filter(Boolean);
  if (ws.length < 2) return [s];
  let best = 1, bd = 1e9;
  for (let i = 1; i < ws.length; i++) {
    const d = Math.abs(ws.slice(0, i).join(' ').length - ws.slice(i).join(' ').length);
    if (d < bd) { bd = d; best = i; }
  }
  return [ws.slice(0, best).join(' '), ws.slice(best).join(' ')];
}

/** Bangers size so `text` (n chars) fits `width` on one line. */
const bangersFit = (text, width, max, min) => Math.round(clamp(width / (Math.max(3, String(text).length) * 0.6), min, max));

/** Masthead text + size: one line when it fits `width` at >= min px, else two balanced lines ("\n"; masthead breaks
 * there), else (one long word) smaller: a 40-character product name used to run ~2x off the 9:16 frame. */
function mastFit(text, width, max, min) {
  const one = width / (Math.max(3, visLen(text, 1.7)) * 0.6);     // CJK / emoji: ~1 em, Bangers caps ~0.6 em
  if (one >= min) return { text, size: Math.round(Math.min(max, one)), lines: 1 };
  let ls = twoLines(text);
  if (ls.length < 2 && visLen(text, 1.7) > String(text).length + 1) {     // CJK without spaces breaks anywhere
    const a = Array.from(String(text)), k = Math.ceil(a.length / 2);
    ls = [a.slice(0, k).join(''), a.slice(k).join('')];
  }
  const n = Math.max(...ls.map((x) => visLen(x, 1.7)));
  return { text: ls.join('\n'), size: Math.round(Math.min(max, width / (Math.max(3, n) * 0.6))), lines: ls.length };
}

// ------------------------------------------------------------------------------------- TITLE
comicScene('kit:comic/TITLE', {
  describe: 'Cover page: the title drops in letter by letter as a masthead over a turning sunburst and magenta halftone, the tagline ribbon wipes on, a NEW ISSUE burst slams, the agent hero stands over a code-tower skyline.',
  params: { ...pick(TITLE_DEF.params, ['title', 'tagline', 'product', 'one_liner', 'hero']),
    eyebrow: { type: 'string', default: 'Introducing', doc: 'strip under the masthead ("" hides it)' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe;
    const title = String(p.title || p.product || '').trim().toUpperCase();
    const tagline = String(p.tagline || '').trim();
    const cover = P.panel({ x: -20, y: -20, w: W + 40, h: H + 40 }, { bg: 'sun', rays: L ? [0.67, 0.48] : [0.6, 0.6], seed: 4, spin: 3 });
    cover.el.style.boxShadow = 'none';
    const sky = skyline(P.doc, W + 40, L ? 380 : 520, 9);
    sky.style.left = '-20px'; sky.style.top = `${H - (L ? 360 : 500)}px`;
    P.content.appendChild(sky);
    const hero = figure(agentSvg({ pose: 'hero' }), L ? 990 : 420, L ? 250 : 900, L ? 580 : 560);
    P.content.appendChild(hero);
    // corner box
    const cw = L ? 196 : 160, ch = L ? 244 : 218;
    const corner = h('div', 'cx-corner');
    corner.style.cssText = `left:${S.l}px;top:${S.t}px;width:${cw}px;height:${ch}px;`;
    const num = h('div', 'cx-num', { text: '1' });
    if (!L) num.style.fontSize = '96px';
    corner.append(h('div', 'cx-no', { text: 'No.' }), num, h('div', 'cx-price', { text: 'NEW!' }));
    P.content.appendChild(corner);
    // masthead
    const mx = L ? S.l + cw + 40 : S.l, my = L ? S.t - 4 : S.t + ch + 20;
    const mW = L ? W - mx - S.r - 300 : W - S.l - S.r;
    const mf = mastFit(title, mW, L ? 290 : 220, 96);
    const ms = mf.size;
    const mast = masthead(mf.text, { x: mx, y: my, size: ms, ls: Math.round(ms * 0.02) });
    P.content.appendChild(mast.el);
    let y = my + ms * 1.02 * mf.lines;
    let sub = null;
    if (p.eyebrow) {
      sub = h('div', 'cx-sub', { text: String(p.eyebrow) });
      sub.style.cssText = `left:${mx + 12}px;top:${y}px;`;
      P.content.appendChild(sub);
      y += 84;
    }
    // ribbon (tagline): one or two lines of Bangers on a red banner
    let ribbon = null;
    if (tagline) {
      // 16:9: a long title shrinks the masthead, which would lift the ribbon over the corner box (NEW! hidden)
      // (the ribbon is rotated -4deg: its rising right end must clear the NEW! sticker that hangs under the box)
      if (L) y = Math.max(y, S.t + ch + 44);
      const lines = tagline.length > 24 ? twoLines(tagline) : [tagline];
      const rW = L ? 980 : 840;
      const longest = Math.max(...lines.map((s) => s.length));
      const rs = Math.round(clamp(rW / (longest * 0.47), 64, L ? 112 : 96));
      ribbon = h('div', 'cx-ribbon');
      ribbon.style.cssText = `left:${L ? S.l - 24 : S.l - 20}px;top:${y + 18}px;font-size:${rs}px;padding:6px 46px 2px 40px;transform-origin:left center;` +
        'clip-path:polygon(0 0,100% 0,97% 50%,100% 100%,0 100%);';
      lines.forEach((s, i) => { if (i) ribbon.appendChild(h('br')); ribbon.append(s.toUpperCase()); });
      P.content.appendChild(ribbon);
      y += 18 + lines.length * rs * 1.04 + 40;
    }
    // blurb (one-liner) or a small printed hero
    let blurb = null, heroB = null;
    const one = String(p.one_liner || '').trim();
    if (p.hero && (p.hero.asset || p.hero.kind)) {
      heroB = heroBlock(ctx, p.hero, { width: L ? 640 : 560, maxH: L ? 380 : 400, t0: 0.9, portrait: !L });
      heroB.el.style.left = `${L ? S.l + 10 : S.l}px`;
      heroB.el.style.top = `${Math.min(y + 10, H - S.b - heroB.h)}px`;
      P.content.appendChild(heroB.el);
    } else if (one && one.toLowerCase() !== tagline.toLowerCase()) {
      blurb = h('div', 'cx-blurb', { text: one });
      const bw = L ? 640 : 520;
      blurb.style.cssText = `left:${L ? S.l - 30 : S.l}px;top:${Math.min(y + 10, H - S.b - 200)}px;width:${bw}px;font-size:${fitSize(one, bw - 56, 3, 46, 32, 0.48)}px;`;
      P.content.appendChild(blurb);
    }
    const bst = burst(P.doc, { w: L ? 330 : 280, h: L ? 290 : 250, spikes: 14, fill: 'yellow', seed: 6, shadow: 8, text: 'NEW\nISSUE!', size: L ? 58 : 50 });
    bst.el.style.left = `${L ? W - S.r - 290 : S.l - 10}px`;
    bst.el.style.top = `${L ? S.t - 50 : Math.round(y + (blurb || heroB ? 190 : 10))}px`;
    P.content.appendChild(bst.el);
    const cam = P.track([[0, [W / 2, H / 2, 1.06]], [ctx.dur + 0.5, [W / 2, H / 2 - 10, 1.0]]]);
    return {
      cues: [{ t: 0.1, sfx: 'appear', gain_db: -10 }, { t: 0.7, sfx: 'move', gain_db: -14 }, { t: 1.0, sfx: 'hit', gain_db: -4 }],
      render(t) {
        P.spinRays(t);
        snapIn(corner, t, 0.0, { rise: 0, from: 0.7 });
        mast.update(t, 0.1, Math.min(0.067, 0.6 / Math.max(1, title.length)));
        if (sub) snapIn(sub, t, 0.5, { rise: 0, from: 0.9, origin: '0 50%' });
        if (ribbon) {
          const u = seg(t, 0.62, 0.95, ease.outCubic);
          css(ribbon, { transform: 'rotate(-4deg)', clipPath: `polygon(0 0,${(u * 100).toFixed(1)}% 0,${(u * 97).toFixed(1)}% 50%,${(u * 100).toFixed(1)}% 100%,0 100%)` });
        }
        const s = slam(t, 1.0, { from: 1.7 });
        css(bst.el, { opacity: s.op.toFixed(3), transform: `translate(${s.dx}px,${s.dy}px) rotate(8deg) scale(${s.s.toFixed(4)})` });
        if (blurb) snapIn(blurb, t, 1.15, { rot: -2 });
        if (heroB) { heroB.update(t); snapIn(heroB.el, t, 0.85, { rot: -3 }); }
        const hu = seg(t, -0.2, 0.6, ease.outCubic);
        css(hero, { transform: `translate(0,${((1 - hu) * 120 + Math.sin(t * 1.6) * 4).toFixed(2)}px)` });
        P.camera(t, cam(t), { shakes: [1.0], amp: 8 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- PROBLEM
comicScene('kit:comic/PROBLEM', {
  describe: "The ask as a comic page: \"MEANWHILE, IN A HERMES SESSION...\" caption, the user's verbatim prompt pops in a speech balloon phrase by phrase, then the camera pulls back as the agent reads it and gets to work (TAK TAK!).",
  params: { text: { type: 'string', default: '', doc: 'verbatim prompt (redacted)' }, truncated: { type: 'bool', default: false, doc: 'adds an ellipsis' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, dur = ctx.dur;
    let text = String(p.text || '').trim();
    if (text.length > 260) text = text.slice(0, 258).replace(/\s+\S*$/, '') + '\u2026';
    else if (p.truncated && !/[.!?…]$/.test(text)) text += '\u2026';
    const R1 = L ? { x: 40, y: 40, w: 1230, h: 1000 } : { x: 40, y: 200, w: 1000, h: 900 };
    const R2 = L ? { x: 1296, y: 40, w: 584, h: 487 } : { x: 40, y: 1126, w: 1000, h: 754 };
    const R3 = L ? { x: 1296, y: 553, w: 584, h: 487 } : null;
    const p1 = P.panel(R1, { bg: 'cyan' });
    const cap = caption('Meanwhile, in a Hermes session\u2026', { x: 30, y: 30 });
    p1.el.appendChild(cap.el);
    const bustW = L ? 330 : 300;
    const user = figure(userSvg({ rim: 'magenta' }), 20, R1.h - bustW * 1.1 + 6, bustW);
    p1.el.appendChild(user);
    const bw = L ? 840 : 820, bh = L ? 640 : 560;
    const bx = L ? R1.w - bw - 36 : R1.w - bw - 30, by = L ? 120 : 110;
    const size = balloonSize(text, bw, bh, 42, 28);
    const bal = balloon(P.doc, p1.el, text, { x: bx, y: by, w: bw, h: bh, size, tail: [bustW * 0.62, R1.h - bustW * 0.95], tailW: 76, maxWords: 4 });
    // panel 2: the agent reads it
    const p2 = P.panel(R2, { bg: L ? 'magenta' : 'action', rays: [0.62, 0.55], seed: 7 });
    const cap2 = caption(L ? 'Hermes reads it\u2026' : '\u2026and Hermes gets to work!', { x: 26, y: 26, white: true });
    p2.el.appendChild(cap2.el);
    let agent2, tak = null;
    if (L) {
      agent2 = figure(agentSvg({ pose: 'bust', rim: 'yellow' }), R2.w - 330, R2.h - 300, 300);
      p2.el.appendChild(agent2);
      const q = burst(P.doc, { w: 150, h: 140, spikes: 11, fill: 'white', seed: 3, shadow: 6, text: '!', size: 84 });
      q.el.style.left = '120px'; q.el.style.top = '170px';
      p2.el.appendChild(q.el);
      agent2.__q = q;
    } else {
      agent2 = figure(agentSvg({ pose: 'type', rim: 'yellow' }), -20, R2.h - 470, 470);
      p2.el.appendChild(agent2);
      tak = sfx('TAK TAK TAK!', { x: 380, y: 300, size: 76, color: C.white, rot: -6, stroke: 9 });
      p2.el.appendChild(tak.el);
    }
    let p3 = null, tak3 = null;
    if (R3) {
      p3 = P.panel(R3, { bg: 'action', rays: [0.7, 0.6], seed: 5 });
      const cap3 = caption('\u2026and gets to work!', { x: 26, y: 26, white: true });
      p3.el.appendChild(cap3.el);
      p3.el.appendChild(figure(agentSvg({ pose: 'type', rim: 'yellow' }), -24, R3.h - 360, 360));
      tak3 = sfx('TAK TAK!', { x: 250, y: 300, size: 70, color: C.white, rot: -7, stroke: 9 });
      p3.el.appendChild(tak3.el);
      p3.cap = cap3;
    }
    const every = clamp((dur * 0.42) / Math.max(1, bal.phrases), 0.14, 0.32);
    const t0 = 0.25;
    const done = bal.doneAt(t0, every);
    const tP2 = Math.min(done + 0.25, dur - 1.3), tP3 = tP2 + 0.45;
    const brect = { x: R1.x, y: R1.y, w: R1.w, h: by + bh + 70 };
    const cam = P.track([[0, brect], [Math.max(0.6, tP2 - 0.35), brect], [tP2 + 0.35, 'page'], [dur + 1, [W / 2, H / 2 + 6, 1.02]]], 40, 1.5);
    const cues = [{ t: t0, sfx: 'appear', gain_db: -10 }];
    for (let i = 0; i < bal.phrases; i++) cues.push({ t: t0 + 0.12 + i * every, sfx: 'type', gain_db: -18 });
    cues.push({ t: tP2, sfx: 'move', gain_db: -14 });
    if (tak || tak3) cues.push({ t: (tak ? tP2 : tP3) + 0.3, sfx: 'hit', gain_db: -10 });
    return {
      cues,
      render(t) {
        P.spinRays(t);
        cap.update(t, 0.05);
        bal.update(t, t0, every);
        P.panelIn(p2, t, tP2, L ? 'left' : 'top');
        cap2.update(t, tP2 + 0.2);
        if (agent2.__q) { const s = slam(t, tP2 + 0.35); css(agent2.__q.el, { opacity: s.op.toFixed(3), transform: `rotate(-8deg) scale(${s.s.toFixed(4)})` }); }
        if (tak) tak.update(t, tP2 + 0.3);
        if (p3) { P.panelIn(p3, t, tP3, 'top'); p3.cap.update(t, tP3 + 0.2); tak3.update(t, tP3 + 0.3); }
        P.camera(t, cam(t));
      },
    };
  },
});

// ------------------------------------------------------------------------------------- PLAN
comicScene('kit:comic/PLAN', {
  describe: "The agent's plan as caption boxes stacked down a page: done items get a green check stamp with an ink splat on the beat, the active item gets a red marker ring and a NOW! burst, the hero points at the list.",
  params: { items: { type: 'array', default: [], doc: '[{text, status}] <= 6 (status: completed|in_progress|pending)' }, more: { type: 'int', default: 0, doc: 'hidden items count' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, dur = ctx.dur;
    const items = (p.items || []).slice(0, 6);
    const st = (s) => { const v = String(s || '').toLowerCase(); return /complete|done|finish/.test(v) ? 'done' : /progress|active|doing|current|running/.test(v) ? 'active' : 'todo'; };
    const R1 = L ? { x: 40, y: 40, w: 560, h: 1000 } : { x: 40, y: 200, w: 1000, h: 300 };
    const R2 = L ? { x: 626, y: 40, w: 1254, h: 1000 } : { x: 40, y: 526, w: 1000, h: 1354 };
    const p1 = P.panel(R1, { bg: 'action', rays: L ? [0.5, 0.62] : [0.78, 0.6], seed: 11 });
    const head = headline(String(p.label || 'The plan!').toUpperCase(), L ? { x: 40, y: 60, w: 480, size: 112 } : { x: 40, y: 40, w: 620, size: 104 });
    p1.el.appendChild(head.el);
    const hero = L ? figure(agentSvg({ pose: 'point', rim: 'white', cape: 'blue' }), 6, 440, 470) : figure(agentSvg({ pose: 'bust', rim: 'white' }), 700, 40, 270);
    p1.el.appendChild(hero);
    const p2 = P.panel(R2, { bg: 'paper' });
    const n = Math.max(1, items.length);
    const rowH = L ? Math.min(128, (R2.h - 220) / n) : Math.min(164, (R2.h - 420) / n);
    const gap = L ? 26 : 30;
    const boxW = R2.w - (L ? 330 : 250);
    const fs = L ? 40 : 42;
    const top0 = L ? Math.round((R2.h - n * rowH - (n - 1) * gap) / 2) - (p.more ? 30 : 0) : Math.max(60, Math.round((R2.h - n * rowH - (n - 1) * gap - 330) / 2));
    const rows = items.map((it, i) => {
      const s = st(it.status);
      const el = h('div', `cx-item ${s}`);
      el.style.cssText = `left:${L ? 110 : 60}px;top:${top0 + i * (rowH + gap)}px;width:${boxW}px;height:${rowH}px;font-size:${fs}px;`;
      const no = h('span', 'cx-no', { text: String(i + 1).padStart(2, '0') });
      const box = h('span', 'cx-box');
      const txt = h('span', 'cx-txt', { text: String(it.text || '') });
      el.append(no, txt);
      el.appendChild(box);
      box.style.marginLeft = 'auto';
      let stamp = null;
      if (s === 'done') {
        stamp = h('div', 'cx-stamp');
        stamp.style.cssText = 'position:absolute;left:-44px;top:-48px;width:140px;height:140px;opacity:0;';
        stamp.appendChild(svgEl(P.doc, 140, 140, burstSvg({ w: 140, h: 140, spikes: 11, depth: 0.3, fill: 'white', seed: 17 + i, sw: 5, shadow: 6 })));
        const chk = h('div', '', { html: checkSvg('green', 15) });
        chk.style.cssText = 'position:absolute;left:30px;top:16px;width:92px;height:92px;';
        stamp.appendChild(chk);
        box.appendChild(stamp);
      }
      p2.el.appendChild(el);
      return { el, s, stamp, box };
    });
    let ring = null, nowB = null;
    const ai = rows.findIndex((r) => r.s === 'active');
    if (ai >= 0) {
      const r = rows[ai];
      const x = (L ? 110 : 60) - 24, y = top0 + ai * (rowH + gap) - 22, w = boxW + 48, hh = rowH + 44;
      ring = P.svg(w, hh, `<ellipse cx="${w / 2}" cy="${hh / 2}" rx="${w / 2 - 6}" ry="${hh / 2 - 6}" fill="none" stroke="${C.red}" stroke-width="9" pathLength="1" stroke-dasharray="1 1" transform="rotate(-1.2 ${w / 2} ${hh / 2})"/>`, { style: `position:absolute;left:${x}px;top:${y}px;z-index:26;` });
      p2.el.appendChild(ring);
      nowB = burst(P.doc, { w: 170, h: 130, spikes: 12, fill: 'red', seed: 21, shadow: 6, text: 'NOW!', size: 46, color: C.yellow });
      nowB.el.style.left = `${x + w + 6}px`; nowB.el.style.top = `${y + hh / 2 - 65}px`;
      p2.el.appendChild(nowB.el);
      void r;
    }
    let more = null;
    if (p.more) {
      more = caption(`+ ${p.more} more`, { x: L ? 110 : 60, y: top0 + n * (rowH + gap) + 4, white: true });
      p2.el.appendChild(more.el);
    }
    const doneN = rows.filter((r) => r.s === 'done').length;
    const total = items.length + (Number(p.more) || 0);
    const cnt = burst(P.doc, { w: L ? 360 : 330, h: L ? 230 : 210, spikes: 15, fill: 'white', seed: 31, shadow: 8, text: `${doneN} of ${total}\nDONE!`, size: L ? 54 : 48 });
    cnt.el.style.left = L ? '40px' : '640px';
    cnt.el.style.top = L ? `${R1.h - 270}px` : `${Math.min(R2.h - 240, top0 + n * (rowH + gap) + 50)}px`;
    (L ? p1 : p2).el.appendChild(cnt.el);
    const step = clamp((dur * 0.45) / n, 0.18, 0.36);
    const t0 = 0.3;
    const drop = rows.map((_, i) => t0 + i * step);
    let k = 0;
    const tick = rows.map((r, i) => (r.s === 'done' ? drop[i] + 0.25 + 0.05 * k++ : null));
    const tAct = ai >= 0 ? drop[ai] + 0.35 : null;
    const tCnt = Math.min(dur - 0.8, t0 + n * step + 0.35);
    const listRect = { x: R2.x + 60, y: R2.y + top0 - 30, w: R2.w - 60, h: n * (rowH + gap) + 60 };
    const topRect = { x: R2.x + 40, y: R2.y + top0 - 40, w: R2.w - 40, h: Math.min(n, 3) * (rowH + gap) + 60 };
    const cam = P.track(L ? [[0, topRect], [t0 + 2.2 * step, topRect], [tCnt - 0.1, listRect], [tCnt + 0.5, 'page'], [dur + 1, [W / 2, H / 2, 1.0]]]
      : [[0, [W / 2, H / 2 + 30, 1.05]], [tCnt - 0.2, [W / 2, R2.y + top0 + n * (rowH + gap) * 0.6, 1.1]], [tCnt + 0.5, 'page'], [dur + 1, 'page']], 30, 1.45);
    const cues = drop.map((tt) => ({ t: tt, sfx: 'appear', gain_db: -14 }));
    tick.forEach((tt) => { if (tt != null) cues.push({ t: tt, sfx: 'hit', gain_db: -12 }); });
    if (tAct != null) cues.push({ t: tAct, sfx: 'appear', gain_db: -8 });
    cues.push({ t: tCnt, sfx: 'hit', gain_db: -6 });
    return {
      cues,
      render(t) {
        P.spinRays(t);
        head.update(t, 0.05);
        const hu = seg(t, 0, 0.5, ease.outCubic);
        css(hero, { transform: `translate(${((1 - hu) * -60).toFixed(1)}px,0)` });
        rows.forEach((r, i) => {
          snapIn(r.el, t, drop[i], { rise: -40, from: 0.92, origin: '0 50%' });
          if (r.stamp) {
            const s = slam(t, tick[i], { from: 2.0 });
            css(r.stamp, { opacity: s.op.toFixed(3), transform: `translate(${s.dx}px,${s.dy}px) scale(${s.s.toFixed(4)}) rotate(-8deg)` });
          }
        });
        if (ring) {
          const u = seg(t, tAct, tAct + 0.4, ease.inOutCubic);
          css(ring.firstChild, { strokeDashoffset: (1 - u).toFixed(4) });
          const s = slam(t, tAct + 0.35);
          css(nowB.el, { opacity: s.op.toFixed(3), transform: `rotate(-10deg) scale(${s.s.toFixed(4)})` });
        }
        if (more) more.update(t, t0 + n * step);
        const s = slam(t, tCnt, { from: 1.8 });
        css(cnt.el, { opacity: s.op.toFixed(3), transform: `translate(${s.dx}px,${s.dy}px) rotate(-5deg) scale(${s.s.toFixed(4)})` });
        P.camera(t, cam(t), { shakes: [tCnt], amp: 7 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- STATS
comicScene('kit:comic/STATS', {
  describe: '"BY THE NUMBERS!" splash page: each real session number slams in its own burst on the beat and counts up, with a caption label; page shake on the drop.',
  params: { ...pick(STATS_DEF.params, ['stats']) },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, dur = ctx.dur;
    const stats = (p.stats || []).slice(0, 3);
    const n = Math.max(1, stats.length);
    const pn = P.panel({ x: 40, y: L ? 40 : 200, w: W - 80, h: L ? H - 80 : H - 240 }, { bg: 'splash', rays: [0.5, L ? 0.55 : 0.5], seed: 3, spin: 4 });
    const title = String(p.label || 'By the numbers!').toUpperCase();
    const head = headline(title, L ? { x: S.l - 40, y: S.t - 40, w: W - 2 * S.l, size: 96 } : { x: S.l - 40, y: 30, w: W - 2 * S.l, size: 84 });
    pn.el.appendChild(head.el);
    const fills = ['white', 'yellow', 'white'];
    const bw = L ? (n === 1 ? 820 : n === 2 ? 680 : 560) : (n === 1 ? 860 : 820);
    const bh = L ? (n === 1 ? 600 : n === 2 ? 520 : 450) : (n === 1 ? 620 : n === 2 ? 520 : 380);
    const items = stats.map((s, i) => {
      const fin = String(s.display ?? s.value ?? '');
      const ns = Math.round(clamp((bw * 0.62) / (Math.max(2, fin.length) * 0.5), 90, L ? (n === 1 ? 300 : 230) : (n === 3 ? 170 : 230)));
      const b = burst(P.doc, { w: bw, h: bh, spikes: 18 + i * 2, depth: 0.2, fill: fills[i], seed: 40 + i * 7, shadow: 12 });
      const num = h('div', 'cx-num', { text: fin });
      num.style.cssText = `position:absolute;left:0;right:0;top:${Math.round(bh * 0.5 - ns * 0.62)}px;text-align:center;font-size:${ns}px;color:${i === 1 ? C.red : C.yellow};`;
      b.el.appendChild(num);
      const lab = caption(String(s.label || s.key || ''), { x: 0, y: 0 });
      lab.el.style.fontSize = L ? '40px' : '36px';
      lab.el.style.zIndex = '28';
      let x, y;
      if (L) { x = (pn.w / n) * (i + 0.5) - bw / 2; y = (pn.h - bh) / 2 + 30 + (i % 2) * 24; }
      else { x = (pn.w - bw) / 2; y = 150 + i * (bh + (n === 3 ? 26 : 60)); }
      b.el.style.left = `${x}px`; b.el.style.top = `${y}px`;
      lab.el.style.left = `${x + bw / 2}px`; lab.el.style.top = `${y + bh - (L ? 70 : 54)}px`;
      pn.el.append(b.el, lab.el);
      return { b, num, lab, s, fin };
    });
    const t0 = 0.18, step = clamp((dur * 0.3) / n, 0.25, 0.42);
    const cues = items.map((_, i) => ({ t: t0 + i * step, sfx: i === 0 ? 'hit' : 'appear', gain_db: i === 0 ? -2 : -8 }));
    return {
      cues,
      render(t) {
        P.spinRays(t);
        head.update(t, 0.0, 0.07);
        items.forEach((it, i) => {
          const a = t0 + i * step;
          const s = slam(t, a, { from: 1.9, dur: 0.15 });
          css(it.b.el, { opacity: s.op.toFixed(3), transform: `translate(${s.dx}px,${s.dy}px) rotate(${(i % 2 ? 4 : -4)}deg) scale(${s.s.toFixed(4)})` });
          const cu = seg(t, a + 0.05, a + 0.9, ease.outExpo);
          const txt = countText(it.s.display, it.s.value, cu >= 0.999 ? 1 : cu);
          if (it.num.__t !== txt) { it.num.__t = txt; it.num.textContent = txt; }
          const lp = pop(t, a + 0.35, 0.2, 0.9);
          css(it.lab.el, { opacity: lp.op.toFixed(3), transform: `translateX(-50%) rotate(-2deg) scale(${lp.s.toFixed(4)})` });
        });
        const u = seg(t, 0, dur, ease.outCubic);
        P.camera(t, [W / 2, H / 2, lerp(1.06, 1.0, u)], { shakes: items.map((_, i) => t0 + i * step + 0.13), amp: 12 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- CALLOUT
comicScene('kit:comic/CALLOUT', {
  describe: 'One quotable line in a big speech balloon (a jagged shout balloon for exclamations or test results) from a small speaker silhouette; the balloon pops and the words land phrase by phrase, one stressed word in red.',
  params: { ...pick(CALLOUT_DEF.params, ['text', 'who', 'ref']) },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, dur = ctx.dur;
    const text = String(p.text || '').trim();
    const who = String(p.who || 'agent').toLowerCase();
    const shout = who === 'test' || /!\s*$/.test(text);
    const R = L ? { x: 40, y: 40, w: W - 80, h: H - 80 } : { x: 40, y: 200, w: W - 80, h: H - 240 };
    const pn = P.panel(R, { bg: shout ? 'action' : 'cyan', rays: [0.3, 0.8], seed: 13 });
    const fb = fitBalloon(text, L ? 1180 : 920, L ? 620 : 800, L ? 66 : 72, 36, L ? 420 : 820);
    const bw = fb.w, bh = fb.h;
    const bx = L ? Math.round(560 + (R.w - 560 - 60 - bw) / 2) : (R.w - bw) / 2;
    const by = L ? Math.round(Math.max(70, (R.h - 260 - bh) / 2)) : Math.round(Math.max(90, (R.h - 640 - bh) / 2 + 40));
    const spW = L ? 420 : 520;
    const spX = L ? 60 : 50, spY = R.h - spW * 1.1 + 10;
    const sp = who === 'user' ? figure(userSvg({ rim: 'magenta' }), spX, spY, spW)
      : figure(agentSvg({ pose: who === 'test' ? 'hero' : 'bust', rim: 'yellow', cape: 'red' }), spX, who === 'test' ? R.h - spW * 1.35 : spY, spW);
    pn.el.appendChild(sp);
    let shoutB = null;
    if (shout) {
      shoutB = burst(P.doc, { w: bw + 120, h: bh + 120, spikes: 26, depth: 0.12, fill: 'white', seed: 9, shadow: 12 });
      shoutB.el.style.left = `${bx - 60}px`; shoutB.el.style.top = `${by - 60}px`;
      pn.el.appendChild(shoutB.el);
    }
    const size = fb.size;
    const bal = balloon(P.doc, pn.el, text, { x: bx, y: by, w: bw, h: bh, size, tail: shout ? null : [spX + spW * 0.66, spY + spW * 0.18], tailW: 90, maxWords: 3 });
    if (shout) { bal.el.classList.add('shout'); }
    const attr = caption(`\u2014 ${whoLabel(who)}`, { x: L ? bx + bw - 330 : bx + bw - 300, y: by + bh + (L ? 26 : 40), white: true });
    attr.el.style.fontSize = L ? '32px' : '38px';
    pn.el.appendChild(attr.el);
    const every = clamp(1.4 / Math.max(1, bal.phrases), 0.16, 0.34);
    const t0 = 0.2;
    const doneAt = bal.doneAt(t0, every);
    const brect = { x: R.x + Math.min(bx, spX) - 30, y: R.y + by - 30, w: Math.max(bx + bw, spX + spW) - Math.min(bx, spX) + 60, h: Math.max(by + bh + 120, spY + spW * 0.6) - by + 30 };
    const cam = P.track([[0, [W / 2, H / 2, 1.0]], [Math.min(1.4, dur * 0.45), brect], [dur + 1, brect]], 30, 1.12);
    return {
      cues: [{ t: t0, sfx: 'appear', gain_db: -8 }, { t: doneAt + 0.3, sfx: 'appear', gain_db: -16 }],
      render(t) {
        P.spinRays(t);
        if (shoutB) { const s = slam(t, t0, { from: 1.4 }); css(shoutB.el, { opacity: s.op.toFixed(3), transform: `scale(${s.s.toFixed(4)})` }); }
        bal.update(t, t0, every);
        attr.update(t, doneAt + 0.3);
        const hu = seg(t, 0, 0.45, ease.outCubic);
        css(sp, { transform: `translate(0,${((1 - hu) * 80).toFixed(1)}px)` });
        P.camera(t, cam(t), { drift: 1.0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- END
comicScene('kit:comic/END', {
  describe: 'Back cover / thumbnail: big masthead title and tagline, a dashed TRY IT TODAY! coupon stamped on with the CTA command and repo URL, the "made with Hermes · Hype" credit; the hero stands on the right over a blue sunburst. Speedrun adds a PB burst.',
  params: { ...pick(END_DEF.params, ['title', 'cta', 'url', 'credit', 'tagline', 'pb_display']) },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe;
    const title = String(p.title || '').trim().toUpperCase();
    const pn = P.panel({ x: -20, y: -20, w: W + 40, h: H + 40 }, { bg: 'blue', rays: L ? [0.8, 0.55] : [0.5, 0.8], seed: 8, spin: 2.5 });
    pn.el.style.boxShadow = 'none';
    const hero = figure(agentSvg({ pose: 'hero', rim: 'yellow', cape: 'red' }), L ? 1350 : 300, L ? 300 : 1130, L ? 520 : 560);
    P.content.appendChild(hero);
    const colW = L ? 1160 : W - S.l - S.r;
    const x0 = S.l;
    let y = L ? S.t + 10 : S.t;
    let pb = null;
    if (p.pb_display) {
      pb = burst(P.doc, { w: L ? 460 : 400, h: L ? 290 : 260, spikes: 16, fill: 'yellow', seed: 51, shadow: 10, text: `PB!\n${p.pb_display}`, size: L ? 80 : 70 });
      pb.el.style.left = `${W - S.r - (L ? 430 : 370)}px`;
      pb.el.style.top = `${L ? S.t - 40 : S.t - 20}px`;
      P.content.appendChild(pb.el);
      if (!L) y += 220;
    }
    const mf = mastFit(title, L ? Math.min(colW, W - S.r - (pb ? 470 : 0) - x0) : colW, L ? 250 : 230, 96);
    const ms = mf.size;
    const mast = masthead(mf.text, { x: x0 - 12, y, size: ms, ls: Math.round(ms * 0.02) });
    P.content.appendChild(mast.el);
    y += ms * (mf.lines - 1) + ms * 1.1;
    let tag = null;
    if (p.tagline) {
      const ts = fitSize(p.tagline, colW - 80, 2, 42, 32, 0.5);
      tag = caption(String(p.tagline), { x: x0, y, white: true, wrap: true, maxW: colW - 40, size: ts });
      tag.el.style.textTransform = 'none';
      P.content.appendChild(tag.el);
      y += ts * (String(p.tagline).length * ts * 0.5 > colW - 80 ? 2.3 : 1.25) + 60;
    }
    // the back-cover coupon: dashed border, TRY IT TODAY!, the command and the URL
    let coupon = null;
    if (p.cta || p.url) {
      coupon = h('div', 'cx-coupon');
      const cs = p.cta ? clamp(Math.floor((colW - 160) / (String(p.cta).length + 3) / 0.62), 24, 40) : 30;
      coupon.style.cssText = `left:${x0}px;top:${y}px;max-width:${colW}px;`;
      coupon.appendChild(h('div', 'cx-ch', { text: 'Try it today!' }));
      if (p.cta) {
        const row = h('div', 'cx-cr');
        row.style.fontSize = `${cs}px`;
        const isCmd = /^[a-z0-9_.\/@~-]+(?:\s|$)/.test(String(p.cta).trim());   // words get no shell prompt
        row.append(...(isCmd ? [h('span', 'cx-p', { text: '$' })] : []), h('span', '', { text: String(p.cta) }));
        coupon.appendChild(row);
      }
      if (p.url) coupon.appendChild(h('div', 'cx-cu', { text: String(p.url).replace(/^https?:\/\//, '') }));
      P.content.appendChild(coupon);
      y += 90 + (p.cta ? cs * 1.9 : 0) + (p.url ? 56 : 0) + 50;
    }
    const credit = caption(String(p.credit || ''), { x: x0, y: F.caps || !L ? y : H - S.b - 52, white: true });
    credit.el.className = 'cx-credit';
    credit.el.style.left = `${x0}px`;
    credit.el.style.top = `${F.caps || !L ? y : H - S.b - 52}px`;
    P.content.appendChild(credit.el);
    if (!L) {
      // centre the text column in the space between the top (or the PB burst) and the hero's head
      const y0 = pb ? S.t + 220 : S.t, room = 1150 - (y + 50) ;
      const dy = Math.max(0, Math.round(room / 2));
      for (const e of [mast.el, tag && tag.el, coupon, credit.el]) if (e) e.style.top = `${parseFloat(e.style.top) + dy}px`;
      void y0;
    }
    const pillAt = 0.75;
    return {
      cues: [{ t: 0.05, sfx: 'appear', gain_db: -10 }, ...(coupon ? [{ t: pillAt, sfx: 'hit', gain_db: -5 }] : []),
        ...(pb ? [{ t: 0.15, sfx: 'pass', gain_db: -4 }] : [])],
      render(t) {
        P.spinRays(t);
        mast.update(t, 0.05, Math.min(0.06, 0.5 / Math.max(1, title.length)));
        if (tag) tag.update(t, 0.45);
        if (coupon) {
          const s = slam(t, pillAt, { from: 1.3 });
          css(coupon, { opacity: s.op.toFixed(3), transform: `translate(${s.dx}px,${s.dy}px) rotate(-1.5deg) scale(${s.s.toFixed(4)})`, transformOrigin: '30% 50%' });
        }
        css(credit.el, { opacity: seg(t, pillAt + 0.45, pillAt + 0.65).toFixed(3) });
        if (pb) { const s = slam(t, 0.15, { from: 1.8 }); css(pb.el, { opacity: s.op.toFixed(3), transform: `rotate(6deg) scale(${s.s.toFixed(4)})` }); }
        const hu = seg(t, -0.1, 0.6, ease.outCubic);
        css(hero, { transform: `translate(0,${((1 - hu) * 100 + Math.sin(t * 1.4) * 4).toFixed(2)}px)` });
        P.camera(t, [W / 2, H / 2, lerp(1.04, 1.0, seg(t, 0, 1.6, ease.outCubic))], { shakes: coupon ? [pillAt] : [], amp: 6, drift: 1.0 });
      },
    };
  },
});

export { svgEl };
