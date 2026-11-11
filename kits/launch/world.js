// Hype kit "launch" — the lit graphite table world: a look-at camera written as one matrix3d from t,
// paper panels placed as nodes (hinge tilt, height above the table), projected contact shadows,
// connectors with travelling pulses, and a JS project() that matches what Chromium draws.
// All state is recomputed from t by the scene; nothing accumulates across frames.

import { h, css } from '../base/dom.js';
import { drift } from '../base/motion.js';

const V = {
  sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
  add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
  mul: (a, s) => [a[0] * s, a[1] * s, a[2] * s],
  dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
  cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]],
  norm: (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; },
};
export { V };

const RAD = Math.PI / 180;
/** Key light direction (world): from above-back-left, so shadows fall forward and slightly right. */
export const LIGHT = V.norm([0.14, 0.34, -1]);

/** Row-major 4x4 multiply. */
function mm(a, b) {
  const o = new Array(16).fill(0);
  for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) {
    let s = 0;
    for (let k = 0; k < 4; k++) s += a[r * 4 + k] * b[k * 4 + c];
    o[r * 4 + c] = s;
  }
  return o;
}
const T = (x, y, z) => [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1];
const RZ = (a) => { const c = Math.cos(a), s = Math.sin(a); return [c, -s, 0, 0, s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]; };
const RX = (a) => { const c = Math.cos(a), s = Math.sin(a); return [1, 0, 0, 0, 0, c, -s, 0, 0, s, c, 0, 0, 0, 0, 1]; };
const RY = (a) => { const c = Math.cos(a), s = Math.sin(a); return [c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, 0, 0, 0, 1]; };
/** CSS matrix3d() string from a row-major 4x4. */
export function cssM(m) {
  const f = (v) => (Math.abs(v) < 1e-10 ? '0' : v.toFixed(6));
  return `matrix3d(${[0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15].map((i) => f(m[i])).join(',')})`;
}
function apply(m, p) {
  return [m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3], m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
    m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11]];
}

/**
 * Look-at view matrix for CSS perspective P: camera at `eye` looking at `target`, screen-up toward the far
 * side of the table, `roll` degrees. Maps world -> the perspective parent's space (eye at z = +P).
 */
export function lookAt(eye, target, roll, P) {
  const f = V.norm(V.sub(target, eye));
  const hint = V.norm([0, -1, 1]);
  let up = V.sub(hint, V.mul(f, V.dot(hint, f)));
  up = V.norm(up);
  let d = V.mul(up, -1);
  const z = V.mul(f, -1);
  let r = V.cross(d, z);
  const a = roll * RAD, c = Math.cos(a), s = Math.sin(a);
  const r2 = V.add(V.mul(r, c), V.mul(d, s));
  const d2 = V.add(V.mul(r, -s), V.mul(d, c));
  r = r2; d = d2;
  return [r[0], r[1], r[2], -V.dot(r, eye), d[0], d[1], d[2], -V.dot(d, eye), z[0], z[1], z[2], -V.dot(z, eye) + P, 0, 0, 0, 1];
}

/** Eye position from an orbit: target, distance, yaw (deg, 0 = from the front/+y), pitch (deg from straight down). */
export function orbitEye(target, dist, yaw, pitch) {
  const p = pitch * RAD, y = yaw * RAD;
  return [target[0] + dist * Math.sin(p) * Math.sin(y), target[1] + dist * Math.sin(p) * Math.cos(y), target[2] + dist * Math.cos(p)];
}

/**
 * Build the world inside the scene frame F (reference px). o: {P (focal px), table: true, lift}
 * Returns the world API.
 */
