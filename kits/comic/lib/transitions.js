// Auteur kit "comic" — transitions (css kind: they work on DOM shots; tx.g is an overlay canvas above both).
//  kit:comic/page-turn   the page lifts at the bottom-right corner and turns over to the left; the back of the
//                        page (newsprint) and the curl shadow are painted on the overlay.
//  kit:comic/splat-iris  the next page bursts open through a jagged explosion balloon with a heavy ink rim.
//  kit:comic/panel-glide the camera glides across the gutter to the next page (both pages slide, ink borders).

import { burstClip } from './art.js';

const INK = '#14110F', PAPER = '#F4EAD2', PAPER_D = '#E2D3AE';

function reflect(p, a, d) {
  const vx = p[0] - a[0], vy = p[1] - a[1];
  const k = vx * d[0] + vy * d[1];
  return [a[0] + 2 * k * d[0] - vx, a[1] + 2 * k * d[1] - vy];
}

/** Sutherland-Hodgman: the part of polygon `poly` where side(q) > 0. */
function clipHalf(poly, side) {
  const out = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    const sa = side(a), sb = side(b);
    if (sa > 0) out.push(a);
    if ((sa > 0) !== (sb > 0)) {
      const k = sa / (sa - sb);
      out.push([a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]);
    }
  }
  return out;
}

function pageTurn(tx, u, p) {
  const { g, w, h } = tx;
  const e = tx.ease.inOutCubic(u);
  const slant = (p.slant ?? 0.32) * w;
  const xb = w + 4 - e * (w + slant + 0.08 * w + 8);
  const xt = xb + slant;
  // the part of the page still lying flat
  tx.fromEl.style.clipPath = `polygon(0px 0px, ${Math.max(0, xt).toFixed(1)}px 0px, ${Math.max(0, xb).toFixed(1)}px ${h}px, 0px ${h}px)`;
  tx.fromEl.style.zIndex = String(Number(tx.toEl.style.zIndex || 0) + 1);
  if (e <= 0 || e >= 1) return;
  const A = [xb, h], B = [xt, 0];
  const L = Math.hypot(B[0] - A[0], B[1] - A[1]);
  const d = [(B[0] - A[0]) / L, (B[1] - A[1]) / L];
  const n = [-d[1], d[0]];   // points to the lifted side (right)
  // shadow cast on the next page, along the fold
  const sw = 40 + 120 * Math.sin(Math.PI * e);
  const gr = g.createLinearGradient(A[0], A[1], A[0] + n[0] * sw, A[1] + n[1] * sw);
  gr.addColorStop(0, 'rgba(20,17,15,0.42)');
  gr.addColorStop(1, 'rgba(20,17,15,0)');
  g.save();
  g.beginPath();
  g.moveTo(B[0], B[1]); g.lineTo(w + 2000, -2000); g.lineTo(w + 2000, h + 2000); g.lineTo(A[0], A[1]); g.closePath();
  g.clip();
  g.fillStyle = gr;
  g.fillRect(0, 0, w, h);
  g.restore();
  // the flap: the lifted region reflected over the fold line (back of the page)
  const side = (q) => (q[0] - A[0]) * n[0] + (q[1] - A[1]) * n[1];
  const flap = clipHalf([[0, 0], [w, 0], [w, h], [0, h]], side).map((q) => reflect(q, A, d));
  if (flap.length < 3) return;
  g.save();
  g.beginPath();
  flap.forEach((q, i) => (i ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1])));
  g.closePath();
  g.shadowColor = 'rgba(20,17,15,0.35)'; g.shadowBlur = 0; g.shadowOffsetX = -10; g.shadowOffsetY = 8;
  const fg = g.createLinearGradient(A[0], A[1], A[0] - n[0] * w * 0.5, A[1] - n[1] * w * 0.5);
  fg.addColorStop(0, PAPER_D); fg.addColorStop(0.18, PAPER); fg.addColorStop(1, '#FBF4E2');
  g.fillStyle = fg;
  g.fill();
  g.shadowColor = 'transparent';
  g.lineWidth = Math.max(3, w / 320);
  g.strokeStyle = INK;
  g.stroke();
  // newsprint dots on the back of the page
  g.clip();
  g.fillStyle = 'rgba(120,90,40,.13)';
  const step = Math.max(6, Math.round(w / 240));
  for (let y = 0; y < h; y += step) for (let x = (y / step) % 2 ? step / 2 : 0; x < w; x += step) g.fillRect(x, y, 1.6, 1.6);
  g.restore();
}

function splatIris(tx, u, p) {
  const { g, w, h } = tx;
  const e = tx.ease.inOutCubic(u);
  const cx = (p.x ?? 0.5) * w, cy = (p.y ?? 0.5) * h;
  const R = Math.hypot(Math.max(cx, w - cx), Math.max(cy, h - cy)) * 1.55 * e;
  const pts = burstClip(p.spikes || 14, p.depth ?? 0.3, p.seed || 7).split(',').map((s) => s.trim().split(/\s+/).map((v) => parseFloat(v) / 100 - 0.5));
  const poly = pts.map(([x, y]) => [cx + x * 2 * R, cy + y * 2 * R]);
  tx.toEl.style.clipPath = `polygon(${poly.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(',')})`;
  tx.toEl.style.zIndex = String(Number(tx.fromEl.style.zIndex || 0) + 1);
  if (e <= 0 || e >= 1) return;
  g.save();
  g.beginPath();
  poly.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
  g.closePath();
  g.lineJoin = 'miter';
  g.lineWidth = Math.max(8, w / 110);
  g.strokeStyle = INK;
  g.stroke();
  g.lineWidth = Math.max(3, w / 300);
  g.strokeStyle = '#FFD23A';
  g.translate(-w / 240, -w / 240);
  g.stroke();
  g.restore();
}

function panelGlide(tx, u, p) {
  const { g, w, h } = tx;
  const e = tx.ease.inOutCubic(u);
  const gap = (p.gap ?? 0.035) * w;
  const span = w + gap;
  tx.fromEl.style.transform = `translate3d(${(-e * span).toFixed(1)}px,0,0)`;
  tx.toEl.style.transform = `translate3d(${((1 - e) * span).toFixed(1)}px,0,0)`;
  const blur = Math.sin(Math.PI * u) ** 2 * (p.blur ?? 6);
  if (blur > 0.3) { tx.fromEl.style.filter = `blur(${blur.toFixed(2)}px)`; tx.toEl.style.filter = `blur(${blur.toFixed(2)}px)`; }
  const x0 = w - e * span;   // gutter left edge
  g.fillStyle = PAPER;
  g.fillRect(x0, 0, gap, h);
  g.fillStyle = INK;
  const bw = Math.max(4, w / 240);
  g.fillRect(x0 - bw, 0, bw, h);
  g.fillRect(x0 + gap, 0, bw, h);
}

export const TRANSITIONS = {
  'kit:comic/page-turn': { kind: 'css', render: pageTurn },
  'kit:comic/splat-iris': { kind: 'css', render: splatIris },
  'kit:comic/panel-glide': { kind: 'css', render: panelGlide },
};
