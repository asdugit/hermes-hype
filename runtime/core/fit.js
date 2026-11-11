// Runtime fit pass for DOM shots: no text may be cut by the frame edge while it is held on screen.
//
// Kits move cameras (push-ins onto code, pans, zooms on cards); with long real-world text a push can park lines
// past the frame edge for seconds. Before a DOM shot is first shown, the runtime samples its own render at fixed
// times, finds text that stays cut by the frame edge for a while (a pan or an entrance that only crosses the edge
// is motion, not a defect), and solves a correction on the outermost moving element that holds that text (the
// kit's camera / world / card): first shrink it towards the centre (down to a floor), then nudge it inside the
// safe area. The correction is a pure function of the shot time (computed from fixed samples, eased between them),
// applied through the independent CSS `scale` / `translate` properties so the kit's own `transform` is untouched.
// When nothing is cut the pass does nothing.
import { domTextBoxes } from './qa.js';

const STEP = 0.2;            // s between samples
const PERSIST = 0.6;         // a text box cut for at least this long (s) is a defect, shorter is motion
const SMIN = 0.55;           // never shrink a camera/card below this
const SAMPLES_MAX = 80;

const isCut = (r, W, H) => {
  const [x, y, w, h] = r;
  const vis = x < W && y < H && x + w > 0 && y + h > 0;
  return vis && (x < -2 || y < -2 || x + w > W + 2 || y + h > H + 2);
};
const visible = (r, W, H) => r[0] < W - 1 && r[1] < H - 1 && r[0] + r[2] > 1 && r[1] + r[3] > 1;

/** The element to correct for a cut text element: the outermost transformed element inside the innermost
 * full-frame clipper (the kit's camera/world), else the outermost element below that clipper. */
export function fitTarget(el, root, W, H, stage) {
  const chain = [];
  for (let a = el; a && a !== root; a = a.parentElement) chain.push(a);
  if (!chain.length) return null;
  const sr = stage.el.getBoundingClientRect();
  const sc = stage.scale || 1;
  let clipIdx = chain.length;            // index in chain of the innermost full-frame clipper (root if none)
  for (let i = 0; i < chain.length; i++) {
    const a = chain[i];
    const cs = getComputedStyle(a);
    if (cs.overflow === 'visible' && cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
    // a frame clipper is an untransformed box the size of the frame (a pushed-in card that clips its own rows
    // also covers the frame, but it is transformed and much bigger than the frame)
    if (cs.transform && cs.transform !== 'none') continue;
    const r = a.getBoundingClientRect();
    const w = r.width / sc, h = r.height / sc, x = (r.left - sr.left) / sc, y = (r.top - sr.top) / sc;
    if (w >= 0.85 * W && h >= 0.85 * H && w <= 1.15 * W && h <= 1.15 * H && Math.abs(x) <= W * 0.08 && Math.abs(y) <= H * 0.08) { clipIdx = i; break; }
  }
  const below = chain.slice(0, clipIdx).filter((a) => !a.classList.contains('srb') && a.dataset.srFit !== 'off');
  if (!below.length) return null;
  for (let i = below.length - 1; i >= 0; i--) {
    const tf = getComputedStyle(below[i]).transform;
    if (tf && tf !== 'none') return below[i];
  }
  return below[below.length - 1];
}

function apply(el, c) {
  if (!c || (Math.abs(c.s - 1) < 1e-4 && Math.abs(c.tx) < 0.05 && Math.abs(c.ty) < 0.05)) {
    el.style.scale = '';
    el.style.translate = '';
    return;
  }
  el.style.scale = `${c.s.toFixed(5)} ${c.s.toFixed(5)}`;
  el.style.translate = `${c.tx.toFixed(2)}px ${c.ty.toFixed(2)}px`;
}

function union(boxes) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const b of boxes) {
    x0 = Math.min(x0, b.rect[0]); y0 = Math.min(y0, b.rect[1]);
    x1 = Math.max(x1, b.rect[0] + b.rect[2]); y1 = Math.max(y1, b.rect[1] + b.rect[3]);
  }
  return { x0, y0, x1, y1, w: x1 - x0, h: y1 - y0, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
}

