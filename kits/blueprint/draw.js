// Hype kit "blueprint" — SVG drafting primitives. Every stroke is a <path pathLength="1"> so the plotter can
// draw it on with stroke-dashoffset 1 -> 0; fills (arrowheads, balloon discs) "pop" when their stroke lands.
// Drafting grammar: object lines (obj, 2.4 px), thin (1.4), hidden (dashed 9 6), centre (chain 26 7 4 7),
// construction (dotted 4 5), dimensions with 16 px filled arrowheads and unidirectional (horizontal) lettering.

const NS = 'http://www.w3.org/2000/svg';
const f1 = (n) => (Math.round(n * 10) / 10).toString();

/** Create an SVG element under `parent` with attributes. */
export function el(parent, tag, attrs = {}) {
  const e = parent.ownerDocument.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, String(v));
  parent.appendChild(e);
  return e;
}

/** Polyline points -> path data. */
export const d = (pts, close = false) => 'M' + pts.map((p) => f1(p[0]) + ' ' + f1(p[1])).join(' L') + (close ? 'Z' : '');

const DASH = { hid: '9 6', ctr: '26 7 4 7', cons: '4 5' };

/**
 * A plottable stroke. cls: obj | thin | hid | ctr | cons | dim | lead | cloud | red | pen. Dashed classes keep their
 * dash pattern by drawing through a mask-free trick: the dash pattern is applied to a twin path revealed by the plot
 * path (pathLength=1 dash 1 1) used as a clip; to stay cheap we plot dashed lines as solid during the draw and
 * switch to the dash pattern when complete (`dashed` attribute).
 */
export function stroke(parent, dd, cls = 'obj', extra = {}) {
  const e = el(parent, 'path', { d: dd, class: cls, pathLength: 1, ...extra });
  if (DASH[cls]) e.dataset.dash = DASH[cls];
  return e;
}
export const line = (parent, pts, cls = 'obj', extra) => stroke(parent, d(pts), cls, extra);

/** Rectangle path (clockwise from top-left). */
export const rectD = (x, y, w, h) => d([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], true);

/** Circle as a path starting at angle a0 (radians, 0 = +x, clockwise on screen). */
export function circleD(cx, cy, r, a0 = -Math.PI / 2, a1 = a0 + Math.PI * 2, n = 72) {
  const pts = [];
  for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); }
  return d(pts);
}

/** Filled arrowhead with its tip at p pointing along unit vector (ux, uy). */
export function arrow(parent, p, ux, uy, size = 16) {
  const nx = -uy, ny = ux, w = size * 0.28;
  return el(parent, 'path', { class: 'arrow', d: `M${f1(p[0])} ${f1(p[1])} L${f1(p[0] - ux * size + nx * w)} ${f1(p[1] - uy * size + ny * w)} L${f1(p[0] - ux * size - nx * w)} ${f1(p[1] - uy * size - ny * w)}Z` });
}

/**
 * Dimension between points a and b, offset `off` px along the normal: extension lines, the dimension line and two
 * arrowheads (pointing outwards to the extension lines). Returns {parts: [strokes], heads: [fills], mid: [x, y], u: [ux, uy]}.
 */
export function dimension(parent, a, b, off) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, nx = -uy, ny = ux;
  const s = Math.sign(off) || 1;
  const A = [a[0] + nx * off, a[1] + ny * off], B = [b[0] + nx * off, b[1] + ny * off];
  const ext = 12 * s;
  const parts = [
    line(parent, [[a[0] + nx * 6 * s, a[1] + ny * 6 * s], [A[0] + nx * ext, A[1] + ny * ext]], 'dim'),
    line(parent, [[b[0] + nx * 6 * s, b[1] + ny * 6 * s], [B[0] + nx * ext, B[1] + ny * ext]], 'dim'),
    line(parent, [A, B], 'dim'),
  ];
  const heads = [arrow(parent, A, -ux, -uy), arrow(parent, B, ux, uy)];
  return { parts, heads, mid: [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2], u: [ux, uy], n: [nx * s, ny * s] };
}

