// Built-in transitions (SDK §5). Each is {kind, render(tx, u, p), fallback?}.
//  - kind 'css': tx.fromEl / tx.toEl are the two shot wrappers (styles are reset by the runtime every frame);
//    tx.g draws on a transparent overlay canvas above both shots (flashes, burns, ink fronts).
//  - kind 'canvas': tx.from / tx.to are the shots' rendered surfaces (null for DOM shots); tx.g is a film-size
//    canvas that replaces both shots for the window. `fallback` (css) is used when a side is a DOM shot.
// tx = {g, w, h, from, to, fromEl, toEl, rng, ease, noise2, fbm2, draw(src, opts), frame, t, seed}

const io = (tx, u) => tx.ease.inOutCubic(u);

function crossfadeCss(tx, u) {
  tx.toEl.style.opacity = String(tx.ease.inOutSine(u));
}

function dip(color) {
  return {
    kind: 'css',
    render(tx, u, p) {
      const c = p.color || color;
      const hold = Math.max(0, Math.min(0.5, p.hold ?? 0.12));
      const a = u < 0.5 - hold / 2 ? u / (0.5 - hold / 2) : u > 0.5 + hold / 2 ? (1 - u) / (0.5 - hold / 2) : 1;
      if (u < 0.5) tx.toEl.style.visibility = 'hidden';
      else tx.fromEl.style.visibility = 'hidden';
      tx.g.globalAlpha = tx.ease.inOutSine(Math.max(0, Math.min(1, a)));
      tx.g.fillStyle = c;
      tx.g.fillRect(0, 0, tx.w, tx.h);
    },
  };
}

const DIRS = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] };

function push(dir) {
  return {
    kind: 'css',
    render(tx, u, p) {
      const [dx, dy] = DIRS[p.dir || dir] || DIRS.left;
      const e = (p.ease ? tx.ease.get(p.ease) : tx.ease.inOutQuart)(u);
      tx.fromEl.style.transform = `translate(${dx * e * 100}%, ${dy * e * 100}%)`;
      tx.toEl.style.transform = `translate(${dx * (e - 1) * 100}%, ${dy * (e - 1) * 100}%)`;
    },
  };
}

function whipCss(tx, u, p) {
  const [dx, dy] = DIRS[p.dir || 'left'] || DIRS.left;
  const e = tx.ease.inOutExpo(u);
  const blur = Math.sin(Math.PI * u) ** 2 * (p.blur ?? 28);
  const travel = p.travel ?? 100;
  tx.fromEl.style.transform = `translate(${dx * e * travel}%, ${dy * e * travel}%)`;
  tx.toEl.style.transform = `translate(${dx * (e - 1) * travel}%, ${dy * (e - 1) * travel}%)`;
  const f = blur > 0.3 ? `blur(${blur.toFixed(2)}px)` : '';
  tx.fromEl.style.filter = f; tx.toEl.style.filter = f;
  // streak flash at the crossing
  const k = Math.sin(Math.PI * u) ** 6 * (p.flash ?? 0.18);
  if (k > 0.002) { tx.g.globalAlpha = k; tx.g.fillStyle = p.color || '#fff'; tx.g.fillRect(0, 0, tx.w, tx.h); }
}

function zoomThroughCss(tx, u, p) {
  const s = p.scale ?? 2.4;
  const a = tx.ease.inCubic(Math.min(1, u * 1.25));
  const b = tx.ease.outCubic(Math.max(0, (u - 0.3) / 0.7));
  tx.fromEl.style.transform = `scale(${1 + (s - 1) * a})`;
  tx.fromEl.style.opacity = String(1 - tx.ease.inOutSine(Math.max(0, (u - 0.35) / 0.45)));
  tx.fromEl.style.filter = `blur(${(a * (p.blur ?? 18)).toFixed(2)}px)`;
  tx.toEl.style.transform = `scale(${0.7 + 0.3 * b})`;
  tx.toEl.style.filter = `blur(${((1 - b) * (p.blur ?? 18) * 0.6).toFixed(2)}px)`;
  tx.toEl.style.zIndex = String(Number(tx.fromEl.style.zIndex || 0) - 1);
}

