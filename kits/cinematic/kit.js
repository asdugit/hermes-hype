// Hype kit · cinematic — "evidence becomes a world": the session's real captures are emissive glass cards
// at depth in a dark room, shot by a heavy camera with per-object depth of field, dust bokeh, bloom, 2.39
// letterbox, Cormorant titles and one amber accent. Registers the 15 Quick-mode types (kit:cinematic/<TYPE>,
// data = TimelineScene.data shapes) plus kit:cinematic/card-field and kit:cinematic/screen-push.
import { sr } from '../../runtime/showreel.js';
import { mediaOf, isCard } from '../base/media.js';
import * as cards from './lib/cards.js';
import { makeCine, rig, mulberry32, clamp, lerp, inOut, outCubic, TPU } from './lib/world.js';
import * as type from './lib/type.js';
import { drawLockup, LOCKUP_PARAMS } from './lib/lockup.js';

const { PAD } = cards;
const hashStr = (s) => { let h = 2166136261 >>> 0; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; } return h; };

const COMMON = {
  label: { type: 'string', default: '', doc: 'storyboard label (<= 6 words); shown as kicker/caption where the type allows' },
  quality: { type: 'enum', values: ['auto', 'high', 'low'], default: 'auto', doc: 'auto = low on software GL (half-res plate, 12-tap DOF)' },
  rail: { type: 'object', default: null, doc: '{from, to (0..1 session progress over the shot), ticks:[0..1], label} — session-clock rail in the bottom bar' },
  register: { type: 'bool', default: true, doc: 'show the "● CAPTURED · session" tag on verbatim captures' },
  _captions: { type: 'bool', default: false, doc: 'captions are up (Quick mode): lower thirds lift clear of the caption band' },
};
const IMAGE_DOC = { type: 'image', default: null, doc: 'screenshot/product image ({asset, url, ...} or asset name)' };

/** Card width in world units (texels / TPU incl. padding). */
const cw = (c) => c.cv.width / TPU, ch = (c) => c.cv.height / TPU;
/** Camera distance so a card of width w (units) fills `fill` of the frame width (vfov deg). */
function fitDist(w, h, ctx, fill = 0.72, fov = 30) {
  const tanV = Math.tan((fov * Math.PI) / 360), tanH = tanV * ctx.w / ctx.h;
  const pic = ctx.h > ctx.w ? 1 : 0.78;      // letterboxed picture height fraction
  return Math.max((w / 2) / (tanH * fill), (h / 2) / (tanV * pic * fill * 1.05));
}

/** Ambient glass cards (abstract, unreadable) scattered in depth; `avoid` keeps the centre clear. */
function ghosts(seed, n, o = {}) {
  const r = mulberry32(seed), out = [];
  for (let i = 0; i < n; i++) {
    const side = i % 2 ? 1 : -1;
    const z = lerp(o.z0 ?? -3, o.z1 ?? -16, r());
    const x = side * (o.xMin ?? 1.6) + side * r() * (o.xSpread ?? 3.5) + (z < -8 ? (r() - 0.5) * 4 : 0);
    out.push({ card: cards.ghostCard(r), pos: [x, (r() - 0.5) * (o.ySpread ?? 2.4), z], rot: [0, -side * (10 + r() * 30), 0], scale: 0.9 + r() * 0.6,
      exposure: 0.8, dim: o.dim ?? 0.55, rim: 1.4, halo: 0.05 });
  }
  return out;
}
/** Two near defocused motes-cards in the outer thirds (foreground depth cue). */
function nearGhosts(seed) {
  const r = mulberry32(seed + 99);
  return [-1, 1].map((s) => ({ card: cards.ghostCard(r), pos: [s * (1.5 + r() * 0.5), (r() - 0.5) * 0.8, 2.6 + r()], rot: [0, -s * 25, 0], scale: 0.8, dim: 0.5, halo: 0 }));
}

