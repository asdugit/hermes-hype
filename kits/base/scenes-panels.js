// Showreel kits/base — panel scenes: PROBLEM, PLAN, CODE, DIFF, TERMINAL (flat 2.5D, theme tokens only).

import { defineDomScene, flatCam, place, fitZoom, centerBox } from './scene.js';
import { css } from './dom.js';
import { seg, ease, pchip, clamp, lerp } from './motion.js';
import { codeBlock, diffBlock } from './code.js';
import { termBlock, termFont, termWidth } from './term.js';
import { chatBlock, planBlock } from './cards.js';

export const COMMON = {
  theme: { type: 'string', default: 'base', doc: 'theme registered by a style kit (CSS tokens on .sr-theme-<name>)' },
  label: { type: 'string', default: '', doc: 'storyboard label (<= 6 words); some scenes show it as a headline' },
  _captions: { type: 'bool', default: false, doc: 'captions are up in this shot: content lifts clear of the caption band' },
};

/** Panel entrance (tilt up out of a soft blur), starting before t=0 so frame 0 is already in motion. */
export function panelIn(el, t, t0 = -0.25, dur = 0.85, o = {}) {
  const u = seg(t, t0, t0 + dur, ease.outQuint);
  const b = (1 - u) * (o.blur ?? 8);
  css(el, { transform: `perspective(2400px) translate3d(0,${((1 - u) * (o.rise ?? 60)).toFixed(2)}px,0) rotateX(${((1 - u) * (o.tilt ?? 14)).toFixed(3)}deg) scale(${(1 - (1 - u) * 0.05).toFixed(4)})`,
    transformOrigin: '50% 100%', opacity: clamp(u * 2.2).toFixed(3), filter: b > 0.05 ? `blur(${b.toFixed(2)}px)` : 'none' });
  return u;
}