function irisCss(tx, u, p) {
  const cx = (p.x ?? 0.5) * 100, cy = (p.y ?? 0.5) * 100;
  const maxR = Math.hypot(Math.max(p.x ?? 0.5, 1 - (p.x ?? 0.5)) * tx.w, Math.max(p.y ?? 0.5, 1 - (p.y ?? 0.5)) * tx.h);
  if (p.mode === 'close') {
    // close on `from`, open on `to` (classic cartoon iris through black)
    const half = u < 0.5;
    const r = half ? (1 - tx.ease.inCubic(u * 2)) * maxR : tx.ease.outCubic((u - 0.5) * 2) * maxR;
    const el = half ? tx.fromEl : tx.toEl;
    (half ? tx.toEl : tx.fromEl).style.visibility = 'hidden';
    el.style.clipPath = `circle(${r.toFixed(1)}px at ${cx}% ${cy}%)`;
    return;
  }
  const r = tx.ease.inOutCubic(u) * maxR;
  tx.toEl.style.clipPath = `circle(${r.toFixed(1)}px at ${cx}% ${cy}%)`;
}

function wipeCss(tx, u, p) {
  const dir = p.dir || 'right';
  const soft = Math.max(0, p.soft ?? 8);
  const ang = { right: 90, left: 270, down: 180, up: 0 }[dir] ?? 90;
  const e = io(tx, u) * (100 + soft) - soft / 2;
  const m = `linear-gradient(${ang}deg, #000 ${(e - soft / 2).toFixed(2)}%, transparent ${(e + soft / 2).toFixed(2)}%)`;
  tx.toEl.style.maskImage = m;
  tx.toEl.style.webkitMaskImage = m;
}

function pageTurnCss(tx, u, p) {
  const e = tx.ease.inOutCubic(u);
  const dir = p.dir === 'right' ? 1 : -1;
  tx.fromEl.style.transformOrigin = dir < 0 ? 'left center' : 'right center';
  tx.fromEl.style.transform = `perspective(${tx.w * 1.4}px) rotateY(${dir * -e * 100}deg)`;
  tx.fromEl.style.backfaceVisibility = 'hidden';
  tx.fromEl.style.filter = `brightness(${(1 - 0.35 * Math.sin(Math.PI * Math.min(1, e * 1.1))).toFixed(3)})`;
  tx.fromEl.style.zIndex = String(Number(tx.toEl.style.zIndex || 0) + 1);
  tx.toEl.style.filter = `brightness(${(0.55 + 0.45 * e).toFixed(3)})`;
}

// ---------------------------------------------------------------------------------- canvas kinds

function scratch(tx, key, w, h) {
  const cache = tx.cache;
  let c = cache[key];
  if (!c || c.width !== w || c.height !== h) {
    c = document.createElement('canvas');
    c.width = w; c.height = h;
    cache[key] = c;
  }
  return c;
}

function glitchCanvas(tx, u, p) {
  const src = u < 0.5 ? tx.from : tx.to;
  const { g, w, h } = tx;
  g.fillStyle = '#000';
  g.fillRect(0, 0, w, h);
  if (src) tx.draw(src);
  const k = Math.sin(Math.PI * u) * (p.amount ?? 1);
  const r = tx.rng;
  const n = Math.round(6 + 18 * k);
  for (let i = 0; i < n; i++) {
    const y = Math.floor(r() * h), sh = Math.max(2, Math.floor(r() * h * 0.08 * (0.3 + k)));
    const off = (r() - 0.5) * w * 0.18 * k;
    if (src) {
      const sy = src.height / h;
      g.drawImage(src, 0, y * sy, src.width, Math.max(1, sh * sy), off, y, w, sh);
    }
  }
  // channel split: tinted copies of a half-res version, screened back with opposite offsets
  if (src && k > 0.05) {
    const sw = Math.max(1, Math.round(w / 2)), shh = Math.max(1, Math.round(h / 2));
    for (const [col, dx] of [['#ff0040', 1], ['#00e5ff', -1]]) {
      const c = scratch(tx, `split${col}`, sw, shh);
      const cg = c.getContext('2d');
      cg.globalCompositeOperation = 'source-over';
      cg.drawImage(src, 0, 0, sw, shh);
      cg.globalCompositeOperation = 'multiply';
      cg.fillStyle = col;
      cg.fillRect(0, 0, sw, shh);
      g.save();
      g.globalCompositeOperation = 'screen';
      g.globalAlpha = 0.55 * k;
      g.drawImage(c, dx * w * 0.012 * k, 0, w, h);
      g.restore();
    }
  }
  // blocky noise bars
  g.save();
  for (let i = 0; i < Math.round(10 * k); i++) {
    g.globalAlpha = 0.25 + 0.5 * r();
    g.fillStyle = r() < 0.5 ? '#fff' : (p.color || '#2fd3c0');
    g.fillRect(r() * w, r() * h, r() * w * 0.25, 2 + r() * 10);
  }
  g.restore();
}

