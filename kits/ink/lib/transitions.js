// Hype kit "ink" — transitions (css kind: they work on DOM shots; tx.g is an overlay canvas above both).
//  kit:ink/ink-bleed    the next scene bleeds in through an organic ink blot that spreads from a point, with a
//                       wet ink rim and a few seeded droplets running ahead of the edge.
//  kit:ink/paper-slide  the next paper sheet is slid in over the current one by hand (a slight turn that settles,
//                       a flat edge shadow on the sheet below).

const INK = '43,38,34';

function rnd(seed) {
  let a = seed >>> 0 || 1;
  return () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** Blot outline: N points around (cx, cy) at base radius R with seeded lobes that bleed unevenly with u. */
function blot(cx, cy, R, u, seed, n = 96) {
  const r = rnd(seed);
  const ph = [r(), r(), r(), r(), r()].map((x) => x * Math.PI * 2);
  const lobes = Array.from({ length: 9 }, () => [r() * Math.PI * 2, 0.08 + r() * 0.16, 0.25 + r() * 0.35]);
  const pts = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    let k = 1 + 0.10 * Math.sin(3 * a + ph[0]) + 0.06 * Math.sin(5 * a + ph[1]) + 0.035 * Math.sin(11 * a + ph[2]) + 0.02 * Math.sin(23 * a + ph[3]);
    for (const [la, amp, w] of lobes) {
      const d = Math.atan2(Math.sin(a - la), Math.cos(a - la));
      k += amp * Math.exp(-(d * d) / (2 * (w * 0.35) ** 2)) * Math.min(1, u * 1.6);
    }
    pts.push([cx + Math.cos(a) * R * k, cy + Math.sin(a) * R * k]);
  }
  return pts;
}

function inkBleed(tx, u, p) {
  const { g, w, h } = tx;
  const e = tx.ease.inOutCubic(Math.max(0, Math.min(1, u)));
  const cx = (p.x ?? 0.42) * w, cy = (p.y ?? 0.52) * h;
  const R = Math.hypot(Math.max(cx, w - cx), Math.max(cy, h - cy)) * 1.08 * e;
  const seed = p.seed || 17;
  const pts = blot(cx, cy, R, u, seed);
  tx.toEl.style.clipPath = e >= 1 ? 'none' : `polygon(${pts.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(',')})`;
  tx.toEl.style.zIndex = String(Number(tx.fromEl.style.zIndex || 0) + 1);
  if (e <= 0 || e >= 1) return;
  const fade = Math.min(1, (1 - e) * 4);
  // wet rim: a soft dark band just outside the blot edge (the ink front), then a crisp inner line
  const rim = blot(cx, cy, R * 1.035 + w * 0.006, u, seed);
  g.save();
  g.beginPath();
  rim.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
  g.closePath();
  pts.slice().reverse().forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
  g.closePath();
  g.fillStyle = `rgba(${INK},${(0.82 * fade).toFixed(3)})`;
  g.fill('evenodd');
  g.lineJoin = 'round';
  g.lineWidth = Math.max(2, w / 640);
  g.strokeStyle = `rgba(${INK},${(0.55 * fade).toFixed(3)})`;
  g.beginPath();
  pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
  g.closePath();
  g.stroke();
  // droplets ahead of the edge (seeded positions, they appear as the front reaches them)
  const r = rnd(seed * 7 + 3);
  for (let i = 0; i < 26; i++) {
    const a = r() * Math.PI * 2, dist = 1.05 + r() * 0.22, rad = (0.002 + r() * 0.006) * w, born = 0.1 + r() * 0.6;
    if (u < born) continue;
    const k = Math.min(1, (u - born) * 5);
    g.fillStyle = `rgba(${INK},${(0.85 * fade).toFixed(3)})`;
    g.beginPath();
    g.ellipse(cx + Math.cos(a) * R * dist, cy + Math.sin(a) * R * dist, rad * k, rad * k * (0.7 + r() * 0.3), a, 0, Math.PI * 2);
    g.fill();
  }
  g.restore();
}

function paperSlide(tx, u, p) {
  const { g, w, h } = tx;
  const e = tx.ease.inOutCubic(Math.max(0, Math.min(1, u)));
  const dir = p.dir === 'up' ? 'up' : 'left';
  const x = dir === 'left' ? (1 - e) * (w + 40) : 0, y = dir === 'up' ? (1 - e) * (h + 40) : 0;
  const rot = (1 - e) * (p.turn ?? 2.2) * (dir === 'left' ? 1 : -1);
  tx.toEl.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) rotate(${rot.toFixed(3)}deg)`;
  tx.toEl.style.transformOrigin = dir === 'left' ? '0% 100%' : '0% 0%';
  tx.toEl.style.zIndex = String(Number(tx.fromEl.style.zIndex || 0) + 1);
  tx.fromEl.style.transform = `translate(${(dir === 'left' ? -e * w * 0.06 : 0).toFixed(1)}px,${(dir === 'up' ? -e * h * 0.05 : 0).toFixed(1)}px)`;
  if (e <= 0 || e >= 1) return;
  // flat edge shadow of the incoming sheet on the sheet below (offset copy, no blur)
  g.save();
  g.fillStyle = 'rgba(92,62,38,0.16)';
  if (dir === 'left') {
    g.translate(x - 14, 0);
    g.rotate((rot * Math.PI) / 180);
    g.fillRect(0, 10, 14, h * 1.2);
  } else {
    g.translate(0, y - 14);
    g.fillRect(-10, 0, w * 1.2, 14);
  }
  g.restore();
}

export const TRANSITIONS = {
  'kit:ink/ink-bleed': { kind: 'css', render: inkBleed },
  'kit:ink/paper-slide': { kind: 'css', render: paperSlide },
};