/** Shift (film px) that brings span [a0, a1] inside [lo, hi] (centres it when it is too big). */
function shiftInto(a0, a1, lo, hi) {
  if (a1 - a0 > hi - lo) return (lo + hi) / 2 - (a0 + a1) / 2;
  if (a0 < lo) return lo - a0;
  if (a1 > hi) return hi - a1;
  return 0;
}

/**
 * Solve one correction for `target` with the DOM at the current (uncorrected) state.
 * measure() -> text boxes [{rect, el}] under the shot root (film px). Returns {s, tx, ty} or null.
 */
export function solveAt(target, measure, o) {
  const { W, H, safe } = o;
  const lo = [safe.l, safe.t], hi = [W - safe.r, H - safe.b];
  const under = () => measure().filter((b) => target.contains(b.el));
  apply(target, null);
  const keep = new Set();
  const grow = (bs) => { for (const b of bs) if (visible(b.rect, W, H)) keep.add(b.el); };
  let bs = under();
  grow(bs);
  if (!bs.some((b) => isCut(b.rect, W, H))) return null;
  let c = { s: 1, tx: 0, ty: 0 };
  for (let iter = 0; iter < 4; iter++) {
    let U = union(bs.filter((b) => keep.has(b.el)));
    if (!Number.isFinite(U.w)) break;
    const need = Math.min(1, (hi[0] - lo[0]) / Math.max(1, U.w), (hi[1] - lo[1]) / Math.max(1, U.h));
    const s = Math.max(o.smin ?? SMIN, Math.min(1, c.s * need));
    if (Math.abs(s - c.s) > 1e-4) {
      c = { ...c, s };
      apply(target, c);
      bs = under();
      U = union(bs.filter((b) => keep.has(b.el)));
    }
    const dx = shiftInto(U.x0, U.x1, lo[0], hi[0]);
    const dy = shiftInto(U.y0, U.y1, lo[1], hi[1]);
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
      // probe the translate gain (perspective / scaled parents): move by a guess, measure, rescale
      const g = { ...c, tx: c.tx + dx, ty: c.ty + dy };
      apply(target, g);
      const B = union(under().filter((b) => keep.has(b.el)));
      const gx = Math.abs(dx) > 0.5 ? (B.cx - U.cx) / dx : 1;
      const gy = Math.abs(dy) > 0.5 ? (B.cy - U.cy) / dy : 1;
      c = { ...c,
        tx: c.tx + (Math.abs(gx) > 0.05 ? dx / gx : dx),
        ty: c.ty + (Math.abs(gy) > 0.05 ? dy / gy : dy) };
      apply(target, c);
    }
    bs = under();
    const before = keep.size;
    grow(bs);
    const stillCut = bs.some((b) => keep.has(b.el) && isCut(b.rect, W, H));
    if (!stillCut && keep.size === before) break;
  }
  apply(target, null);
  return (Math.abs(c.s - 1) < 1e-4 && Math.abs(c.tx) < 0.05 && Math.abs(c.ty) < 0.05) ? null : c;
}

/**
 * Pre-pass for one DOM shot instance. renderAt(t) renders the shot at local time t (uncorrected).
 * Returns a plan {targets: [{el, cs: [{s,tx,ty}|null per sample]}], step, n} or null when nothing is cut.
 */