/** Build a hero card from a content dict ({kind: image|terminal|diff|code|plan|prompt, ...}). */
function contentCard(ctx, d) {
  const k = d && (d.kind || (d.image || d.asset || d.path && /\.(png|jpe?g|webp)$/i.test(d.path) ? 'image' : d.cmd ? 'terminal' : d.hunks ? 'diff' : d.lines ? 'code' : d.items ? 'plan' : 'prompt'));
  if (k === 'image' || k === 'screenshot') {
    const m = mediaOf(ctx, d.image || d);
    // a game/app picture (image.frame 'card') has no address: no URL bar with its file name on the glass card
    const url = isCard(m.meta) || isCard(d) ? '' : (d.url || (m.meta && m.meta.url) || '');
    return m.image ? cards.screenshotCard(m.image, url, { viewH: 1000 }) : cards.promptCard({ text: d.page_title || url || '' });
  }
  if (k === 'terminal') return cards.terminalCard(d);
  if (k === 'diff') return cards.diffCard(d);
  if (k === 'code') return cards.codeCard(d);
  if (k === 'plan') return cards.planCard(d);
  return cards.promptCard({ text: d.text || d.label || '' });
}

/** Register a three-layer cinematic scene; build(ctx, p, rnd) returns the world spec (items, cam, focus, overlay...). */
function defineCine(id, describe, params, build) {
  sr.defineScene(id, {
    layer: 'three', describe, params: { ...COMMON, ...params },
    async setup(ctx, p) {
      const seed = ((ctx.seed || 0) * 31 + hashStr(id + (ctx.id || ''))) >>> 0;
      const spec = build(ctx, p, mulberry32(seed), seed);
      const userOverlay = spec.overlay;
      const railSpec = p.rail;
      spec.overlay = (g, t, F) => {
        if (userOverlay) userOverlay(g, t, F);
        if (railSpec) type.rail(g, F, lerp(railSpec.from ?? 0, railSpec.to ?? railSpec.from ?? 0, clamp(t / ctx.dur)), railSpec.ticks || [], { label: railSpec.label });
        if (spec.register && p.register !== false) type.register(g, F, t);
      };
      if (railSpec) spec.overlayKey = (t) => String(Math.round(t * 30));
      ctx.state = makeCine(ctx, { seed, quality: p.quality, ...spec });
    },
    render(ctx, t) { ctx.state.render(t); },
  });
}

const until = (T) => (t) => (t < T ? String(Math.round(t * 30)) : 'done');
const logDolly = (z0, z1, u) => z0 * Math.pow(z1 / z0, u);

// ------------------------------------------------------------------------------------- HOOK
defineCine('kit:cinematic/HOOK', 'Black → the hero capture already lit and close; slow push through two near bokeh motes, focus pulls from a mote to the card; <= 6 words in Cormorant italic.',
  { hero: { type: 'content', default: null, doc: '{kind: image|terminal|diff|code, ...data}' } },
  (ctx, p, r, seed) => {
    const hero = contentCard(ctx, p.hero || {});
    const D = fitDist(cw(hero), ch(hero), ctx, 0.7);
    const items = [{ card: hero, pos: [0, 0, 0], exposure: 1.18, rim: 2.4, halo: 0.1 }, ...ghosts(seed, 6, { dim: 0.35 }), ...nearGhosts(seed)];
    const dur = ctx.dur;
    return {
      items, register: true, motes: 8,
      cam: (t) => rig([[0, { pos: [0.12, 0.05, logDolly(D * 1.3, D, inOut(t / dur))], look: [0, 0, 0], fov: 30 }]], t),
      focus: (t) => lerp(0.9, logDolly(D * 1.3, D, inOut(t / dur)), outCubic((t - 0.15) / 0.9)),   // pull from a mote to the card
      overlay: (g, t, F) => { if (p.label) type.italic(g, F, p.label, t, { y: F.h - F.barH - (p._captions ? 210 : 70) * F.scale, size: 56, t0: 0.5 }); },
      overlayKey: until(2.5),
    };
  });

