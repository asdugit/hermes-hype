// Hype kit "ink" — story pages: TITLE (style frame A), PROBLEM, PLAN (style frame B / V), STATS, CALLOUT, END.

import { inkScene } from './lib/page.js';
import { h, css } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { countFrame } from '../base/type.js';
import { pickEmphasis } from '../base/dom.js';
import { TITLE_DEF, STATS_DEF, CALLOUT_DEF, END_DEF } from '../base/scenes-titles.js';
import { C, NOTE_COLORS, form, tube, stroke, arrow, loop, underline, sparkle, tick, drawOn, popIn, place, gpose,
  settleIn, writeOn, charSpans, typeTo, riseLetters, roughD, svgBox } from './lib/ink.js';
import { robot, person, setArm, blink, antenna, face } from './lib/cast.js';
import { note, bubble, luggageTag, filmStrip, lamp, desk, laptop, mugBooks } from './lib/props.js';
import { layer, text, clockOf, fitText, fitBox, linesAt, clip, CW } from './lib/scene.js';
import { rng } from '../base/motion.js';

const pick = (o, ks) => Object.fromEntries(ks.filter((k) => o[k]).map((k) => [k, o[k]]));
const deg = (r) => (r * 180) / Math.PI;

/** Angle (deg, outward from hanging down) for a right arm at shoulder s to point at target q. */
const aimR = (s, q) => deg(Math.atan2(q[0] - s[0], q[1] - s[1]));

/** Underline data URL (rough, seeded) used as a CSS background on an emphasis word (no measuring). */
function underlineUrl(key, color = C.terra) {
  const d = roughD(['path', 'M4,12 C40,6 90,16 130,9 S180,8 196,12'], key, { sw: 5, roughness: 1.3, bowing: 1 });
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 20' preserveAspectRatio='none'><path d='${d}' fill='none' stroke='${color}' stroke-width='5' stroke-linecap='round'/></svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
}