export function planFit({ root, stage, W, H, safe, dur, renderAt, smin }) {
  const n = Math.max(2, Math.min(SAMPLES_MAX, Math.ceil(dur / STEP) + 1));
  const step = dur / (n - 1);
  const owner = { id: 'fit', kind: 'shot' };
  const measure = () => domTextBoxes(root, stage, owner);
  // 1) where is text cut, uncorrected
  const cutAt = new Map();           // el -> [sample idx]
  for (let i = 0; i < n; i++) {
    renderAt(i * step);
    for (const b of measure()) {
      if (!isCut(b.rect, W, H)) continue;
      if (!cutAt.has(b.el)) cutAt.set(b.el, []);
      const a = cutAt.get(b.el);
      if (a[a.length - 1] !== i) a.push(i);
    }
  }
  if (!cutAt.size) return null;
  const runLen = Math.max(2, Math.ceil(PERSIST / step) + 1);
  const persistentAt = new Map();    // sample idx -> Set(el)
  for (const [el, idx] of cutAt) {
    let s0 = 0;
    for (let k = 1; k <= idx.length; k++) {
      if (k === idx.length || idx[k] !== idx[k - 1] + 1) {
        if (k - s0 >= runLen) {
          for (let j = s0; j < k; j++) {
            if (!persistentAt.has(idx[j])) persistentAt.set(idx[j], new Set());
            persistentAt.get(idx[j]).add(el);
          }
        }
        s0 = k;
      }
    }
  }
  if (!persistentAt.size) return null;
  // 2) one correction per sample on each target holding persistently cut text
  const targets = new Map();         // el -> array per sample
  for (const [i, els] of [...persistentAt.entries()].sort((a, b) => a[0] - b[0])) {
    const ts = new Set();
    for (const el of els) { const tg = fitTarget(el, root, W, H, stage); if (tg) ts.add(tg); }
    if (!ts.size) continue;
    renderAt(i * step);
    for (const tg of ts) {
      if (!targets.has(tg)) targets.set(tg, new Array(n).fill(null));
      targets.get(tg)[i] = solveAt(tg, measure, { W, H, safe, smin });
    }
  }
  const out = [];
  for (const [el, cs] of targets) {
    // envelope: the strongest correction within +-2 samples, then a 3-tap average -> no pops at the edges
    const sv = cs.map((c) => (c ? c.s : 1));
    const env = cs.map((_, i) => {
      let best = null;
      for (let j = Math.max(0, i - 2); j <= Math.min(n - 1, i + 2); j++) if (cs[j] && (!best || cs[j].s < best.s || (cs[j].s === best.s && Math.hypot(cs[j].tx, cs[j].ty) > Math.hypot(best.tx, best.ty)))) best = cs[j];
      return best || { s: 1, tx: 0, ty: 0 };
    });
    const sm = env.map((_, i) => {
      const a = env[Math.max(0, i - 1)], b = env[i], c = env[Math.min(n - 1, i + 1)];
      return { s: (a.s + b.s + c.s) / 3, tx: (a.tx + b.tx + c.tx) / 3, ty: (a.ty + b.ty + c.ty) / 3 };
    });
    if (sv.every((v) => v === 1) && sm.every((c) => Math.abs(c.tx) < 0.05 && Math.abs(c.ty) < 0.05)) continue;
    out.push({ el, cs: sm });
  }
  return out.length ? { targets: out, step, n } : null;
}

/** Apply a plan at local time t (linear between samples). Safe to call with plan = null. */
export function applyFit(plan, t) {
  if (!plan) return;
  const u = Math.max(0, Math.min(plan.n - 1, t / plan.step));
  const i = Math.floor(u), f = u - i;
  for (const { el, cs } of plan.targets) {
    const a = cs[i], b = cs[Math.min(plan.n - 1, i + 1)];
    apply(el, { s: a.s + (b.s - a.s) * f, tx: a.tx + (b.tx - a.tx) * f, ty: a.ty + (b.ty - a.ty) * f });
  }
}

/** Remove every correction of a plan (before a fresh uncorrected render). */
export function clearFit(plan) {
  if (!plan) return;
  for (const { el } of plan.targets) apply(el, null);
}