// ------------------------------------------------------------------------------------- TITLE / END (corridor)
function corridor(seed, n = 16) {
  const r = mulberry32(seed + 5), out = [];
  for (let i = 0; i < n; i++) {
    const side = i % 2 ? 1 : -1, z = 4 - i * 1.7 - r() * 0.8;
    out.push({ card: cards.ghostCard(r), pos: [side * (2.1 + r() * 0.6), (r() - 0.5) * 0.9, z], rot: [0, -side * (58 + r() * 12), 0], scale: 0.9 + r() * 0.4, dim: 0.75, rim: 2.0, halo: 0.08 });
  }
  return out;
}
defineCine('kit:cinematic/TITLE', 'Corridor of evidence cards on both walls receding to a dark centre; wide-tracked Cormorant title + italic tagline in the void; camera creeps forward.',
  { title: { type: 'string', default: '', doc: 'product name' }, tagline: { type: 'string', default: '', doc: 'one line' }, product: { type: 'string', default: '', doc: 'overline' }, one_liner: { type: 'string', default: '', doc: 'fallback tagline' } },
  (ctx, p, r, seed) => ({
    items: corridor(seed), warmAt: [0.5, 0.5],
    cam: (t) => rig([[0, { pos: [0, 0, 7.5], look: [0, 0, -30], fov: 32 }], [ctx.dur, { pos: [0, 0, 7.5 - 0.3 * ctx.dur], look: [0, 0, -30], fov: 32 }]], t, { ease: (u) => u }),
    focus: () => 7,
    overlay: (g, t, F) => {
      const s = F.scale;
      if (p.product && p.product !== p.title) type.label(g, F, p.product, t, { y: F.h / 2 - 110 * s, t0: 0.1 });
      type.title(g, F, p.title || '', t, { y: F.h / 2 + 20 * s, t0: 0.3 });
      const tl = p.tagline || p.one_liner;
      if (tl) type.italic(g, F, tl, t, { y: F.h / 2 + 120 * s, t0: 0.9, size: 44 });
    },
    overlayKey: until(3.0),
  }));
defineCine('kit:cinematic/END', 'Pull back out of the corridor until the cards are stars; title, CTA in Geist Mono, URL and credit; last frame holds as the thumbnail.',
  { title: { type: 'string', default: '' }, cta: { type: 'string', default: '', doc: 'e.g. install command' }, url: { type: 'string', default: '' }, credit: { type: 'string', default: 'made with Hermes · Hype' } },
  (ctx, p, r, seed) => ({
    items: corridor(seed), warmAt: [0.5, 0.5],
    cam: (t) => rig([[0, { pos: [0, 0, 2], look: [0, 0, -30], fov: 32 }], [ctx.dur * 0.8, { pos: [0, 0.2, 14], look: [0, 0, -30], fov: 32 }]], t),
    focus: (t) => lerp(5, 14, inOut(t / (ctx.dur * 0.8))),
    overlay: (g, t, F) => {
      const s = F.scale;
      type.title(g, F, p.title || '', t, { y: F.h / 2 - 30 * s, t0: 0.2, k: 0.85 });
      if (p.cta) type.cta(g, F, p.cta, t, { y: F.h / 2 + 70 * s, t0: 0.9 });
      if (p.url) type.label(g, F, p.url, t, { y: F.h / 2 + 150 * s, t0: 1.2, color: type.INK.ash });
      if (p.credit) type.label(g, F, p.credit, t, { y: F.h - F.barH - 40 * s, t0: 1.4, size: 13, color: type.INK.ash });
    },
    overlayKey: until(3.0),
  }));

// ------------------------------------------------------------------------------------- PROBLEM
defineCine('kit:cinematic/PROBLEM', "The user's prompt card alone, frontal, everything else black; the card's emission fades up; near-static.",
  { text: { type: 'string', default: '' }, truncated: { type: 'bool', default: false } },
  (ctx, p, r, seed) => {
    const c = cards.promptCard({ text: p.text + (p.truncated ? ' …' : '') });
    const D = fitDist(cw(c), ch(c), ctx, 0.66);
    return {
      items: [{ card: c, pos: [0, 0, 0], rim: 2.0, halo: 0.07, anim: (t) => ({ exposure: lerp(0.15, 1.05, outCubic(t / 1.2)) }) }, ...ghosts(seed, 4, { dim: 0.18 })],
      register: true, stars: 300, dust: 60, motes: 2,
      cam: (t) => rig([[0, { pos: [0, 0, D * 1.04], look: [0, 0, 0], fov: 30 }], [ctx.dur, { pos: [0, 0, D], look: [0, 0, 0], fov: 30 }]], t),
      focus: () => D,
      overlayKey: until(1.5),
    };
  });