/** Dog-leg leader from p (with a dot) through `via` points; returns {stroke, dot}. */
export function leader(parent, pts) {
  const s = line(parent, pts, 'lead');
  const dot = el(parent, 'circle', { cx: f1(pts[0][0]), cy: f1(pts[0][1]), r: 4.5, class: 'arrow' });
  return { stroke: s, dot };
}

/** Item balloon (circle + number). Returns {ring, disc, num}. */
export function balloon(parent, cx, cy, n, r = 21) {
  const disc = el(parent, 'circle', { cx: f1(cx), cy: f1(cy), r, class: 'fillsheet' });
  const ring = stroke(parent, circleD(cx, cy, r), 'thin');
  const num = el(parent, 'text', { x: f1(cx), y: f1(cy + 1), class: 'bnum' });
  num.textContent = String(n);
  return { ring, disc, num };
}

/** Revision cloud around a rectangle (scallops of ~`step` px bulging outwards). */
export function cloudD(x0, y0, x1, y1, step = 26) {
  const pts = [];
  const edge = (ax, ay, bx, by) => {
    const L = Math.hypot(bx - ax, by - ay), n = Math.max(2, Math.round(L / step));
    for (let i = 0; i < n; i++) pts.push([ax + (bx - ax) * i / n, ay + (by - ay) * i / n]);
  };
  edge(x0, y0, x1, y0); edge(x1, y0, x1, y1); edge(x1, y1, x0, y1); edge(x0, y1, x0, y0);
  pts.push(pts[0]);
  let s = `M${f1(pts[0][0])} ${f1(pts[0][1])}`;
  for (let i = 1; i < pts.length; i++) {
    const [px, py] = pts[i - 1], [x, y] = pts[i];
    const r = Math.hypot(x - px, y - py) * 0.6;
    s += ` A${f1(r)} ${f1(r)} 0 0 1 ${f1(x)} ${f1(y)}`;
  }
  return s;
}

/** Revision delta: triangle with the REV letter. Returns {tri, text}. */
export function delta(parent, x, y, s, label) {
  const tri = el(parent, 'path', { d: `M${f1(x)} ${f1(y - s)} L${f1(x + s * 0.9)} ${f1(y + s * 0.6)} L${f1(x - s * 0.9)} ${f1(y + s * 0.6)}Z`, class: 'rev' });
  const text = el(parent, 'text', { x: f1(x), y: f1(y + s * 0.12), class: 'revt' });
  text.textContent = label;
  return { tri, text };
}

/** A lettered check mark (stroke) of size s with its corner at (x, y). */
export const checkD = (x, y, s) => d([[x - s * 0.45, y - s * 0.05], [x - s * 0.1, y + s * 0.3], [x + s * 0.5, y - s * 0.4]]);

// ------------------------------------------------------------------------------------- oblique part kit
// Parts sit on an axis; local x runs along the axis, faces are circles sheared into ellipses (style-frame kit).
export const K = 0.36, S = 0.24;
export const T1 = Math.atan2(1, S);
/** Face point (u, v) at axial x -> local. */
export const P = (x, u, v) => [x + K * u, S * u + v];
export function circlePts(x, R, a0 = 0, a1 = 2 * Math.PI, n = 96, cu = 0, cv = 0) {
  const pts = [];
  for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; pts.push(P(x, cu + R * Math.cos(a), cv + R * Math.sin(a))); }
  return pts;
}
export const visArc = (x, R) => circlePts(x, R, T1 - Math.PI, T1, 64);
export const hidArc = (x, R) => circlePts(x, R, T1, T1 + Math.PI, 64);
export const sil = (x0, x1, R) => [[P(x0, R * Math.cos(T1), R * Math.sin(T1)), P(x1, R * Math.cos(T1), R * Math.sin(T1))],
  [P(x0, -R * Math.cos(T1), -R * Math.sin(T1)), P(x1, -R * Math.cos(T1), -R * Math.sin(T1))]];

/** Oblique plate (a sheet seen at an angle) of half-size a x b at axial x; returns its outline points. */
export const platePts = (x, a, b) => [[-a, -b], [a, -b], [a, b], [-a, b], [-a, -b]].map(([u, v]) => P(x, u, v));

export { NS, f1 };