// ------------------------------------------------------------------------------------- PROBLEM
defineDomScene('kit:base/PROBLEM', {
  describe: "The user's request as a chat card; the prompt types in letter by letter (human input) under a slow push.",
  params: { ...COMMON, text: { type: 'string', default: '', doc: 'verbatim prompt (redacted)' }, truncated: { type: 'bool', default: false, doc: 'adds an ellipsis' } },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const width = F.portrait ? 900 : 1360;
    const len = String(p.text || '').length;
    const typeAt = [0.35, Math.max(0.9, Math.min(dur * 0.62, 0.35 + len * 0.045))];
    const b = chatBlock(p, { width, maxLines: F.portrait ? 9 : 5, typeAt });
    b.el.style.position = 'relative';
    centerBox(F).appendChild(b.el);
    const bh = b.h;
    const z0 = Math.min(1, fitZoom(F, width, bh, 0.95));
    return {
      cues: b.cues,
      render(t) {
        b.update(t);
        panelIn(b.el, t);
        const u = seg(t, 0, dur, ease.inOutCubic);
        flatCam(F, t, F.W / 2, F.H / 2 + lerp(0, bh * 0.08, u), z0 * lerp(1.0, 1.1, u), { lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- PLAN
defineDomScene('kit:base/PLAN', {
  describe: "The agent's plan as a checklist card: done items tick in, the active item spins with a highlighter sweep.",
  params: { ...COMMON, items: { type: 'array', default: [], doc: '[{text, status}] <= 6 (status: completed|in_progress|pending)' }, more: { type: 'int', default: 0, doc: 'hidden items count' } },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const width = F.portrait ? 900 : 1180;
    const b = planBlock(p, { width, rowH: F.portrait ? 100 : 92, tickEvery: Math.min(0.5, (dur * 0.55) / Math.max(1, (p.items || []).length)) });
    F.cam.appendChild(b.el);
    place(b.el, (F.W - width) / 2, (F.H - b.h) / 2);
    const z0 = Math.min(1.15, fitZoom(F, width, b.h, 0.9));
    return {
      cues: b.cues,
      render(t) {
        b.update(t);
        panelIn(b.el, t);
        const u = seg(t, 0.3, dur, ease.inOutCubic);
        flatCam(F, t, F.W / 2, F.H / 2 + lerp(-b.h * 0.08, b.h * 0.08, u), z0 * lerp(1, 1.06, u), { lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- CODE
defineDomScene('kit:base/CODE', {
  describe: 'Editor panel: the real file streams in word by word, then the camera pushes to the focus lines and holds.',
  params: {
    ...COMMON,
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    lines: { type: 'array', default: [], doc: '<= 18 verbatim lines' }, start: { type: 'int', default: 1, doc: 'first line number' },
    focus: { type: 'array', default: [1, 1], doc: '[a, b] focus line numbers' },
  },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const width = F.portrait ? 980 : 1520;
    const reveal = [0.25, clamp(dur * 0.5, 1.2, 3.4)];
    const b = codeBlock(p, { width, fontSize: F.portrait ? 26 : 27, reveal, focusAt: reveal[1] + 0.1 });
    F.cam.appendChild(b.el);
    const x = (F.W - width) / 2, y = (F.H - b.h) / 2;
    place(b.el, x, y);
    const zw = Math.min(1, fitZoom(F, width, b.h, 0.96));
    const fr = b.focusRect();
    const zp = clamp(Math.min((F.H * 0.56) / fr.h, F.portrait ? 1.3 : 1.55), zw * 1.2, 1.9);
    // keep the code's left edge at the safe margin when pushed (long lines may run off the right)
    const cxP = Math.min(x + (F.W / 2 - F.safe.l + 10) / zp, x + width / 2);
    const cyP = y + fr.y + fr.h / 2;
    const tp = reveal[1] + 0.15;
    const cam = pchip([[0, [F.W / 2, F.H / 2, zw]], [tp, [F.W / 2, F.H / 2 + 6, zw * 1.02]], [tp + 0.75, [cxP, cyP, zp]], [dur + 1, [cxP + 6, cyP + 8, zp * 1.02]]]);
    return {
      cues: [...b.cues, { t: tp + 0.05, sfx: 'move', gain_db: -12 }],
      render(t) {
        b.update(t);
        panelIn(b.el, t);
        const [cx, cy, z] = cam(t);
        flatCam(F, t, cx, cy, z, { lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- DIFF
defineDomScene('kit:base/DIFF', {
  describe: 'Diff panel: rows wipe in, deletions strike through, additions sweep an accent highlighter; camera pushes to the change.',
  params: {
    ...COMMON,
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language id' },
    hunks: { type: 'array', default: [], doc: '[{header, lines:[[op, text]]}] <= 24 rows' },
    adds: { type: 'int', default: 0, doc: 'lines added' }, dels: { type: 'int', default: 0, doc: 'lines removed' },
  },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const width = F.portrait ? 980 : 1520;
    const b0rows = (p.hunks || []).reduce((a, hk) => a + 1 + (hk.lines || []).length, 0);
    const reveal = [0.25, clamp(0.25 + b0rows * 0.085, 0.9, dur * 0.45)];
    const b = diffBlock(p, { width, fontSize: F.portrait ? 25 : 27, reveal });
    F.cam.appendChild(b.el);
    const x = (F.W - width) / 2, y = (F.H - b.h) / 2;
    place(b.el, x, y);
    const zw = Math.min(1, fitZoom(F, width, b.h, 0.96));
    const cr = b.changedRect(F.portrait ? 12 : 9);
    const zp = clamp(Math.min((F.H * 0.6) / cr.h, F.portrait ? 1.25 : 1.5), zw * 1.2, 1.9);
    const cxP = Math.min(x + (F.W / 2 - F.safe.l + 10) / zp, x + width / 2);
    const cyP = y + cr.y + cr.h / 2;
    const tp = reveal[1] + 0.2;
    const cam = pchip([[0, [F.W / 2, F.H / 2, zw]], [tp, [F.W / 2, F.H / 2 + 6, zw * 1.02]], [tp + 0.7, [cxP, cyP, zp]], [dur + 1, [cxP + 6, cyP + 6, zp * 1.02]]]);
    return {
      cues: [...b.cues, { t: tp + 0.05, sfx: 'move', gain_db: -12 }],
      render(t) {
        b.update(t);
        panelIn(b.el, t);
        const [cx, cy, z] = cam(t);
        flatCam(F, t, cx, cy, z, { lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- TERMINAL
defineDomScene('kit:base/TERMINAL', {
  describe: 'Dark terminal panel: the command types, output streams line by line, a PASS / exit badge pops.',
  params: {
    ...COMMON,
    cmd: { type: 'string', default: '', doc: 'command line' }, output: { type: 'array', default: [], doc: '<= 12 output lines' },
    truncated_top: { type: 'bool', default: false, doc: 'output was cut at the top' }, exit_code: { type: 'int', default: null, doc: 'exit code' },
    elapsed_s: { type: 'number', default: null, doc: 'runtime seconds' }, ok: { type: 'bool', default: true, doc: 'run succeeded' },
    tests_passed: { type: 'bool', default: false, doc: 'shows the PASS badge + chime' },
  },
  build(ctx, p, F) {
    const dur = ctx.dur;
    const fsT = termFont(p, F.portrait);
    const width = termWidth(p, fsT, F.portrait);
    const cmdLen = String(p.cmd || '').length;
    const typeAt = [0.25, 0.25 + clamp(cmdLen * 0.032, 0.35, 1.1)];
    const nOut = (p.output || []).length;
    const streamAt = [typeAt[1] + 0.2, typeAt[1] + 0.2 + clamp(nOut * 0.12, 0.2, 1.6)];
    const badgeAt = Math.min(streamAt[1] + 0.2, Math.max(streamAt[1], dur - 1.1));
    const b = termBlock(p, { width, fontSize: fsT, typeAt, streamAt, badgeAt, wrap: F.portrait, maxRows: F.portrait ? 18 : 14 });
    F.cam.appendChild(b.el);
    const x = (F.W - width) / 2, y = (F.H - b.h) / 2;
    place(b.el, x, y);
    const zw = Math.min(1.12, fitZoom(F, width, b.h, 0.92));
    return {
      cues: b.cues,
      render(t) {
        b.update(t);
        panelIn(b.el, t);
        const u = seg(t, 0, dur, ease.inOutCubic);
        flatCam(F, t, F.W / 2, F.H / 2 + lerp(-10, b.h * 0.12, u), zw * lerp(1, 1.08, u), { roll: lerp(-0.4, 0.3, u), lift: F.caps ? 50 : 0 });
      },
    };
  },
});