// ------------------------------------------------------------------------------------- PLAN
defineCine('kit:cinematic/PLAN', "The agent's plan card sharp, a constellation of faint cards behind; lateral truck; the active item glows.",
  { items: { type: 'array', default: [] }, more: { type: 'int', default: 0 } },
  (ctx, p, r, seed) => {
    const c = cards.planCard(p);
    const D = fitDist(cw(c), ch(c), ctx, 0.62);
    const act = (c.rows || []).find((x) => x.active);
    const band = act ? [act.y + PAD - 30, act.y + PAD + 30, 1.35] : null;
    return {
      items: [{ card: c, pos: [0, 0, 0], rim: 2.2, halo: 0.08, anim: band ? (t) => ({ band: [band[0], band[1], lerp(1, band[2], outCubic((t - 0.6) / 0.6))] }) : null }, ...ghosts(seed, 10, { dim: 0.4, z0: -4, z1: -20 })],
      register: true,
      cam: (t) => rig([[0, { pos: [-0.35, 0.05, D], look: [-0.1, 0, 0], fov: 30 }], [ctx.dur, { pos: [0.35, -0.02, D * 0.96], look: [0.1, 0, 0], fov: 30 }]], t),
      focus: () => D, overlayKey: until(2),
    };
  });

// ------------------------------------------------------------------------------------- CODE
defineCine('kit:cinematic/CODE', 'Code card at 3/4 with the focus range lit by the amber gutter; rack focus from the path to the focus lines, then push ×1.4.',
  { path: { type: 'string', default: '' }, lang: { type: 'string', default: '' }, lines: { type: 'array', default: [] }, start: { type: 'int', default: 1 }, focus: { type: 'array', default: [] } },
  (ctx, p, r, seed) => {
    const c = cards.codeCard(p);
    const D = fitDist(cw(c), ch(c), ctx, 0.64);
    const fr = (c.rows || []).filter((x) => x.focus);
    const fy = fr.length ? ((fr[0].y + fr[fr.length - 1].y) / 2) : c.h / 2;
    const yW = (ch(c) / 2) - (fy + PAD) / TPU;
    const dur = ctx.dur;
    return {
      items: [{ card: c, pos: [0, 0, 0], rot: [0, -14, 0], rim: 2.2, halo: 0.08 }, ...ghosts(seed, 8, { dim: 0.4 }), ...nearGhosts(seed)],
      register: true,
      cam: (t) => rig([[0, { pos: [0.5, 0.15, D * 1.1], look: [0, 0.1, 0], fov: 30 }], [dur * 0.35, { pos: [0.45, 0.12, D * 1.05], look: [0, 0.05, 0], fov: 30 }],
        [dur, { pos: [0.25, yW * 0.6, D / 1.25], look: [0, yW * 0.75, 0], fov: 30 }]], t),
      focus: (t) => lerp(D * 1.1, D / 1.25, inOut((t - dur * 0.35) / (dur * 0.65))) + (t < 0.6 ? 0.25 * (1 - t / 0.6) : 0),
      overlayKey: until(1.5),
    };
  });

// ------------------------------------------------------------------------------------- DIFF
defineCine('kit:cinematic/DIFF', 'Diff card; − lines dim and struck, + lines warm with the amber gutter; slow 6–8° orbit around the card.',
  { path: { type: 'string', default: '' }, lang: { type: 'string', default: '' }, hunks: { type: 'array', default: [] }, adds: { type: 'int', default: 0 }, dels: { type: 'int', default: 0 }, truncated: { type: 'bool', default: false } },
  (ctx, p, r, seed) => {
    const c = cards.diffCard(p);
    const D = fitDist(cw(c), ch(c), ctx, 0.66);
    return {
      items: [{ card: c, pos: [0, 0, 0], rim: 2.2, halo: 0.09, anim: (t) => ({ exposure: lerp(0.9, 1.08, outCubic(t / 2)) }) }, ...ghosts(seed, 8, { dim: 0.4 }), ...nearGhosts(seed)],
      register: true,
      cam: (t) => { const a = lerp(-0.07, 0.07, inOut(t / ctx.dur)); return rig([[0, { pos: [Math.sin(a) * D, 0.08, Math.cos(a) * D], look: [0, 0, 0], fov: 30 }]], t); },
      focus: () => D, overlayKey: until(1.5),
    };
  });