// ------------------------------------------------------------------------------------------------ TITLE
inkScene('kit:ink/TITLE', {
  describe: 'Title page (style frame A): the user at a laptop under a swinging lamp, the robot holds up the film strip as it unspools with scene pictograms; the title rises letter by letter in Fraunces, a terracotta brush underline draws on, an italic tagline and handwritten "you" / "your agent" notes.',
  params: { ...pick(TITLE_DEF.params, ['title', 'tagline', 'product', 'one_liner', 'hero']),
    eyebrow: { type: 'string', default: 'Introducing', doc: 'small kicker above the title ("" hides it)' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const title = String(p.title || p.product || '').trim() || 'Untitled';
    const tagline = clip(p.tagline || p.one_liner || '', 90);
    const g = L ? { s: 1, x: 0, y: 0 } : { s: 0.98, x: -66, y: 790 };
    const X = (x, y) => [x * g.s + g.x, y * g.s + g.y];
    const uid = `${P.uid}f`;
    const film = filmStrip([[650, 664], [705, 500], [792, 404], [930, 388], [1012, 470], [1062, 640], [1230, 764], [1520, 798], [2000, 800]], uid);
    const m = `<g transform="translate(${g.x},${g.y}) scale(${g.s})">` +
      `<g data-k="disc"><circle cx="625" cy="560" r="445" fill="${C.peach}"/><path d="M205,700 A445,445 0 0,0 1045,700 Z" fill="${C.peachD}" opacity=".55"/></g>` +
      `<ellipse cx="628" cy="992" rx="500" ry="20" fill="${C.shadow}"/>` +
      lamp(760, 150, 490, 'ti:lamp', 'lamp', L ? -200 : -40) +
      `<g data-k="wn1" transform="rotate(-7 300 290)">${form(['rect', 245, 236, 112, 112, 0], 'butter', 'ti:wn1')}` +
      tube('M262,270 L330,268 M262,294 L318,292 M262,318 L300,317', 'inkS', 4) + `<rect x="274" y="230" width="56" height="14" fill="#fff" opacity=".55"/></g>` +
      `<g data-k="wn2" transform="rotate(6 430 255)">${form(['rect', 384, 206, 96, 96, 0], 'npeach', 'ti:wn2')}${tick(431, 256, 60, 'ti:wn2t', { sw: 6 })}</g>` +
      form(['rect', 418, 452, 254, 270, 48], 'terraD', 'ti:chair') +
      `<g data-k="user"><g transform="translate(545,712)">${person('u', { variant: 'bust' }).markup}</g></g>` +
      film.markup +
      `<g data-k="lap">${laptop(545, 702, 'ti:lap')}</g>` +
      desk(166, 1084, 702, 242, 'ti:desk') + mugBooks(208, 702, 'ti:mug') +
      `<g data-k="bot"><g transform="translate(932,702)">${robot('r', { arms: { l: 24, r: 167 }, reach: 140 }).markup}</g></g>` +
      arrow([300, 520], [462, 436], 'ti:ay', { bend: -34, draw: 'ay' }) + (L ? arrow([1062, 884], [982, 724], 'ti:ab', { bend: -30, draw: 'ab' }) : '') +
      `<g data-k="spk">${sparkle(1104, 664, 15)}${sparkle(1300, 628, 10, 'terra')}${sparkle(1086, 360, 11, 'terra')}${sparkle(700, 300, 9)}${sparkle(440, 590, 13, 'teal')}</g>` +
      '</g>';
    const A = layer(P, m);
    const update = film.bind(A.el);
    // handwritten notes
    const hs = Math.round(46 * g.s);
    const [yx, yy] = X(206, 522), [ax, ay] = X(1072, 862);
    const you = text(P, 'ik-hand', 'you', yx, yy, `font-size:${hs}px;transform:rotate(-6deg);`);
    const agent = L ? text(P, 'ik-hand', 'your agent', ax, ay, `font-size:${hs}px;transform:rotate(-3deg);`) : null;
    // title block
    const bx = L ? 1128 : S.l - 24, bw = L ? W - 1128 - 96 : W - 2 * (S.l - 24);
    let y = L ? 236 : S.t + 10;
    let kicker = null;
    if (p.eyebrow) { kicker = text(P, 'ik-kicker', p.eyebrow, bx + 8, y); y += 44; }
    const ts = fitText(title, bw, 1, L ? 184 : 170, 92, CW.display);
    const lines2 = ts <= 92 && title.length * ts * CW.display > bw;
    const tsz = lines2 ? fitText(title, bw, 2, 140, 72, CW.display) : ts;
    const tEl = text(P, 'ik-title', '', bx, y, `font-size:${tsz}px;width:${bw}px;`);
    const letters = charSpans(tEl, title);
    const tH = tsz * 0.92 * (lines2 ? 2 : 1);
    y += tH + 26;
    const ulW = Math.min(bw - 20, Math.max(260, Math.min(title.length * tsz * CW.display, bw) * 0.95));
    const UL = svgBox(P.doc, bx, y - 18, ulW + 20, 40, underline(6, 20, ulW, 'ti:ul', { draw: 'ul' }));
    P.content.appendChild(UL.el);
    const ulPaths = UL.el.querySelectorAll('[data-d="ul"]');
    y += 50;
    let tag = null;
    if (tagline) {
      const tgs = fitText(tagline, bw - 10, 3, 50, 40, CW.serifIt);
      tag = text(P, 'ik-tagline', tagline, bx + 6, y, `font-size:${tgs}px;width:${bw - 10}px;`);
    }
    const lampEl = A.K.lamp[0], user = A.K.user[0], bot = A.K.bot[0], disc = A.K.disc[0];
    const cam = P.track([[0, [W / 2 + 12, H / 2 + 6, 1.045]], [D + 0.6, [W / 2, H / 2, 1.0]]]);
    const [lx, ly] = [760, -200];
    return {
      cues: [{ t: 0.05, sfx: 'appear', gain_db: -10 }, { t: T(0.3), sfx: 'move', gain_db: -14 }, { t: T(0.95), sfx: 'hit', gain_db: -8 }],
      render(t) {
        const sw = 11 * Math.exp(-2.6 * Math.max(0, t)) * Math.cos(t * 4.4) + 0.6 * Math.sin(t * 1.3);
        lampEl.setAttribute('transform', `rotate(${sw.toFixed(3)} ${lx} ${ly})`);
        const dp = popIn(t, -0.1, 0.5, 0.94);
        gpose(disc, { ox: 625, oy: 560, s: dp.s });
        const up = popIn(t, T(0.02), 0.32, 0.92);
        gpose(user, { ox: 545, oy: 712, s: up.s, y: (1 - up.s) * 120, op: up.op });
        const bp = popIn(t, T(0.14), 0.32, 0.92);
        gpose(bot, { ox: 932, oy: 702, s: bp.s, y: (1 - bp.s) * 120 + Math.sin(t * 2.2) * 1.5, op: bp.op });
        blink(A.K, 'r', t, 'happy', 0.7);
        const fr = seg(t, T(0.3), T(1.5), ease.outCubic);
        update(fr, Math.max(0, t - T(1.5)) * 88 * 1.6);
        if (kicker) writeOn(kicker, seg(t, T(0.3), T(0.6)));
        riseLetters(letters, t, T(0.42), { stagger: Math.min(0.03, 0.5 / letters.length) });
        drawOn(ulPaths, seg(t, T(0.95), T(1.4), ease.inOutCubic));
        if (tag) { const u = seg(t, T(1.1), T(1.5), ease.outCubic); css(tag, { opacity: u.toFixed(3), transform: `translate(0,${((1 - u) * 18).toFixed(2)}px)` }); }
        drawOn(A.D.ay, seg(t, T(1.4), T(1.75), ease.inOutCubic));
        writeOn(you, seg(t, T(1.6), T(1.85)));
        drawOn(A.D.ab, seg(t, T(1.6), T(1.95), ease.inOutCubic));
        if (agent) writeOn(agent, seg(t, T(1.85), T(2.25)));
        css(A.K.spk[0], { opacity: seg(t, T(1.3), T(1.7)).toFixed(3) });
        P.camera(t, cam(t));
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ PROBLEM
inkScene('kit:ink/PROBLEM', {
  describe: "The ask: the user's verbatim request types into a paper speech bubble letter by letter (human cadence), the robot reads along and its antenna lights up on the last word.",
  params: { text: { type: 'string', default: '', doc: 'verbatim prompt (redacted)' }, truncated: { type: 'bool', default: null, doc: 'adds an ellipsis' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    let msg = clip(p.text || '', 240);
    if (p.truncated && !/[.!?\u2026]$/.test(msg)) msg += '\u2026';
    const B = L ? { x: 600, y: 140, w: 1200, h: 640 } : { x: 70, y: 280, w: 940, h: 980 };
    const pad = L ? 64 : 58;
    const fs = fitBox(msg, B.w - 2 * pad, B.h - 2 * pad - 20, L ? 64 : 66, 36, CW.hand, 1.1);
    const need = Math.round(linesAt(msg, B.w - 2 * pad, fs, CW.hand) * fs * 1.12 + 2 * pad + 16);
    if (need < B.h) { const cy = L ? 440 : 760; B.h = Math.max(L ? 300 : 380, need); B.y = Math.max(L ? S.t + 50 : S.t + 60, Math.round(cy - B.h / 2)); }
    const us = L ? 1.1 : 1.12, uo = L ? [360, 1084] : [300, 1930];
    const head = [uo[0], uo[1] - 312 * us];
    const tip = L ? [head[0] + 150 - B.x, head[1] - 40 - B.y] : [head[0] + 30 - B.x, head[1] - 150 - B.y];
    const bub = bubble(P.doc, B.w, B.h, L ? 'left' : 'bottom', L ? 0.8 : 0.26, tip, { key: 'pb', bw: 90 });
    bub.el.style.left = `${B.x}px`; bub.el.style.top = `${B.y}px`;
    const ro = L ? [1690, 1010] : [850, 1890], rs = L ? 0.95 : 1.0;
    const m = `<circle cx="${L ? 360 : 300}" cy="${L ? 820 : 1640}" r="${L ? 330 : 360}" fill="${C.peach}"/>` +
      `<g data-k="user"><g transform="translate(${uo[0]},${uo[1]}) scale(${us})">${person('u', { variant: 'bust', look: 0.6 }).markup}</g></g>` +
      `<g data-k="bot"><g transform="translate(${ro[0]},${ro[1]}) scale(${rs})">${robot('r', { pose: 'think', face: 'focus' }).markup}</g></g>` +
      `<g data-k="spk">${sparkle(ro[0] + 90 * rs, ro[1] - 300 * rs, 16)}${sparkle(ro[0] - 80 * rs, ro[1] - 320 * rs, 11, 'terra')}</g>`;
    const A = layer(P, m);
    P.content.appendChild(bub.el);
    const say = text(P, 'ik-say', '', pad, pad, `width:${B.w - 2 * pad}px;font-size:${fs}px;`, bub.el);
    const spans = charSpans(say, msg);
    // human cadence: per-char weights (punctuation pauses, seeded jitter), mapped onto the typing window
    const r = rng(msg.length + 7);
    const wts = spans.map((s) => { const ch = s ? s.textContent : ' '; return (/[.,!?;:]/.test(ch) ? 4 : ch === ' ' ? 1.6 : 1) * (0.7 + r() * 0.6); });
    const cum = []; let acc = 0; for (const w of wts) { acc += w; cum.push(acc); }
    const t0 = T(0.45), t1 = Math.max(t0 + 0.6, D - T(0.7));
    const kick = text(P, 'ik-kicker', 'The ask', S.l, L ? S.t : S.t - 20);
    const youL = L ? text(P, 'ik-hand', 'you', 150, 470, 'font-size:54px;transform:rotate(-8deg);') : null;
    const ar = L ? layer(P, arrow([200, 545], [262, 640], 'pb:ar', { bend: 20, draw: 'a' })) : null;
    const user = A.K.user[0], bot = A.K.bot[0];
    const cam = P.track([[0, [W / 2, H / 2, 1.0]], [D + 0.5, [W / 2 + (L ? 30 : 0), H / 2 - (L ? 10 : 40), 1.03]]]);
    return {
      cues: [{ t: T(0.2), sfx: 'appear', gain_db: -10 }, { t: t0, sfx: 'type', gain_db: -12 }, { t: t1, sfx: 'appear', gain_db: -14 }],
      render(t) {
        const up = popIn(t, -0.1, 0.4, 0.92);
        gpose(user, { ox: uo[0], oy: uo[1], s: up.s, op: up.op });
        const bp = popIn(t, T(0.2), 0.36, 0.9, true);
        const bo = L ? '0% 80%' : '26% 100%';
        place(bub.el, { s: bp.s, op: bp.op, origin: bo });
        const u = clamp((t - t0) / (t1 - t0));
        let n = 0; while (n < cum.length && cum[n] <= u * acc) n++;
        typeTo(spans, u >= 1 ? spans.length : n);
        const rp = popIn(t, T(0.35), 0.34, 0.9);
        gpose(bot, { ox: ro[0], oy: ro[1], s: rp.s, op: rp.op, y: Math.sin(t * 2) * 2 });
        const done = t >= t1;
        antenna(A.K, 'r', done ? 0.6 + 0.4 * Math.sin((t - t1) * 9) : 0);
        if (done) face(A.K, 'r', t < t1 + 0.35 ? 'wow' : 'happy'); else blink(A.K, 'r', t, 'focus', 0.3);
        setArm(A.K['r-armR'][0], 'r', done ? lerp(160, 150, seg(t, t1, t1 + 0.3)) : 160 + Math.sin(t * 7) * 6);
        css(A.K.spk[0], { opacity: seg(t, t1, t1 + 0.2).toFixed(3) });
        writeOn(kick, seg(t, 0, T(0.3)));
        if (youL) { writeOn(youL, seg(t, T(0.5), T(0.8))); drawOn(ar.D.a, seg(t, T(0.7), T(1.0))); }
        P.camera(t, cam(t));
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ PLAN
inkScene('kit:ink/PLAN', {
  describe: "The plan (style frame B): numbered sticky notes slap onto a corkboard, done items get teal ticks, a terracotta marker loop circles the active note while the user points at it with a pointer; \"3 of 6 done!\" is handwritten under the title; the robot sits on the board.",
  params: { items: { type: 'array', default: [], doc: '[{text, status}] <= 6 (status: completed|in_progress|pending)' },
    more: { type: 'number', default: 0, doc: 'hidden items count' }, total: { type: 'number', default: 0, doc: 'total items (else items + more)' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const items = (Array.isArray(p.items) ? p.items : []).slice(0, 6).map((it) => (typeof it === 'string' ? { text: it, status: 'pending' } : it || {}));
    if (!items.length) items.push({ text: 'Plan the work', status: 'in_progress' });
    const total = Math.max(Number(p.total) || 0, items.length + (Number(p.more) || 0));
    const doneN = items.filter((i) => i.status === 'completed').length;
    let act = items.findIndex((i) => i.status === 'in_progress');
    if (act < 0) act = items.findIndex((i) => i.status !== 'completed');
    const n = items.length;
    const cols = L ? (n <= 3 ? n : n === 4 ? 2 : 3) : (n <= 2 ? n : 2);
    const rows = Math.ceil(n / cols);
    const Bd = L ? { x: 610, y: 150, w: 1210, h: 850 } : { x: 60, y: 520, w: 960, h: 1010 };
    if (!L && rows < 3) { Bd.h = rows * 330 + 80; }
    if (L && rows < 2) { Bd.y = 300; Bd.h = 520; }
    const inset = 26;
    const nw = L ? Math.min(330, (Bd.w - 2 * inset - (cols + 1) * 40) / cols) : Math.min(400, (Bd.w - 2 * inset - (cols + 1) * 36) / cols);
    const nh = L ? Math.min(300, (Bd.h - 2 * inset - (rows + 1) * 40) / rows) : Math.min(290, (Bd.h - 2 * inset - (rows + 1) * 26) / rows);
    const gx = (Bd.w - 2 * inset - cols * nw) / (cols + 1), gy = (Bd.h - 2 * inset - rows * nh) / (rows + 1);
    // board (as art) + robot on the board edge
    const ro = [Bd.x + Bd.w - 150, Bd.y + 4], rsc = L ? 0.56 : 0.6;
    const board = `<rect x="${Bd.x + 14}" y="${Bd.y + 18}" width="${Bd.w}" height="${Bd.h}" fill="${C.shadow}"/>` +
      form(['rect', Bd.x, Bd.y, Bd.w, Bd.h, 10], 'wood', 'pl:frame') +
      `<rect x="${Bd.x + inset}" y="${Bd.y + inset}" width="${Bd.w - 2 * inset}" height="${Bd.h - 2 * inset}" fill="${C.cork}"/>`;
    let speck = '';
    const r = rng(41);
    for (let i = 0; i < (Bd.w * Bd.h) / 700; i++) {
      const x = Bd.x + inset + r() * (Bd.w - 2 * inset), y = Bd.y + inset + r() * (Bd.h - 2 * inset), rr = 1.2 + r() * 2.4;
      speck += `M${(x - rr).toFixed(1)},${y.toFixed(1)}a${rr.toFixed(1)},${(rr * 0.7).toFixed(1)} 0 1,0 ${(2 * rr).toFixed(1)},0a${rr.toFixed(1)},${(rr * 0.7).toFixed(1)} 0 1,0 ${(-2 * rr).toFixed(1)},0`;
    }
    const disc = L ? `<circle cx="300" cy="840" r="300" fill="${C.peach}"/>` : `<circle cx="760" cy="1760" r="330" fill="${C.peach}"/>`;
    const A = layer(P, disc + `<g data-k="board">${board}<path d="${speck}" fill="${C.corkD}" opacity=".5"/>` +
      `<rect x="${Bd.x + inset}" y="${Bd.y + inset}" width="${Bd.w - 2 * inset}" height="9" fill="rgba(92,62,38,.18)"/></g>` +
      `<g data-k="bot"><g transform="translate(${ro[0]},${ro[1]}) scale(${rsc})">${robot('r', { pose: 'stand', shadow: false }).markup}</g></g>`);
    // notes
    const pins = ['terra', 'teal', 'mustard'];
    const notes = items.map((it, i) => {
      const c = i % cols, rr2 = Math.floor(i / cols);
      const x = Bd.x + inset + gx + c * (nw + gx), y = Bd.y + inset + gy + rr2 * (nh + gy);
      const txt = clip(it.text || '', 64);
      const fs = fitText(txt, nw - 58, 3, 52, 34, CW.hand);
      const nt = note(P.doc, x, y, nw, { h: nh, color: NOTE_COLORS[i % 4], num: String(i + 1).padStart(2, '0'), text: txt, size: fs,
        check: it.status === 'completed' ? 'done' : 'todo', pin: pins[i % 3], key: `pl:n${i}` });
      P.content.appendChild(nt.el);
      const rot = (rng(i * 13 + 5)() - 0.5) * 4;
      return { ...nt, x, y, rot, cx: x + nw / 2, cy: y + nh / 2 };
    });
    // the active note: marker loop (top layer) + presenter pointing
    const an = act >= 0 ? notes[act] : notes[n - 1];
    const lp = act >= 0 ? layer(P, loop(an.x, an.y, nw, nh, 'pl:loop', { draw: 'lp', pad: 16 }), 'top') : null;
    const ps = L ? 0.95 : 1.05;
    const po = L ? [Math.min(300, Bd.x - 230), 1010] : [250, 1960];
    const shoulder = L ? [po[0] + 84 * ps, po[1] - 462 * ps] : [po[0] + 84 * ps, po[1] - 192 * ps];
    const target = [an.cx - nw * 0.25, an.cy + nh * 0.15];
    const aim = aimR(shoulder, target);
    const reach = Math.hypot(target[0] - shoulder[0], target[1] - shoulder[1]) / ps - 156;
    const Pz = layer(P, `<g data-k="pres"><g transform="translate(${po[0]},${po[1]}) scale(${ps})">${person('u', { variant: L ? 'stand' : 'bust', pose: 'point', pointer: clamp(reach, 120, 900), look: 0.8 }).markup}</g></g>`);
    // title block
    const tx = L ? S.l - 8 : S.l - 30;
    const kick = text(P, 'ik-kicker', act >= 0 ? `Step ${act + 1} of ${total}` : `${total} steps`, tx + 4, L ? 92 : S.t + 6);
    const ttl = text(P, 'ik-h', 'The plan', tx, L ? 126 : S.t + 44, `font-size:${L ? 116 : 104}px;`);
    const doneTxt = doneN >= total ? 'all done!' : `${doneN} of ${total} done!`;
    const ann = text(P, 'ik-hand', doneTxt, tx + 10, L ? 258 : S.t + 168, `font-size:${L ? 56 : 54}px;transform:rotate(-4deg);`);
    const AU = layer(P, underline(tx + 8, (L ? 258 : S.t + 168) + 66, Math.max(220, doneTxt.length * 25), 'pl:ul', { draw: 'u', sw: 5 }));
    const board2 = A.K.board[0], bot = A.K.bot[0], pres = Pz.K.pres[0], armR = Pz.K['u-armR'][0];
    const land = notes.map((_, i) => T(0.22 + i * 0.17));
    const cam = P.track([[0, [W / 2 - 10, H / 2, 1.0]], [D + 0.5, [W / 2 + (L ? 50 : 0), H / 2 + (L ? 0 : 40), 1.045]]]);
    const tLoop = T(0.3 + n * 0.17 + 0.25);
    return {
      cues: [{ t: 0.05, sfx: 'appear', gain_db: -12 }, ...land.slice(0, 4).map((t) => ({ t, sfx: 'appear', gain_db: -15 })),
        { t: tLoop, sfx: 'type', gain_db: -12 }],
      render(t) {
        const bp = popIn(t, -0.15, 0.4, 0.97);
        gpose(board2, { ox: Bd.x + Bd.w / 2, oy: Bd.y + Bd.h / 2, s: bp.s, op: bp.op });
        notes.forEach((nt, i) => {
          settleIn(nt.el, t, land[i], { r: nt.rot, settle: true, from: 1.08, rise: 0, spin: 3, origin: '50% 0%', dur: 0.26 });
          drawOn(nt.tick, seg(t, land[i] + 0.22, land[i] + 0.45, ease.inOutCubic));
        });
        if (lp) drawOn(lp.D.lp, seg(t, tLoop, tLoop + T(0.5), ease.inOutCubic));
        const pp = popIn(t, -0.05, 0.4, 0.94);
        gpose(pres, { ox: po[0], oy: po[1], s: pp.s, op: pp.op });
        const au = seg(t, T(0.6), tLoop + 0.1, ease.inOutCubic);
        setArm(armR, 'r', lerp(14, aim, au) + Math.sin(t * 2.4) * 1.2 * au, 'person');
        const rp = popIn(t, T(0.5), 0.3, 0.9);
        gpose(bot, { ox: ro[0], oy: ro[1], s: rp.s, op: rp.op });
        blink(A.K, 'r', t, 'happy', 1.2);
        setArm(A.K['r-armR'][0], 'r', 140 + Math.sin(t * 6) * 16);
        writeOn(kick, seg(t, 0, T(0.25)));
        const tu = seg(t, -0.1, T(0.35), ease.outCubic);
        css(ttl, { opacity: tu.toFixed(3), transform: `translate(0,${((1 - tu) * 20).toFixed(2)}px)` });
        writeOn(ann, seg(t, tLoop + T(0.2), tLoop + T(0.55)));
        drawOn(AU.D.u, seg(t, tLoop + T(0.5), tLoop + T(0.75)));
        P.camera(t, cam(t));
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ STATS
inkScene('kit:ink/STATS', {
  describe: 'Real session numbers as big painted Fraunces numerals: each wipes in with ink and counts up, a Caveat label writes under it, terracotta underlines draw on, and the robot cheers from the top of the hero number (the music drop).',
  params: { ...pick(STATS_DEF.params, ['stats']), label: { type: 'string', default: '', doc: 'small handwritten heading' } },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const stats = (Array.isArray(p.stats) ? p.stats : []).slice(0, 3);
    if (!stats.length) stats.push({ display: '1', label: 'build' });
    const n = stats.length;
    const cols = [];
    const usable = W - S.l - S.r;
    for (let i = 0; i < n; i++) {
      const hero = i === 0;
      const disp = String(stats[i].display ?? stats[i].value ?? '');
      let cw, cx, cy;
      if (L) { cw = usable / n; cx = S.l + cw * (i + 0.5); cy = n === 1 ? H / 2 + 20 : H / 2 + 40; }
      else { cw = usable + 120; cx = W / 2; cy = S.t + 330 + i * ((H - S.t - S.b - 260) / Math.max(n, 1)); }
      const max = L ? (n === 1 ? 300 : hero ? 230 : 190) : (hero ? 250 : 200);
      const size = Math.round(clamp((cw * 0.86) / (Math.max(2, disp.length) * 0.6), 96, max));
      cols.push({ disp, value: stats[i].value, label: clip(stats[i].label || stats[i].key || '', 28), cx, cy, size, hero });
    }
    let m = `<circle cx="${cols[0].cx}" cy="${cols[0].cy - cols[0].size * 0.2}" r="${Math.round(cols[0].size * 1.25)}" fill="${C.peach}"/>`;
    cols.forEach((c, i) => {
      const w = Math.min(c.disp.length * c.size * 0.58, L ? usable / n - 40 : usable);
      m += `<g data-k="sw${i}">${form(['path', `M${c.cx - w / 2 - 20},${c.cy - c.size * 0.42} C${c.cx - w / 4},${c.cy - c.size * 0.55} ${c.cx + w / 4},${c.cy - c.size * 0.38} ${c.cx + w / 2 + 24},${c.cy - c.size * 0.5} L${c.cx + w / 2 + 14},${c.cy + c.size * 0.12} C${c.cx},${c.cy + c.size * 0.2} ${c.cx - w / 3},${c.cy + c.size * 0.02} ${c.cx - w / 2 - 12},${c.cy + c.size * 0.14} Z`], i === 0 ? 'mustard' : i === 1 ? 'mint' : 'sky', `st:sw${i}`, { sw: 0, fillOpacity: 0.55 })}</g>`;
      m += underline(c.cx - w / 2, c.cy + c.size * 0.32, w, `st:ul${i}`, { draw: `u${i}`, sw: i === 0 ? 7 : 5 });
      m += `<g data-k="sp${i}">${sparkle(c.cx + w / 2 + 34, c.cy - c.size * 0.62, 14)}${sparkle(c.cx - w / 2 - 30, c.cy - c.size * 0.2, 9, 'terra')}</g>`;
    });
    const h0 = cols[0];
    const w0 = Math.min(h0.disp.length * h0.size * 0.58, L ? usable / n - 40 : usable);
    const ro = [h0.cx + w0 * 0.18, h0.cy - h0.size * 0.62], rsc = L ? (n === 1 ? 0.8 : 0.62) : 0.6;
    m += `<g data-k="bot"><g transform="translate(${ro[0]},${ro[1]}) scale(${rsc})">${robot('r', { pose: 'cheer', shadow: false }).markup}</g></g>`;
    const A = layer(P, m);
    const nums = cols.map((c) => text(P, 'ik-num', c.disp, c.cx - 1000, c.cy - c.size * 0.72, `width:2000px;text-align:center;font-size:${c.size}px;`));
    const labs = cols.map((c) => text(P, 'ik-hand', c.label, c.cx - 600, c.cy + c.size * 0.36, `width:1200px;text-align:center;font-size:${L ? 52 : 56}px;color:#2B2622;`));
    let head = null;
    if (p.label) head = text(P, 'ik-hand', clip(p.label, 40), L ? S.l + 10 : S.l - 10, L ? S.t + 10 : S.t, `font-size:${L ? 60 : 64}px;transform:rotate(-3deg);`);
    const land = cols.map((_, i) => T(0.25 + i * 0.32));
    const bot = A.K.bot[0];
    const cam = P.track([[0, [W / 2, H / 2, 1.06]], [land[n - 1] + 0.4, [W / 2, H / 2, 1.0]], [D + 0.5, [W / 2, H / 2 - 10, 1.015]]]);
    return {
      cues: land.map((t, i) => ({ t, sfx: 'hit', gain_db: i ? -8 : -4 })),
      render(t) {
        cols.forEach((c, i) => {
          const u = seg(t, land[i], land[i] + 0.3, ease.outCubic);
          writeOn(nums[i], u);
          nums[i].textContent = countFrame(c.disp, c.value, t, land[i], 0.8 * T.k);
          css(nums[i], { transform: `translate(0,${((1 - u) * 24).toFixed(2)}px)` });
          const sw = seg(t, land[i] - 0.1, land[i] + 0.2, ease.outCubic);
          gpose(A.K[`sw${i}`][0], { ox: c.cx - 200, oy: c.cy, s: 1, op: sw });
          drawOn(A.D[`u${i}`], seg(t, land[i] + 0.25, land[i] + 0.6, ease.inOutCubic));
          writeOn(labs[i], seg(t, land[i] + 0.3, land[i] + 0.65));
          const sp = A.K[`sp${i}`][0];
          css(sp, { opacity: (seg(t, land[i] + 0.2, land[i] + 0.35) * (0.75 + 0.25 * Math.sin(t * 5 + i))).toFixed(3) });
        });
        const rp = popIn(t, land[0] + 0.15, 0.3, 0.85, true);
        gpose(bot, { ox: ro[0], oy: ro[1], s: rp.s, op: rp.op, y: -Math.abs(Math.sin(t * 5.2)) * 8 * seg(t, land[0] + 0.3, land[0] + 0.5) });
        setArm(A.K['r-armL'][0], 'l', 150 + Math.sin(t * 9) * 12);
        setArm(A.K['r-armR'][0], 'r', 150 + Math.sin(t * 9 + 1.5) * 12);
        if (head) writeOn(head, seg(t, 0, T(0.3)));
        P.camera(t, cam(t));
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ CALLOUT
inkScene('kit:ink/CALLOUT', {
  describe: 'One quotable line, verbatim, in a hand-drawn speech bubble from the robot (or the user): Fraunces italic words appear one by one, then one word gets a terracotta underline; a handwritten attribution.',
  params: { ...pick(CALLOUT_DEF.params, ['text', 'who', 'ref']) },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const quote = clip(p.text || '', 160);
    const who = String(p.who || 'agent').toLowerCase();
    const isUser = who === 'user';
    const B = L ? { x: 620, y: 150, w: 1170, h: 600 } : { x: 70, y: 280, w: 940, h: 900 };
    const so = L ? [330, 1000] : [540, 1760], ssc = isUser ? (L ? 1.0 : 1.1) : (L ? 1.25 : 1.4);
    const headY = so[1] - (isUser ? 312 : 170) * ssc;
    const tip = L ? [so[0] + 110 - B.x, headY - B.y] : [so[0] - B.x, headY - (isUser ? 120 : 140) * ssc - B.y];
    const bub = bubble(P.doc, B.w, B.h, L ? 'left' : 'bottom', L ? 0.7 : 0.5, tip, { key: 'cb', bw: 96 });
    bub.el.style.left = `${B.x}px`; bub.el.style.top = `${B.y}px`;
    const fig = isUser ? person('u', { variant: 'bust', look: 0.5 }).markup : robot('r', { pose: 'present' }).markup;
    const A = layer(P, `<circle cx="${so[0]}" cy="${so[1] - 160 * ssc}" r="${L ? 310 : 330}" fill="${C.peach}"/>` +
      `<g data-k="fig"><g transform="translate(${so[0]},${so[1]}) scale(${ssc})">${fig}</g></g>`);
    P.content.appendChild(bub.el);
    const pad = L ? 70 : 64;
    const fs = fitBox(quote, B.w - 2 * pad, B.h - 2 * pad - 30, L ? 76 : 80, 44, CW.serifIt, 1.18);
    const qEl = text(P, 'ik-quote', '', pad, pad, `width:${B.w - 2 * pad}px;height:${B.h - 2 * pad}px;font-size:${fs}px;display:flex;flex-wrap:wrap;align-content:center;justify-content:center;column-gap:0.26em;`, bub.el);
    const words = quote.split(/\s+/).filter(Boolean);
    const em = pickEmphasis(quote);
    const wEls = words.map((w, i) => { const s = h('span', 'ik-word', { text: w }); if (i === em) s.style.cssText = `background-image:${underlineUrl('cl:em')};background-repeat:no-repeat;background-position:0 100%;padding-bottom:0.1em;`; qEl.appendChild(s); return s; });
    const attr = isUser ? '\u2014 you' : who === 'test' ? '\u2014 the test run' : '\u2014 your agent';
    const at = text(P, 'ik-hand', attr, L ? B.x + B.w - 330 : B.x + B.w - 330, B.y + B.h + 30, 'font-size:50px;transform:rotate(-3deg);');
    const fig2 = A.K.fig[0];
    const wt = (i) => T(0.35) + i * Math.min(0.11, (D * 0.45) / Math.max(1, words.length));
    const tEm = wt(words.length) + 0.15;
    const cam = P.track([[0, [W / 2, H / 2, 1.0]], [D + 0.5, [W / 2 + (L ? 30 : 0), H / 2 - 10, 1.035]]]);
    return {
      cues: [{ t: T(0.15), sfx: 'appear', gain_db: -10 }, { t: tEm, sfx: 'type', gain_db: -14 }],
      render(t) {
        const fp = popIn(t, -0.1, 0.36, 0.92);
        gpose(fig2, { ox: so[0], oy: so[1], s: fp.s, op: fp.op });
        const bp = popIn(t, T(0.15), 0.3, 0.88, true);
        place(bub.el, { s: bp.s, op: bp.op, origin: L ? '0% 70%' : '50% 100%' });
        wEls.forEach((s, i) => { const u = seg(t, wt(i), wt(i) + 0.28, ease.outCubic); css(s, { opacity: clamp(u * 2).toFixed(3), transform: `translate(0,${((1 - u) * 14).toFixed(2)}px)` }); });
        if (wEls[em]) wEls[em].style.backgroundSize = `${(seg(t, tEm, tEm + 0.4, ease.inOutCubic) * 100).toFixed(1)}% 0.28em`;
        writeOn(at, seg(t, tEm + 0.1, tEm + 0.45));
        if (!isUser) { blink(A.K, 'r', t, 'happy', 0.4); setArm(A.K['r-armR'][0], 'r', 118 + Math.sin(t * 2.6) * 8); }
        P.camera(t, cam(t));
      },
    };
  },
});

// ------------------------------------------------------------------------------------------------ END
inkScene('kit:ink/END', {
  describe: 'End card (thumbnail frame): the user and the robot wave side by side, the title lockup with the film strip running under it, the CTA command written on a paper luggage tag, the repo URL and the "made with Hermes \u00b7 Hype" credit; speedrun adds a PB sticky note.',
  params: { ...pick(END_DEF.params, ['title', 'cta', 'url', 'credit', 'tagline', 'pb_display']) },
  build(ctx, p, F, P) {
    const L = !F.portrait, W = F.W, H = F.H, S = F.safe, T = clockOf(ctx.dur), D = ctx.dur;
    const title = String(p.title || '').trim() || 'Hype';
    const tag = clip(p.tagline || '', 80);
    // cast
    const uo = L ? [400, 1010] : [370, 1200], us = L ? 1.0 : 0.95;
    const ro = L ? [720, 1000] : [700, 1190], rsc = L ? 1.12 : 1.08;
    const fpts = L ? [[1010, 520], [1300, 500], [1560, 540], [1990, 500]] : [[-60, 560], [300, 530], [700, 570], [1140, 530]];
    const film = filmStrip(fpts, `${P.uid}e`, { width: 70, frame: 54, gap: 12 });
    const m = `<circle cx="${L ? 560 : 540}" cy="${L ? 720 : 990}" r="${L ? 400 : 330}" fill="${C.peach}"/>` +
      `<ellipse cx="${L ? 560 : 540}" cy="${L ? 1010 : 1202}" rx="380" ry="16" fill="${C.shadow}"/>` + film.markup +
      `<g data-k="user"><g transform="translate(${uo[0]},${uo[1]}) scale(${us})">${person('u', { variant: 'bust', pose: 'wave', look: 0.4 }).markup}</g></g>` +
      `<g data-k="bot"><g transform="translate(${ro[0]},${ro[1]}) scale(${rsc})">${robot('r', { arms: { l: 150, r: 20 } }).markup}</g></g>` +
      `<g data-k="spk">${sparkle(L ? 260 : 170, L ? 420 : 760, 16)}${sparkle(L ? 900 : 950, L ? 520 : 840, 12, 'terra')}${sparkle(L ? 860 : 880, L ? 300 : 700, 9, 'teal')}</g>`;
    const A = layer(P, m);
    const update = film.bind(A.el);
    const bx = L ? 1030 : S.l - 30, bw = L ? W - 1030 - S.r + 20 : W - 2 * (S.l - 30);
    let y = L ? S.t + 70 : S.t + 10;
    const ts = fitText(title, bw, 1, L ? 150 : 140, 80, CW.display);
    const tEl = text(P, 'ik-title', '', bx, y, `font-size:${ts}px;width:${bw + 40}px;white-space:nowrap;`);
    const letters = charSpans(tEl, title);
    y += ts * 0.95 + 20;
    let tg = null;
    if (tag) { const s2 = fitText(tag, bw, 2, 46, 36, CW.serifIt); tg = text(P, 'ik-tagline', tag, bx + 4, y, `font-size:${s2}px;width:${bw}px;`); y += s2 * 1.22 * (tag.length * s2 * CW.serifIt > bw ? 2 : 1) + 20; }
    let cta = null;
    const ctaY = L ? Math.max(y + 110, 620) : 1250;
    if (p.cta) {
      cta = luggageTag(P.doc, clip(p.cta, 44), { size: L ? 32 : 30, maxW: L ? bw : W - 2 * S.l + 80, key: 'end:cta' });
      cta.el.style.left = `${(L ? bx + 60 : S.l - 10) - cta.off}px`; cta.el.style.top = `${ctaY}px`;
      P.content.appendChild(cta.el);
    }
    const urlY = ctaY + (cta ? cta.h + 34 : 0);
    const url = p.url ? text(P, 'ik-url', clip(String(p.url).replace(/^https?:\/\//, '').replace(/\/$/, ''), 48), L ? bx + 64 : S.l + 10, urlY) : null;
    const credit = p.credit ? text(P, 'ik-credit', p.credit, L ? bx + 64 : S.l + 10, L ? H - S.b - 10 : Math.max(urlY + 60, H - S.b - 70)) : null;
    let pb = null;
    if (p.pb_display) {
      pb = note(P.doc, L ? W - S.r - 250 : W - S.r - 190, L ? 60 : S.t - 30, L ? 250 : 220, { color: 'butter', text: `PB ${p.pb_display}`, size: 64, tape: true, key: 'end:pb' });
      pb.text.style.top = '60px'; pb.text.style.textAlign = 'center';
      P.content.appendChild(pb.el);
    }
    const user = A.K.user[0], bot = A.K.bot[0];
    const cam = P.track([[0, [W / 2 + 10, H / 2, 1.04]], [T(2.0), [W / 2, H / 2, 1.0]], [D + 0.5, [W / 2, H / 2, 1.0]]]);
    return {
      cues: [{ t: 0.05, sfx: 'appear', gain_db: -10 }, { t: T(0.9), sfx: 'appear', gain_db: -12 }],
      render(t) {
        const up = popIn(t, -0.1, 0.36, 0.92);
        gpose(user, { ox: uo[0], oy: uo[1], s: up.s, op: up.op });
        setArm(A.K['u-armR'][0], 'r', 150 + Math.sin(t * 6.5) * 14, 'person');
        const bp = popIn(t, T(0.08), 0.36, 0.92);
        gpose(bot, { ox: ro[0], oy: ro[1], s: bp.s, op: bp.op, y: Math.sin(t * 2.4) * 2 });
        setArm(A.K['r-armL'][0], 'l', 150 + Math.sin(t * 6.5 + 1.2) * 16);
        blink(A.K, 'r', t, 'happy', 0.9);
        riseLetters(letters, t, T(0.2), { stagger: Math.min(0.03, 0.4 / letters.length) });
        update(seg(t, T(0.5), T(1.2), ease.outCubic), t * 60);
        if (tg) { const u = seg(t, T(0.6), T(0.95), ease.outCubic); css(tg, { opacity: u.toFixed(3), transform: `translate(0,${((1 - u) * 14).toFixed(2)}px)` }); }
        if (cta) writeOn(cta.el, seg(t, T(0.9), T(1.25), ease.outCubic));
        if (url) writeOn(url, seg(t, T(1.15), T(1.45)));
        if (credit) css(credit, { opacity: seg(t, T(1.3), T(1.6)).toFixed(3) });
        if (pb) settleIn(pb.el, t, T(1.1), { r: 5, from: 1, rise: -40, spin: 7 });
        css(A.K.spk[0], { opacity: (seg(t, T(0.6), T(0.9)) * (0.8 + 0.2 * Math.sin(t * 4))).toFixed(3) });
        P.camera(t, cam(t));
      },
    };
  },
});

