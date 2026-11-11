// Hype kit "terminal" — the tube: every kit:terminal scene is a DOM scene on the base frame (reference px at a
// 1080 short side) with the phosphor theme, a screen layer that powers on/off like a CRT, CSS scanlines, a slow
// roll bar and a 2-3 % brightness flicker (the only "camera": a CRT never parks because the tube itself breathes).
// Wide halation, curvature and misconvergence are the ffmpeg `crt` post chain (kit.json "style.post").

import { defineDomScene } from '../base/scene.js';
import { COMMON } from '../base/scenes-panels.js';
import { h, css } from '../base/dom.js';
import { seg, ease, clamp, lerp } from '../base/motion.js';
import { lineH, sp, len, pad, customPhosphor, phosphorVars } from './crt.js';

/** Params every terminal scene accepts (on top of the base COMMON ones). */
export const TCOMMON = {
  ...COMMON,
  theme: { type: 'string', default: 'terminal', doc: 'theme (terminal: amber P3 tokens; kit:base scenes re-skin with it too)' },
  phosphor: { type: 'string', default: 'p3', doc: 'p3 (amber, default) | p1 (green); one phosphor per film' },
  power_on: { type: 'bool', default: null, doc: 'tube powers on at the start of the shot (null = scene default: HOOK on)' },
  power_off: { type: 'bool', default: null, doc: 'tube switches off in the last 0.45 s (null = scene default: END on)' },
};

/** Content box (reference px) that clears the tube curvature, the safe area and (when up) the caption band. */
export function margins(F) {
  if (F.portrait) return { l: 120, r: 120, t: 232, b: F.caps ? 500 : 420 };
  return { l: 150, r: 150, t: 70, b: F.caps ? 200 : 124 };
}

/**
 * Register a terminal scene. def.build(ctx, p, F, T) -> {render(t), cues}; T = tube helpers:
 * {scr, M, W, H, pre(x, y, fs, cls), disp(x, y, size), bar(tag, right), barSet(tag, right), power}.
 */
export function tubeScene(id, def) {
  defineDomScene(id, {
    describe: def.describe,
    params: { ...TCOMMON, ...(def.params || {}) },
    build(ctx, p, F) {
      if (String(p.phosphor || 'p3').toLowerCase() === 'p1') F.el.classList.add('tm-p1');
      const cp = /^#/.test(String(p.phosphor || '')) ? customPhosphor(p.phosphor) : null;   // customization: any hex
      if (cp) for (const [k, v] of Object.entries(phosphorVars(cp))) F.el.style.setProperty(k, v);
      const T = tube(ctx, p, F, def);
      const s = def.build(ctx, p, F, T) || {};
      return {
        cues: [...(s.cues || []), ...T.cues],
        render(t) { s.render && s.render(t); T.update(t); },
      };
    },
  });
}