// ------------------------------------------------------------------------------------- TERMINAL
defineCine('kit:cinematic/TERMINAL', 'A lone terminal card in the dark; push in then hold; the PASS / ✓ line over-exposes so it blooms — the halation is the success beat.',
  { cmd: { type: 'string', default: '' }, output: { type: 'any', default: '' }, exit_code: { type: 'int', default: 0 }, ok: { type: 'bool', default: true }, elapsed_s: { type: 'number', default: null }, tests_passed: { type: 'int', default: null } },
  (ctx, p, r, seed) => {
    const c = cards.terminalCard(p);
    const D = fitDist(cw(c), ch(c), ctx, 0.62);
    const lit = (c.rows || []).filter((x) => x.lit).pop();
    const tLit = Math.min(ctx.dur * 0.45, 1.6);
    return {
      items: [{ card: c, pos: [0, 0, 0], rim: 2.2, halo: 0.08, anim: lit ? (t) => ({ band: [lit.y + PAD - 30, lit.y + PAD + 22, lerp(1, 2.4, clamp((t - tLit) / 0.27))] }) : null },
        ...ghosts(seed, 5, { dim: 0.25 })],
      register: true, cues: [],
      cam: (t) => rig([[0, { pos: [0.1, 0.05, D * 1.25], look: [0, 0, 0], fov: 30 }], [tLit + 0.3, { pos: [0.05, 0.02, D], look: [0, 0, 0], fov: 30 }], [ctx.dur, { pos: [0.03, 0.0, D * 0.97], look: [0, 0, 0], fov: 30 }]], t),
      focus: (t) => lerp(D * 1.25, D, inOut(t / (tLit + 0.3))), overlayKey: until(1.5),
    };
  });

// ------------------------------------------------------------------------------------- MONTAGE
defineCine('kit:cinematic/MONTAGE', 'The tool-call chips at many depths; fast lateral dolly past them with focus snapping chip to chip.',
  { items: { type: 'array', default: [], doc: '[{tool, arg, ...}]' } },
  (ctx, p, r, seed) => {
    const its = (p.items || []).slice(0, 14);
    const items = its.map((it, i) => ({ card: cards.chipCard(it), pos: [-3.2 + (6.4 * (i + 0.5)) / Math.max(1, its.length), (r() - 0.5) * 1.1, -0.5 - r() * 3.0], rot: [0, (r() - 0.5) * 20, 0], scale: 1.1, rim: 2.0, halo: 0.06 }));
    const dur = ctx.dur;
    const camX = (t) => lerp(-3.4, 3.4, t / dur);
    return {
      items: [...items, ...ghosts(seed, 6, { dim: 0.3, z0: -6, z1: -18 })], register: true,
      cam: (t) => rig([[0, { pos: [camX(t), 0.1, 3.2], look: [camX(t) + 0.4, 0, -2], fov: 34 }]], t),
      focus: (t) => {
        if (!items.length) return 4;
        let best = items[0], bd = 1e9; const x = camX(Math.floor(t * 4) / 4 + 0.125) + 0.4;
        for (const it of items) { const d = Math.abs(it.pos[0] - x); if (d < bd) { bd = d; best = it; } }
        return Math.hypot(best.pos[0] - camX(t), best.pos[2] - 3.2);
      },
      overlayKey: until(1),
    };
  });