function glitchCss(tx, u, p) {
  const r = tx.rng;
  const k = Math.sin(Math.PI * u) * (p.amount ?? 1);
  (u < 0.5 ? tx.toEl : tx.fromEl).style.visibility = 'hidden';
  const el = u < 0.5 ? tx.fromEl : tx.toEl;
  el.style.transform = `translate(${((r() - 0.5) * 60 * k).toFixed(1)}px, ${((r() - 0.5) * 16 * k).toFixed(1)}px)`;
  el.style.filter = `hue-rotate(${Math.round((r() - 0.5) * 120 * k)}deg) contrast(${(1 + 0.6 * k).toFixed(2)})`;
  const { g, w, h } = tx;
  for (let i = 0; i < Math.round(14 * k); i++) {
    g.globalAlpha = 0.3 + 0.5 * r();
    g.fillStyle = r() < 0.5 ? '#fff' : (p.color || '#2fd3c0');
    g.fillRect(r() * w, r() * h, r() * w * 0.3, 2 + r() * 12);
  }
}

function pixelateCanvas(tx, u, p) {
  const { g, w, h } = tx;
  const src = u < 0.5 ? tx.from : tx.to;
  const k = u < 0.5 ? u * 2 : (1 - u) * 2;      // 0 -> 1 -> 0
  const maxBlock = p.block ?? Math.round(Math.min(w, h) / 18);
  const block = Math.max(1, Math.round(1 + (maxBlock - 1) * tx.ease.inCubic(k)));
  g.fillStyle = '#000';
  g.fillRect(0, 0, w, h);
  if (!src) return;
  const sw = Math.max(1, Math.round(w / block)), sh = Math.max(1, Math.round(h / block));
  const c = scratch(tx, 'pix', sw, sh);
  const cg = c.getContext('2d');
  cg.imageSmoothingEnabled = true;
  cg.clearRect(0, 0, sw, sh);
  cg.drawImage(src, 0, 0, sw, sh);
  g.imageSmoothingEnabled = false;
  g.drawImage(c, 0, 0, w, h);
}

function pixelateCss(tx, u) {
  crossfadeCss(tx, u);
  const b = Math.sin(Math.PI * u) * 10;
  tx.fromEl.style.filter = `blur(${b.toFixed(2)}px)`;
  tx.toEl.style.filter = `blur(${b.toFixed(2)}px)`;
}

function burnOverlay(tx, u, p) {
  const { g, w, h } = tx;
  const k = Math.sin(Math.PI * u);
  g.save();
  g.globalCompositeOperation = 'lighter';
  const blobs = p.blobs ?? 5;
  for (let i = 0; i < blobs; i++) {
    const nx = tx.noise2(i * 3.1, u * 1.6 + tx.seed * 0.001);
    const ny = tx.noise2(i * 7.7 + 11, u * 1.3);
    const cx = w * (0.5 + 0.45 * nx), cy = h * (0.5 + 0.45 * ny);
    const rad = Math.max(w, h) * (0.25 + 0.35 * k) * (0.6 + 0.4 * Math.abs(tx.noise2(i, 5)));
    const grd = g.createRadialGradient(cx, cy, 0, cx, cy, rad);
    const warm = p.color || [255, 120, 40];
    grd.addColorStop(0, `rgba(255,240,210,${0.85 * k * k})`);
    grd.addColorStop(0.35, `rgba(${warm[0]},${warm[1]},${warm[2]},${0.55 * k})`);
    grd.addColorStop(1, 'rgba(120,20,0,0)');
    g.fillStyle = grd;
    g.fillRect(0, 0, w, h);
  }
  g.restore();
  if (k > 0.85) {
    g.globalAlpha = (k - 0.85) / 0.15 * 0.6;
    g.fillStyle = '#fff6e6';
    g.fillRect(0, 0, w, h);
    g.globalAlpha = 1;
  }
}

function filmBurnCss(tx, u, p) {
  tx.toEl.style.opacity = String(tx.ease.inOutSine(Math.max(0, Math.min(1, (u - 0.35) / 0.3))));
  burnOverlay(tx, u, p);
}

/** Static fbm field per transition (cached), thresholded by progress to make an ink mask. */
function inkField(tx, mw, mh) {
  const key = `inkfield${mw}x${mh}`;
  if (tx.cache[key]) return tx.cache[key];
  const f = new Float32Array(mw * mh);
  const sc = 3.2 / Math.max(mw, mh);
  for (let y = 0; y < mh; y++) {
    for (let x = 0; x < mw; x++) {
      const dx = (x / mw - 0.5) * (mw / mh), dy = y / mh - 0.5;
      const radial = Math.hypot(dx, dy) * 1.3;
      f[y * mw + x] = radial + 0.32 * tx.fbm2(x * sc * 4 + 3.3, y * sc * 4 - 1.7, 5);
    }
  }
  tx.cache[key] = f;
  return f;
}