function tube(ctx, p, F, def) {
  const W = F.W, H = F.H, M = margins(F);
  const scr = h('div', 'tm-scr');
  scr.style.cssText = `width:${W}px;height:${H}px;`;
  F.cam.appendChild(scr);
  const scan = h('div', 'tm-scan'), roll = h('div', 'tm-roll'), flick = h('div', 'tm-flick'), beam = h('div', 'tm-beam');
  const warm = h('div', 'tm-warm');        // power-on warm-up glow of the phosphor (fades in the first 0.5 s)
  F.ov.append(roll, scan, flick, warm, beam);
  const dur = Number(ctx.dur) || 4;
  const powerOn = p.power_on ?? def.powerOn ?? false;
  const powerOff = p.power_off ?? def.powerOff ?? false;
  const offAt = dur - 0.45;
  const phase = (String(ctx.id || '').length * 0.137) % 1;
  const cues = [];
  if (powerOn) cues.push({ t: 0.02, sfx: 'hero', gain_db: -10 });
  if (powerOff) cues.push({ t: offAt + 0.02, sfx: 'cut', gain_db: -8 });

  /** A <pre> on the character grid at (x, y) reference px; set(html) only touches the DOM when html changes. */
  function pre(x, y, fs, cls = '') {
    const el = h('pre', 'tm-pre' + (cls ? ' ' + cls : ''));
    el.style.cssText = `left:${Math.round(x)}px;top:${Math.round(y)}px;font-size:${fs}px;line-height:${lineH(fs)}px;`;
    scr.appendChild(el);
    el.set = (html) => { if (el.__html !== html) { el.__html = html; el.innerHTML = html; } };
    return el;
  }
  /** Mount an existing element (a pane's <pre>) on the grid at (x, y) with font size fs. */
  function mount(el, x, y, fs, parent = scr) {
    el.classList.add('tm-pre');
    el.style.cssText = `left:${Math.round(x)}px;top:${Math.round(y)}px;font-size:${fs}px;line-height:${lineH(fs)}px;transform-origin:0 0;`;
    parent.appendChild(el);
    return el;
  }
  /** A full-frame layer clipped to the rows of box B (zoomed panes stay under the status line, above captions). */
  function clip(B, pad = 8) {
    const el = h('div', '');
    el.style.cssText = `position:absolute;left:0;top:0;width:${W}px;height:${H}px;` +
      `clip-path:inset(${Math.max(0, B.y - pad)}px 0 ${Math.max(0, H - B.y - B.h - pad)}px 0);`;
    scr.appendChild(el);
    return el;
  }
  /** VT323 display text block. */
  function disp(x, y, size, cls = '') {
    const el = h('div', 'tm-disp' + (cls ? ' ' + cls : ''));
    el.style.cssText = `left:${Math.round(x)}px;top:${Math.round(y)}px;font-size:${size}px;line-height:1;`;
    scr.appendChild(el);
    el.set = (html) => { if (el.__html !== html) { el.__html = html; el.innerHTML = html; } };
    return el;
  }
  /** Status line at the top of the content box: inverse tag left, dim text right. */
  const barFs = F.portrait ? 26 : 24;
  const barCols = Math.floor((W - M.l - M.r) / (barFs * 0.6));
  const barEl = pre(M.l, F.portrait ? M.t - 6 : M.t - 2, barFs);   // 9:16: below the platform UI band (safe top 220)
  function barHtml(tag, right) {
    const tg = tag ? ` ${String(tag).toUpperCase()} ` : '';
    const rt = String(right || '');
    const gap = Math.max(1, barCols - len(tg) - len(rt));
    return (tg ? sp('i', tg) : '') + ' '.repeat(gap) + sp('d', rt.length > barCols - len(tg) - 2 ? rt.slice(0, Math.max(0, barCols - len(tg) - 3)) + '\u2026' : rt);
  }
  const bar = (tag, right) => barEl.set(barHtml(tag, right));

  function update(t) {
    // brightness flicker (2-3 %) and the slow roll bar: pure functions of t
    const fl = 0.018 + 0.012 * (0.5 + 0.5 * Math.sin(t * 47.3 + phase * 9)) * (0.6 + 0.4 * Math.sin(t * 7.1));
    css(flick, { opacity: fl.toFixed(4) });
    const ry = (((t * 0.085 + phase) % 1.5) - 0.35) * H;
    css(roll, { transform: `translate3d(0,${ry.toFixed(1)}px,0)` });
    // power on (warm): the picture is up from the first frame, over-bright and slightly squashed, while a raster
    // line sweeps the glass top -> bottom; then the degauss wobble. Frame 0 is the film's thumbnail (the X poster),
    // so the tube never opens dark (the old dot -> line -> picture start made frame 0 black: luma 3.8).
    let sx = 1, sy = 1, br = 1, dx = 0, beamOp = 0, bw = 0, bh = 0, by = H / 2, warmOp = 0;
    if (powerOn && t < 0.75) {
      const c = seg(t, -0.04, 0.3, ease.outCubic), u = seg(t, -0.02, 0.32, ease.inOutQuad);
      sx = lerp(0.985, 1, c); sy = lerp(0.9, 1, c); br = lerp(1.9, 1, seg(t, 0, 0.5, ease.outCubic));
      beamOp = 0.9 * (1 - seg(t, 0.28, 0.4)); warmOp = 1 - seg(t, 0.05, 0.55, ease.outCubic);
      bw = W * 0.94; bh = 10; by = lerp(H * 0.07, H * 0.93, u);
      dx = t > 0.32 ? Math.sin((t - 0.32) * 70) * 6 * Math.exp(-(t - 0.32) * 9) : 0;
    }
    if (powerOff && t > offAt) {
      const a = seg(t, offAt, offAt + 0.14, ease.inCubic), b = seg(t, offAt + 0.12, offAt + 0.26, ease.inCubic);
      sy = lerp(1, 0.004, a); sx = 1 - b; br = lerp(1, 3.5, a);
      beamOp = seg(t, offAt + 0.1, offAt + 0.16) * (1 - seg(t, offAt + 0.26, offAt + 0.45));
      bw = lerp(W * 0.9, 10, b); bh = lerp(6, 10, b); by = H / 2;
    }
    const on = sx > 0.0005 && sy > 0.0005;
    css(scr, {
      transform: `translate3d(${dx.toFixed(2)}px,0,0) scale(${Math.max(0.0001, sx).toFixed(4)},${Math.max(0.0001, sy).toFixed(4)})`,
      filter: br > 1.01 ? `brightness(${br.toFixed(3)})` : 'none', visibility: on ? 'visible' : 'hidden',
    });
    css(warm, { opacity: clamp(warmOp).toFixed(3) });
    css(beam, { opacity: clamp(beamOp).toFixed(3), left: `${(W / 2 - bw / 2).toFixed(1)}px`, top: `${(by - bh / 2).toFixed(1)}px`,
      width: `${bw.toFixed(1)}px`, height: `${bh.toFixed(1)}px` });
  }
  return { scr, M, W, H, pre, mount, clip, disp, bar, barHtml, barCols, barEl, update, cues, pad };
}