// ------------------------------------------------------------------------------------- SCREEN / FEATURE / SCROLL / screen-push
function screenScene(ctx, p, r, seed, o = {}) {
  const m = mediaOf(ctx, p.image || {});
  // a game/app picture (image.frame 'card'): no URL bar on the card and no URL line in the lower third
  const url = isCard(p.image) ? '' : (p.image && p.image.url) || p.url || '';
  const full = m.image && (m.h / m.w) > 1.1;
  const viewH = full ? Math.round(Math.min(1600, m.w) * 0.62) : null;
  let scrollU = -1;
  const make = (u) => (m.image ? cards.screenshotCard(m.image, url, { maxW: 1600, viewH: viewH || undefined, scroll: u }) : cards.promptCard({ text: url || p.label || '' }));
  const c = make(0);
  const D = fitDist(cw(c), ch(c), ctx, 0.66);
  const bb = p.bbox || [0.1, 0.1, 0.8, 0.8];
  const bx = (bb[0] + bb[2] / 2 - 0.5) * cw(c) * 0.9, by = -(bb[1] + bb[3] / 2 - 0.5) * ch(c) * 0.9;
  const dur = ctx.dur;
  const scr = p.scroll || null;
  const item = { card: c, pos: [0, 0, 0], exposure: 1.15, rim: 2.2, halo: 0.1,
    anim: (t) => {
      const rot = [0, lerp(-13, -4, inOut(t / (dur * 0.8))), 0];
      if (scr && m.image) {
        const u = lerp(scr[0], scr[1], inOut((t - 0.6) / Math.max(dur - 1.2, 0.5)));
        const q = Math.round(u * 200) / 200;
        if (q !== scrollU) { scrollU = q; const nc = make(q); const g2 = c.cv.getContext('2d'); g2.setTransform(1, 0, 0, 1, 0, 0); g2.clearRect(0, 0, c.cv.width, c.cv.height); g2.drawImage(nc.cv, 0, 0); return { rot, refresh: true }; }
      }
      return { rot };
    } };
  const caption = o.caption ?? p.label ?? '';
  return {
    items: [item, ...ghosts(seed, 8, { dim: 0.38 }), ...nearGhosts(seed)], register: true,
    cam: (t) => rig([[0, { pos: [0.3, 0.05, D * 1.05], look: [0, 0, 0], fov: 30 }], [dur * 0.3, { pos: [0.25, 0.04, D], look: [0, 0, 0], fov: 30 }],
      [dur, { pos: [bx * 0.5, by * 0.5, D / 1.15], look: [bx * 0.6, by * 0.6, 0], fov: 30 }]], t),
    focus: (t) => lerp(D * 1.05, D / 1.15, inOut(t / dur)),
    overlay: (g, t, F) => {
      const s = F.scale, x = F.portrait ? F.w / 2 : 120 * s, align = F.portrait ? 'center' : 'left';
      const yb = (F.portrait ? F.h * 0.72 : F.h - F.barH - 96 * s) - (p._captions ? 140 * s : 0);   // clear the caption band
      if (o.kicker !== false) type.label(g, F, o.kicker || 'Captured · screen', t, { x, y: yb - 64 * s, align, t0: 0.5 });
      if (caption) type.italic(g, F, caption, t, { x, y: yb, align, size: 52, t0: 0.7, maxW: F.w * 0.5 });
      if (url) type.label(g, F, url.replace(/^[a-z]+:\/\//i, ''), t, { x, y: yb + 52 * s, align, size: 13, color: type.INK.ash, t0: 0.9 });
    },
    overlayKey: scr ? undefined : until(2.5),
  };
}
defineCine('kit:cinematic/SCREEN', 'Screenshot card pushed close and sharp, others defocused; 3/4 → frontal swing with a ×1.15 push toward the focus box; lower third: kicker · italic caption · URL.',
  { image: IMAGE_DOC, bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8], doc: 'focus box [x,y,w,h] fractions' } },
  (ctx, p, r, seed) => screenScene(ctx, p, r, seed));
defineCine('kit:cinematic/FEATURE', 'A product feature: the screenshot swings frontal and pushes to the feature box; the feature line as an italic caption.',
  { image: IMAGE_DOC, feature: { type: 'string', default: '' }, bbox: { type: 'array', default: [0.1, 0.1, 0.8, 0.8] }, click: { type: 'any', default: null } },
  (ctx, p, r, seed) => screenScene(ctx, p, r, seed, { caption: p.feature || p.label, kicker: 'Feature' }));
defineCine('kit:cinematic/SCROLL', 'A tall full-page capture scrolls inside its glass card while the camera swings frontal.',
  { image: IMAGE_DOC, scroll: { type: 'array', default: [0, 0.6], doc: '[from, to] page fractions' } },
  (ctx, p, r, seed) => screenScene(ctx, { ...p, scroll: p.scroll || [0, 0.6] }, r, seed));
defineCine('kit:cinematic/screen-push', 'Generic screenshot push: any image asset as a lit glass card, 3/4 → frontal with a push to a box, optional caption/kicker/url.',
  { image: IMAGE_DOC, bbox: { type: 'array', default: [0.25, 0.2, 0.5, 0.5] }, caption: { type: 'string', default: '' }, kicker: { type: 'string', default: 'Captured · screen' }, url: { type: 'string', default: '' } },
  (ctx, p, r, seed) => screenScene(ctx, p, r, seed, { caption: p.caption, kicker: p.kicker }));

