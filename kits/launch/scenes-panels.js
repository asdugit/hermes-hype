// Showreel kit "launch" — panel scenes on the table: PROBLEM, PLAN, CODE, DIFF, TERMINAL.

import { launchScene, camTrack, fitRect, nodeIn, pushTrack, panelWires, backdropPanel } from './stage.js';
import { codeBlock, diffBlock } from '../base/code.js';
import { termBlock, termFont, termWidth } from '../base/term.js';
import { chatBlock, planBlock } from '../base/cards.js';
import { clamp, lerp, seg, ease } from '../base/motion.js';

// ------------------------------------------------------------------------------------- CODE
launchScene('kit:launch/CODE', {
  describe: 'Editor panel lying on the lit table; the file streams in, the camera dollies from a low angle onto the focus lines.',
  params: {
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language' },
    lines: { type: 'array', default: [], doc: '<= 18 verbatim lines' }, start: { type: 'int', default: 1, doc: 'first line number' },
    focus: { type: 'array', default: [1, 1], doc: '[a, b] focus lines' },
  },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const reveal = [0.25, clamp(dur * 0.5, 1.2, 3.4)];
    const b = codeBlock(p, { width: L ? 980 : 1540, fontSize: L ? 26 : 27, reveal, focusAt: reveal[1] + 0.1 });
    const n = W.node(b.el, { x: 0, y: b.h / 2, z: 36, w: b.w, h: b.h });
    W.light(0, -40, b.w * 1.1, b.h * 1.3);
    const fr = b.focusRect();
    const wires = panelWires(W, n, b, fr.y + fr.h / 2, { outAt: reveal[1] + 0.4 });
    const cam = pushTrack(W, F, n, b, fr, { tPush: reveal[1] + 0.15, dur, yaw0: 6, pitchWide: 20 });
    return {
      cues: [...b.cues, { t: reveal[1] + 0.2, sfx: 'move', gain_db: -12 }],
      render(t) {
        b.update(t);
        const u = nodeIn(t);
        W.update(n, { z: lerp(160, 36, u), op: clamp(u * 2) });
        for (const w of wires) w.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- DIFF
launchScene('kit:launch/DIFF', {
  describe: 'Diff on paper: rows wipe in, adds sweep the lime highlighter, deletions strike in grey; camera pushes onto the change, pulses carry it on.',
  params: {
    path: { type: 'string', default: '', doc: 'file path' }, lang: { type: 'string', default: '', doc: 'language' },
    hunks: { type: 'array', default: [], doc: '[{header, lines:[[op,text]]}] <= 24 rows' },
    adds: { type: 'int', default: 0, doc: 'lines added' }, dels: { type: 'int', default: 0, doc: 'lines removed' },
  },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const rows = (p.hunks || []).reduce((a, hk) => a + 1 + (hk.lines || []).length, 0);
    const reveal = [0.2, clamp(0.2 + rows * 0.085, 0.9, dur * 0.45)];
    const b = diffBlock(p, { width: L ? 980 : 1540, fontSize: L ? 26 : 27, reveal });
    const n = W.node(b.el, { x: 0, y: b.h / 2, z: 36, w: b.w, h: b.h });
    W.light(0, -30, b.w * 1.1, b.h * 1.3);
    const cr = b.changedRect(L ? 12 : 9);
    const wires = panelWires(W, n, b, cr.y + cr.h / 2, { outAt: reveal[1] + 0.3 });
    const cam = pushTrack(W, F, n, b, cr, { tPush: reveal[1] + 0.2, dur, yaw0: -6, pitchWide: 18 });
    return {
      cues: [...b.cues, { t: reveal[1] + 0.25, sfx: 'move', gain_db: -12 }],
      render(t) {
        b.update(t);
        const u = nodeIn(t);
        W.update(n, { z: lerp(160, 36, u), op: clamp(u * 2) });
        for (const w of wires) w.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- TERMINAL
launchScene('kit:launch/TERMINAL', {
  describe: 'The one dark panel, tilted up off the table: command types, output streams, PASS badge pops with glow; slow 6-degree orbit.',
  params: {
    cmd: { type: 'string', default: '', doc: 'command' }, output: { type: 'array', default: [], doc: '<= 12 lines' },
    truncated_top: { type: 'bool', default: false, doc: 'output cut at the top' }, exit_code: { type: 'int', default: null, doc: 'exit code' },
    elapsed_s: { type: 'number', default: null, doc: 'seconds' }, ok: { type: 'bool', default: true, doc: 'succeeded' },
    tests_passed: { type: 'bool', default: false, doc: 'PASS badge + chime' },
  },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const fs = termFont(p, L);
    const width = termWidth(p, fs, L);
    const typeAt = [0.25, 0.25 + clamp(String(p.cmd || '').length * 0.032, 0.35, 1.1)];
    const nOut = (p.output || []).length;
    const streamAt = [typeAt[1] + 0.2, typeAt[1] + 0.2 + clamp(nOut * 0.12, 0.2, 1.6)];
    const syncPass = Number(p._sync && p._sync.pass);
    const badgeAt = Number.isFinite(syncPass) && syncPass >= streamAt[1] && syncPass < dur - 0.5 ? syncPass : Math.min(streamAt[1] + 0.2, Math.max(streamAt[1], dur - 1.1));
    const b = termBlock(p, { width, fontSize: fs, typeAt, streamAt, badgeAt, wrap: L, maxRows: L ? 18 : 14 });
    const n = W.node(b.el, { x: 0, y: 0, z: 50, w: b.w, h: b.h, tilt: 40 });
    W.light(0, -b.h * 0.4, b.w * 1.2, b.h * 1.5);
    const foot = W.nodePoint(n, b.w, b.h);
    const wire = W.wire([[foot[0] + 20, foot[1] - 10], [foot[0] + 320, foot[1] - 10], [foot[0] + 320, foot[1] - 1400], [foot[0] + 3400, foot[1] - 1400]],
      { pulseStart: badgeAt, every: 0.9, draw: [0, 0.6] });
    const c = W.nodePoint(n, b.w / 2, b.h / 2);
    const d = fitRect(W, F, b.w, b.h, 8, 0.82, 0.74);
    const cam = camTrack([
      [0, { target: [c[0], c[1], c[2]], dist: d * 1.12, yaw: -7, pitch: 58, roll: -1.2 }],
      [dur + 0.5, { target: [c[0], c[1] + 30, c[2] - 20], dist: d * 0.95, yaw: 5, pitch: 50, roll: 0.6 }],
    ]);
    return {
      cues: b.cues,
      render(t) {
        b.update(t);
        const u = nodeIn(t);
        W.update(n, { tilt: lerp(8, 40, u), z: lerp(120, 50, u), op: clamp(u * 2) });
        wire.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- PROBLEM
launchScene('kit:launch/PROBLEM', {
  describe: "The user's prompt as a chat card on the table; letters type in (human input) while the camera pushes 1.0 -> 1.4x.",
  params: { text: { type: 'string', default: '', doc: 'verbatim prompt' }, truncated: { type: 'bool', default: false, doc: 'ellipsis' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const width = L ? 920 : 1400;
    const len = String(p.text || '').length;
    const typeAt = [0.35, Math.max(0.9, Math.min(dur * 0.62, 0.35 + len * 0.045))];
    const b = chatBlock(p, { width, maxLines: L ? 9 : 5, typeAt });
    // the product the ask is about, as a defocused echo on the table (fills the tall frame in 9:16)
    const bd = backdropPanel(ctx, W, F, p, { x: L ? 60 : 420, y: L ? -b.h * 0.9 : -40, width: L ? 1400 : 1700, rz: L ? -4 : 6, op: 0.34, scrim: 0, tilt: 0, blur: 8 });
    const n = W.node(b.el, { x: 0, y: b.h / 2, z: 34, w: b.w, h: b.h });
    W.light(0, -20, b.w * 1.2, b.h * 1.8);
    const q0 = W.nodePoint(n, 0, b.h * 0.5);
    const wire = W.wire([[q0[0] - 16, q0[1]], [q0[0] - 420, q0[1]], [q0[0] - 420, q0[1] + 900], [q0[0] - 3200, q0[1] + 900]], { pulseStart: typeAt[1], every: 1.2 });
    const c = W.nodePoint(n, b.w / 2, b.h / 2);
    const d = fitRect(W, F, b.w, b.h, 22, 0.84, 0.7);
    const cam = camTrack([
      [0, { target: c, dist: d * 1.12, yaw: -2, pitch: 20, roll: -0.8 }],
      [dur + 0.5, { target: [c[0], c[1] + b.h * 0.12, c[2]], dist: d * 0.82, yaw: 1, pitch: 12, roll: 0 }],
    ]);
    return {
      cues: b.cues,
      render(t) {
        b.update(t);
        if (bd) bd.set(t);
        const u = nodeIn(t);
        W.update(n, { z: lerp(140, 34, u), op: clamp(u * 2) });
        wire.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
      },
    };
  },
});

// ------------------------------------------------------------------------------------- PLAN
launchScene('kit:launch/PLAN', {
  describe: 'Checklist card on the table: done items tick in on the beat, the active item spins; camera drifts down the list.',
  params: { items: { type: 'array', default: [], doc: '[{text, status}] <= 6' }, more: { type: 'int', default: 0, doc: 'hidden items' } },
  build(ctx, p, F, W) {
    const dur = ctx.dur, L = F.portrait;
    const b = planBlock(p, { width: L ? 920 : 1200, rowH: L ? 104 : 96, tickEvery: Math.min(0.5, (dur * 0.55) / Math.max(1, (p.items || []).length)) });
    const bd = backdropPanel(ctx, W, F, p, { x: L ? -60 : -460, y: L ? -b.h * 0.75 : -40, width: L ? 1400 : 1700, rz: L ? 5 : -6, op: 0.34, scrim: 0, tilt: 0, blur: 8 });
    const n = W.node(b.el, { x: 0, y: b.h / 2, z: 34, w: b.w, h: b.h });
    W.light(0, 0, b.w * 1.3, b.h * 1.5);
    const p0 = W.nodePoint(n, b.w, b.top0 + b.rowH * 0.5);
    const wire = W.wire([[p0[0] + 16, p0[1]], [p0[0] + 380, p0[1]], [p0[0] + 380, p0[1] - 900], [p0[0] + 3200, p0[1] - 900]], { pulseStart: 0.6, every: 1.0 });
    const top = W.nodePoint(n, b.w / 2, b.h * 0.3), bot = W.nodePoint(n, b.w / 2, b.h * 0.7);
    const d = fitRect(W, F, b.w, b.h, 22, L ? 0.94 : 0.8, 0.82);
    const cam = camTrack([
      [0, { target: top, dist: d * 1.05, yaw: 2, pitch: 20, roll: 0.8 }],
      [dur + 0.5, { target: bot, dist: d * 0.9, yaw: -1, pitch: 13, roll: -0.4 }],
    ]);
    return {
      cues: b.cues,
      render(t) {
        if (bd) bd.set(t);
        b.update(t);
        const u = nodeIn(t);
        W.update(n, { z: lerp(140, 34, u), op: clamp(u * 2) });
        wire.set(t);
        W.camera(t, { ...cam(t), lift: F.caps ? 50 : 0 });
      },
    };
  },
});

export { seg, ease };