export function makeWorld(F, o = {}) {
  const P = o.P || 1700;
  const view = h('div', 'slw-view');
  view.style.cssText = `position:absolute;inset:0;perspective:${P}px;perspective-origin:50% 50%;overflow:hidden;`;
  const world = h('div', 'slw-world');
  world.style.cssText = 'position:absolute;left:50%;top:50%;width:0;height:0;transform-style:preserve-3d;transform-origin:0 0;';
  view.appendChild(world);
  const table = h('div', 'slw-table');
  world.appendChild(table);
  const shadowLayer = h('div', 'slw-shadows');
  shadowLayer.style.cssText = 'position:absolute;left:0;top:0;transform-style:preserve-3d;';
  world.appendChild(shadowLayer);
  const svgNS = 'http://www.w3.org/2000/svg';
  const doc = F.el.ownerDocument;
  const svg = doc.createElementNS(svgNS, 'svg');
  svg.setAttribute('class', 'slw-wires');
  svg.setAttribute('width', '1');
  svg.setAttribute('height', '1');
  svg.style.cssText = 'position:absolute;left:0;top:0;overflow:visible;transform:translateZ(1.5px);';
  world.appendChild(svg);
  F.cam.appendChild(view);
  const nodes = [];
  const wires = [];
  let M = null;

  const api = {
    P, view, world, table, svg, nodes, wires,
    /** Place the key-light pool and its radius on the table (world px). */
    light(x, y, rx = 1500, ry = 1100) {
      css(table, { '--lx': `${x + 4000}px`, '--ly': `${y + 4000}px`, '--lrx': `${rx}px`, '--lry': `${ry}px` });
    },
    /**
     * Add a node (a panel element) to the table. spec: {x, y, z, w, h, tilt (deg stand-up about the bottom
     * edge), rz (deg), ax, ay (anchor in element px, default bottom centre), shadow: true}
     */
    node(el, spec) {
      const n = { el, spec: { z: 30, tilt: 0, rz: 0, shadow: true, ...spec }, sh: null, contact: null };
      el.style.position = 'absolute';
      el.style.left = '0px';
      el.style.top = '0px';
      el.style.transformOrigin = '0 0';
      el.style.width = `${n.spec.w}px`;
      el.style.height = `${n.spec.h}px`;
      if (n.spec.shadow) {
        n.sh = h('div', 'slw-shadow');
        n.contact = h('div', 'slw-contact');
        shadowLayer.append(n.sh, n.contact);
      }
      world.appendChild(el);
      nodes.push(n);
      api.update(n, {});
      return n;
    },
    /** Local -> world matrix of a node for the given (possibly animated) spec. */
    nodeMatrix(s) {
      const ax = s.ax ?? s.w / 2, ay = s.ay ?? s.h;
      return mm(mm(mm(T(s.x, s.y, s.z), RZ((s.rz || 0) * RAD)), mm(RX(-(s.tilt || 0) * RAD), RY((s.ry || 0) * RAD))), T(-ax, -ay, 0));
    },
    /** Update a node's transform + its projected contact shadow. patch overrides spec fields for this frame. */
    update(n, patch) {
      const s = { ...n.spec, ...patch };
      const m = api.nodeMatrix(s);
      n.m = m;
      n.cur = s;
      css(n.el, { transform: cssM(m), opacity: s.op == null ? '1' : String(s.op) });
      if (n.sh) {
        // footprint corners -> table along the light: top-left, top-right, bottom-left
        const c = [[0, 0, 0], [s.w, 0, 0], [0, s.h, 0], [s.w, s.h, 0]].map((p) => apply(m, p));
        const proj = c.map((p) => { const k = -p[2] / LIGHT[2]; return [p[0] + LIGHT[0] * k, p[1] + LIGHT[1] * k]; });
        const hAvg = (c[0][2] + c[1][2] + c[2][2] + c[3][2]) / 4;
        const ex = [(proj[1][0] - proj[0][0]) / s.w, (proj[1][1] - proj[0][1]) / s.w];
        const ey = [(proj[2][0] - proj[0][0]) / s.h, (proj[2][1] - proj[0][1]) / s.h];
        const blur = 10 + Math.min(70, hAvg * 0.32);
        const op = Math.max(0.25, 0.86 - hAvg * 0.0012) * (s.shadowOp ?? 1) * (s.op == null ? 1 : s.op);
        css(n.sh, { width: `${s.w}px`, height: `${s.h}px`, filter: `blur(${blur.toFixed(1)}px)`, opacity: op.toFixed(3),
          transform: `matrix3d(${ex[0].toFixed(5)},${ex[1].toFixed(5)},0,0,${ey[0].toFixed(5)},${ey[1].toFixed(5)},0,0,0,0,1,0,${proj[0][0].toFixed(2)},${proj[0][1].toFixed(2)},0.5,1)` });
        // tight occlusion line where the bottom edge meets (or nears) the table
        const b0 = c[2], b1 = c[3];
        const lowZ = Math.min(b0[2], b1[2]);
        const len = Math.hypot(b1[0] - b0[0], b1[1] - b0[1]);
        const ang = Math.atan2(b1[1] - b0[1], b1[0] - b0[0]);
        css(n.contact, { width: `${len.toFixed(1)}px`, opacity: (Math.max(0, 1 - lowZ / 60) * 0.9 * (s.op == null ? 1 : s.op)).toFixed(3),
          transform: `translate3d(${b0[0].toFixed(2)}px,${(b0[1] - 7).toFixed(2)}px,0.8px) rotate(${(ang / RAD).toFixed(3)}deg)` });
      }
      return m;
    },
    /** World point of a node-local point (current transform). */
    nodePoint(n, x, y, z = 0) { return apply(n.m, [x, y, z]); },
    /**
     * A connector on the table: polyline points (world xy) with rounded corners; pulses travel along it.
     * Returns {set(t)}; o: {width, pulse:{every, speed (px/s), len}, reverse, draw: [t0, t1]}
     */
    wire(points, o = {}) {
      const d = roundedPath(points, o.radius ?? 90);
      const mk = (cls) => { const p = doc.createElementNS(svgNS, 'path'); p.setAttribute('d', d); p.setAttribute('class', cls); svg.appendChild(p); return p; };
      const glow = mk('slw-glow'), core = mk('slw-core');
      const pulses = [];
      const np = o.pulses ?? 2;
      for (let i = 0; i < np; i++) pulses.push([mk('slw-pulse-glow'), mk('slw-pulse')]);
      const ports = [];
      if (o.port !== false) {
        const c = doc.createElementNS(svgNS, 'circle');
        c.setAttribute('cx', points[0][0]); c.setAttribute('cy', points[0][1]); c.setAttribute('r', '10'); c.setAttribute('class', 'slw-port');
        svg.appendChild(c);
        ports.push(c);
      }
      const L = core.getTotalLength ? core.getTotalLength() : 1000;
      const w = { L, set(t) {
        const draw = o.draw ? Math.max(0, Math.min(1, (t - o.draw[0]) / (o.draw[1] - o.draw[0]))) : 1;
        const de = 1 - Math.pow(1 - draw, 3);
        for (const p of [glow, core]) css(p, { strokeDasharray: `${L} ${L}`, strokeDashoffset: `${(L * (1 - de)).toFixed(1)}` });
        const speed = o.speed ?? 1400, len = o.len ?? 220, every = o.every ?? 1.1;
        pulses.forEach(([pg, pc], i) => {
          const phase = (t - (o.pulseStart ?? 0.2) - i * every) / ((L + len) / speed);
          const u = phase - Math.floor(phase);
          const on = t >= (o.pulseStart ?? 0.2) + i * every && draw >= 1;
          let head = u * (L + len);
          if (o.reverse) head = L + len - head;
          const start = Math.max(0, head - len), end = Math.min(L, head);
          const seglen = Math.max(0.01, end - start);
          for (const p of [pg, pc]) css(p, { strokeDasharray: `${seglen.toFixed(1)} ${(L * 2 + len).toFixed(1)}`, strokeDashoffset: `${(-start).toFixed(1)}`, opacity: on && end > start ? '1' : '0' });
        });
        for (const c of ports) css(c, { opacity: String(de) });
      } };
      wires.push(w);
      return w;
    },
    /**
     * Set the camera for this frame: {target:[x,y,z], dist, yaw, pitch, roll, lift}. Adds hand-held drift
     * (amp px, never parked). Returns the view matrix.
     */
    camera(t, cam, o = {}) {
      const [dx, dy, dr] = drift(t, o.seed ?? 11, o.amp ?? 5, o.rollAmp ?? 0.18);
      const tg = [cam.target[0] + dx, cam.target[1] + dy, cam.target[2] || 0];
      const eye = orbitEye(tg, cam.dist, cam.yaw || 0, cam.pitch || 0);
      M = lookAt(eye, tg, (cam.roll || 0) + dr, P);
      css(world, { transform: cssM(M) });
      const sh = cam.shift || api.shift || [0, 0];
      api.curShift = [sh[0], sh[1] - (cam.lift || 0)];
      api.applyShift(api.curShift);
      return M;
    },
    /**
     * Lens shift [dx, dy] (frame px): the image centre moves without re-aiming the camera. Done by moving the
     * world origin AND the perspective origin together (an exact 2D shift of the projected image) rather than
     * translating the view, so the frame edge never uncovers the stage behind the table.
     */
    applyShift([dx, dy]) {
      const x = (F.W / 2 + dx).toFixed(2), y = (F.H / 2 + dy).toFixed(2);
      css(view, { perspectiveOrigin: `${x}px ${y}px`, transform: 'none' });
      css(world, { left: `${x}px`, top: `${y}px` });
    },
    shift: null,
    curShift: [0, 0],
    /** World point -> frame px [x, y, scale] (matches Chromium's projection of the CSS world). */
    project(p) {
      const q = apply(M, p);
      const s = P / (P - q[2]);
      return [F.W / 2 + q[0] * s + api.curShift[0], F.H / 2 + q[1] * s + api.curShift[1], s];
    },
    /** Camera distance so a w x h rect facing the camera fills `fill` of the frame (with margins). */
    fitDist(w, hh, fill = 0.82, fillH = 0.78) {
      return Math.max((w * P) / (F.W * fill), (hh * P) / (F.H * fillH));
    },
  };
  return api;
}

/** SVG path through points with rounded corners (radius r). */
export function roundedPath(pts, r) {
  if (pts.length < 3) return `M ${pts[0][0]} ${pts[0][1]} L ${pts[pts.length - 1][0]} ${pts[pts.length - 1][1]}`;
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [a, b, c] = [pts[i - 1], pts[i], pts[i + 1]];
    const l1 = Math.hypot(b[0] - a[0], b[1] - a[1]), l2 = Math.hypot(c[0] - b[0], c[1] - b[1]);
    const rr = Math.min(r, l1 / 2, l2 / 2);
    const p1 = [b[0] - ((b[0] - a[0]) / l1) * rr, b[1] - ((b[1] - a[1]) / l1) * rr];
    const p2 = [b[0] + ((c[0] - b[0]) / l2) * rr, b[1] + ((c[1] - b[1]) / l2) * rr];
    d += ` L ${p1[0].toFixed(1)} ${p1[1].toFixed(1)} Q ${b[0].toFixed(1)} ${b[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  const z = pts[pts.length - 1];
  return d + ` L ${z[0].toFixed(1)} ${z[1].toFixed(1)}`;
}