// ------------------------------------------------------------------------------------- STATS
defineCine('kit:cinematic/STATS', 'The numbers huge in Cormorant set in the void between two defocused cards; slow fade-in, no counting; camera holds with drift.',
  { stats: { type: 'array', default: [], doc: '[{label, value, display}] <= 4' } },
  (ctx, p, r, seed) => ({
    items: [...ghosts(seed, 2, { dim: 0.5, xMin: 2.2, xSpread: 0.6, z0: -1.5, z1: -2.5, ySpread: 0.4 }), ...ghosts(seed + 7, 8, { dim: 0.25, z0: -8, z1: -20 })],
    cam: (t) => rig([[0, { pos: [0, 0, 6], look: [0, 0, 0], fov: 30 }]], t),
    focus: () => 2.5,
    overlay: (g, t, F) => type.stats(g, F, p.stats || [], t),
    overlayKey: until(3),
  }));

// ------------------------------------------------------------------------------------- BEFORE_AFTER
defineCine('kit:cinematic/BEFORE_AFTER', 'Two cards in depth: "before" far and cold, "after" near and warm; focus racks before → after while one light flare sweeps across.',
  { before: { type: 'content', default: null }, after: { type: 'content', default: null } },
  (ctx, p, r, seed) => {
    const b = contentCard(ctx, p.before || {}), a = contentCard(ctx, p.after || {});
    const D = fitDist(cw(a), ch(a), ctx, 0.5);
    const dur = ctx.dur, tR = dur * 0.45;
    const posB = [-cw(b) * 0.42, 0.1, -1.6], posA = [cw(a) * 0.32, -0.05, 0.2];
    const dist = (q) => Math.hypot(q[0], q[1], q[2] - D);
    return {
      items: [{ card: b, pos: posB, rot: [0, 14, 0], dim: 0.7, exposure: 0.85, rim: 1.6, rimCol: 0xc9d6ea, halo: 0.05 },
        { card: a, pos: posA, rot: [0, -10, 0], exposure: 1.12, rim: 2.4, rimCol: 0xffe2b8, halo: 0.1 }, ...ghosts(seed, 6, { dim: 0.3, z0: -5 })],
      register: true, warmAt: [0.66, 0.48],
      cam: (t) => rig([[0, { pos: [0, 0.05, D], look: [0, 0, -0.6], fov: 32 }], [dur, { pos: [0.15, 0.0, D * 0.94], look: [0.2, 0, -0.2], fov: 32 }]], t),
      focus: (t) => lerp(dist(posB), dist(posA), inOut((t - tR) / 0.8)),
      flare: (t) => ({ k: 1.4 * Math.max(0, Math.sin(Math.PI * clamp((t - tR) / 0.5))), at: [lerp(0.1, 0.9, clamp((t - tR) / 0.5)), 0.5] }),
      overlay: (g, t, F) => {
        const s = F.scale;
        type.label(g, F, 'Before', t, { x: F.w * 0.22, y: F.barH + 70 * s, t0: 0.3, alpha: 1 - clamp((t - tR) / 0.6) * 0.6 });
        type.label(g, F, 'After', t, { x: F.w * 0.74, y: F.barH + 70 * s, t0: tR, color: type.INK.accent });
      },
      overlayKey: until(tR + 1.5),
    };
  });

// ------------------------------------------------------------------------------------- CALLOUT
defineCine('kit:cinematic/CALLOUT', 'White Cormorant italic quote centred in black, the source card a faint glow behind; the longest hold, no camera move.',
  { text: { type: 'string', default: '' }, who: { type: 'string', default: '' }, ref: { type: 'any', default: null } },
  (ctx, p, r, seed) => ({
    items: ghosts(seed, 3, { dim: 0.22, xMin: 0.2, xSpread: 1.5, z0: -6, z1: -9 }), stars: 300, dust: 50, motes: 0,
    cam: (t) => rig([[0, { pos: [0, 0, 6], look: [0, 0, 0], fov: 30 }]], t, { breath: 0.5 }),
    focus: () => 6,
    overlay: (g, t, F) => {
      const s = F.scale;
      const hq = type.italic(g, F, `“${p.text || ''}”`, t, { y: F.h / 2 - 20 * s, size: F.portrait ? 72 : 64, t0: 0.3, maxW: F.w * (F.portrait ? 0.82 : 0.6) });
      if (p.who) type.label(g, F, `— ${p.who}`, t, { y: F.h / 2 + hq + 10 * s, t0: 1.0 });
    },
    overlayKey: until(2.5),
  }));