function inkMask(tx, u, p, lead = 0) {
  const mw = Math.max(16, Math.round(tx.w / 8)), mh = Math.max(9, Math.round(tx.h / 8));
  const field = inkField(tx, mw, mh);
  const c = scratch(tx, lead ? 'inkfront' : 'inkmask', mw, mh);
  const cg = c.getContext('2d');
  const img = cg.createImageData(mw, mh);
  const thr = -0.35 + (tx.ease.inOutSine(u) + lead) * 1.75;
  const soft = p.soft ?? 0.05;
  for (let i = 0; i < field.length; i++) {
    const v = (thr - field[i]) / soft;
    const a = v <= 0 ? 0 : v >= 1 ? 255 : Math.round(v * v * (3 - 2 * v) * 255);
    img.data[i * 4 + 3] = a;
  }
  cg.putImageData(img, 0, 0);
  return c;
}

function inkBleedCanvas(tx, u, p) {
  const { g, w, h } = tx;
  g.fillStyle = '#000';
  g.fillRect(0, 0, w, h);
  if (tx.from) tx.draw(tx.from);
  const ink = p.ink || '#141018';
  // dark ink front just ahead of the reveal
  const front = inkMask(tx, u, p, 0.06);
  const layer = scratch(tx, 'inklayer', w, h);
  const lg = layer.getContext('2d');
  lg.globalCompositeOperation = 'source-over';
  lg.clearRect(0, 0, w, h);
  lg.fillStyle = ink;
  lg.fillRect(0, 0, w, h);
  lg.globalCompositeOperation = 'destination-in';
  lg.imageSmoothingEnabled = true;
  lg.drawImage(front, 0, 0, w, h);
  g.drawImage(layer, 0, 0);
  // the incoming shot through the main mask
  const mask = inkMask(tx, u, p, 0);
  lg.globalCompositeOperation = 'source-over';
  lg.clearRect(0, 0, w, h);
  if (tx.to) {
    const smooth = !(tx.to.dataset && tx.to.dataset.pixel === '1');
    lg.imageSmoothingEnabled = smooth;
    lg.drawImage(tx.to, 0, 0, w, h);
  }
  lg.globalCompositeOperation = 'destination-in';
  lg.imageSmoothingEnabled = true;
  lg.drawImage(mask, 0, 0, w, h);
  g.drawImage(layer, 0, 0);
}

function inkBleedCss(tx, u, p) {
  tx.toEl.style.opacity = String(tx.ease.inOutSine(Math.max(0, Math.min(1, (u - 0.25) / 0.6))));
  const front = inkMask(tx, u, p, 0.06);
  const { g, w, h } = tx;
  g.save();
  g.globalAlpha = Math.sin(Math.PI * u);
  g.imageSmoothingEnabled = true;
  const c = scratch(tx, 'inkcss', w, h);
  const cg = c.getContext('2d');
  cg.globalCompositeOperation = 'source-over';
  cg.clearRect(0, 0, w, h);
  cg.fillStyle = p.ink || '#141018';
  cg.fillRect(0, 0, w, h);
  cg.globalCompositeOperation = 'destination-in';
  cg.drawImage(front, 0, 0, w, h);
  g.drawImage(c, 0, 0);
  g.restore();
}

/** name -> definition; registered by the runtime at startup. */
export const BUILTIN_TRANSITIONS = {
  cut: { kind: 'css', render(tx, u) { (u < 0.5 ? tx.toEl : tx.fromEl).style.visibility = 'hidden'; } },
  crossfade: { kind: 'css', render: crossfadeCss },
  'dip-black': dip('#000'),
  'dip-white': dip('#fff'),
  'push-left': push('left'),
  'push-right': push('right'),
  'push-up': push('up'),
  'push-down': push('down'),
  push: push('left'),
  whip: { kind: 'css', render: whipCss },
  'zoom-through': { kind: 'css', render: zoomThroughCss },
  iris: { kind: 'css', render: irisCss },
  wipe: { kind: 'css', render: wipeCss },
  glitch: { kind: 'canvas', render: glitchCanvas, fallback: glitchCss },
  pixelate: { kind: 'canvas', render: pixelateCanvas, fallback: pixelateCss },
  'film-burn': { kind: 'css', render: filmBurnCss },
  'ink-bleed': { kind: 'canvas', render: inkBleedCanvas, fallback: inkBleedCss },
  'page-turn': { kind: 'css', render: pageTurnCss },
};