// ------------------------------------------------------------------------------------- card-field (generic)
defineCine('kit:cinematic/card-field', 'Generic cards-in-depth world from any real content: the hero card lit and sharp, the rest at depth; the camera travels (dolly | truck | orbit) and racks focus; optional title.',
  { cards: { type: 'array', default: [], doc: '[{kind: code|diff|terminal|plan|prompt|image|chip, ...data}]' }, hero: { type: 'int', default: 0 },
    move: { type: 'enum', values: ['dolly', 'truck', 'orbit'], default: 'dolly' }, title: { type: 'string', default: '' }, tagline: { type: 'string', default: '' } },
  (ctx, p, r, seed) => {
    const list = (p.cards || []).slice(0, 12).map((d) => (d.kind === 'chip' ? cards.chipCard(d) : contentCard(ctx, d)));
    const hi = clamp(p.hero || 0, 0, Math.max(0, list.length - 1));
    const items = list.map((c, i) => (i === hi ? { card: c, pos: [0, 0, 0], exposure: 1.1, rim: 2.4, halo: 0.1 }
      : { card: c, pos: [(i % 2 ? 1 : -1) * (1.6 + r() * 2.2), (r() - 0.5) * 1.6, -1.5 - r() * 9], rot: [0, (i % 2 ? -1 : 1) * (12 + r() * 25), 0], dim: 0.75, rim: 2.0, halo: 0.07 }));
    if (items.length < 8) items.push(...ghosts(seed, 8 - items.length, { dim: 0.4 }));
    const hc = list[hi] || cards.ghostCard(r);
    const D = fitDist(cw(hc), ch(hc), ctx, 0.6);
    const dur = ctx.dur;
    const cam = {
      dolly: (t) => rig([[0, { pos: [0.4, 0.15, D * 1.6], look: [0, 0, 0], fov: 30 }], [dur, { pos: [0.1, 0.05, D], look: [0, 0, 0], fov: 30 }]], t),
      truck: (t) => rig([[0, { pos: [-1.2, 0.1, D * 1.1], look: [-0.4, 0, 0], fov: 30 }], [dur, { pos: [1.2, 0.0, D * 1.05], look: [0.4, 0, 0], fov: 30 }]], t),
      orbit: (t) => { const a = lerp(-0.35, 0.25, inOut(t / dur)); return rig([[0, { pos: [Math.sin(a) * D * 1.2, 0.1, Math.cos(a) * D * 1.2], look: [0, 0, 0], fov: 30 }]], t); },
    }[p.move] || null;
    return {
      items: [...items, ...nearGhosts(seed)], register: !p.title,
      cam: cam || ((t) => rig([[0, { pos: [0, 0, D], look: [0, 0, 0], fov: 30 }]], t)),
      focus: (t) => { const c = (cam || (() => ({ pos: [0, 0, D] })))(t); return Math.hypot(...c.pos); },
      overlay: (g, t, F) => {
        if (p.title) type.title(g, F, p.title, t, { y: F.h / 2 + 20 * F.scale, k: 0.8 });
        if (p.tagline) type.italic(g, F, p.tagline, t, { y: F.h / 2 + 110 * F.scale, size: 44, t0: 0.9 });
      },
      overlayKey: until(3),
    };
  });

sr.defineScene('kit:cinematic/lockup', {
  layer: '2d',
  describe: 'End-title lockup OVERLAY (transparent): product name in wide-tracked Cormorant caps rising letter by letter with a light sweep, an accent hairline, an italic tagline and a CTA pill with an arrow; soft scrim for bright pictures. Put it in film.overlays over a product shot (e.g. kit:nature/product-hero with title "top").',
  params: LOCKUP_PARAMS,
  render(ctx, t, p) { drawLockup(ctx, t, p); },
});

if (typeof sr.defineKit === 'function') sr.defineKit('cinematic', { cards, makeCine, rig, type, drawLockup });
