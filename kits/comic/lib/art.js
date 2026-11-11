// Hype kit "comic" — art primitives: palette, true halftone screens, sunburst rays, speed lines, burst
// balloons, speech tails, silhouette figures (built only from primitive shapes), skyline. Everything is built
// once in a scene's build() (static art); scenes animate transforms only. Deterministic (seeded mulberry32).

import { h } from '../../base/dom.js';
import { rng } from '../../base/motion.js';

export const C = {
  ink: '#14110F', paper: '#F4EAD2', paper2: '#E6D6B0', white: '#FFFDF6', cyan: '#29B6E3', magenta: '#E33D7F',
  yellow: '#FFD23A', red: '#E2392B', blue: '#1D5FC2', green: '#2FAE4F', orange: '#F68B1F', grey: '#9A9088',
};
const col = (c) => C[c] || c;
const NS = 'http://www.w3.org/2000/svg';

/** SVG element from markup (our own static strings only). */
export function svgEl(doc, w, hh, inner, o = {}) {
  const s = doc.createElementNS(NS, 'svg');
  s.setAttribute('width', String(w));
  s.setAttribute('height', String(hh));
  s.setAttribute('viewBox', o.viewBox || `0 0 ${w} ${hh}`);
  s.setAttribute('style', `overflow:visible;${o.style || ''}`);
  s.innerHTML = inner;
  return s;
}

/** SVG path data for a set of dots [[x, y, r], ...] (one path: a single fill call, crisp at any zoom). */
export function dotsPath(dots) {
  let d = '';
  for (const [x, y, r] of dots) {
    const rr = r.toFixed(2);
    d += `M${(x - r).toFixed(1)},${y.toFixed(1)}a${rr},${rr} 0 1,0 ${(2 * r).toFixed(2)},0a${rr},${rr} 0 1,0 ${(-2 * r).toFixed(2)},0`;
  }
  return d;
}

/** Image decodes started while building (printed shots); comicScene's setup awaits them. */
export const PENDING = [];

/**
 * Flatten a drawn canvas into an <img> (PNG data URL) — only for the rare non-image media fallback. Art is
 * vector (SVG) instead: a canvas becomes its own composited layer and bitmaps resample through mip levels that
 * depend on seek history when the camera zoom changes (the dry-run determinism probe catches both).
 */
export function flat(c) {
  const img = c.ownerDocument.createElement('img');
  img.className = c.className;
  img.style.cssText = c.style.cssText;
  img.decoding = 'sync';
  img.draggable = false;
  img.src = c.toDataURL('image/png');
  PENDING.push(img.decode().catch(() => {}));
  return img;
}

/**
 * True halftone: a rotated dot screen whose dot radius follows a density f(u, v) in 0..1 (u, v = 0..1 over the
 * box), as one SVG path (vector: re-rasterised crisply at every camera zoom, deterministic). Returns the <svg>
 * sized w x h (CSS px). o: {color, cell, angle, f, max, bg, blend}.
 */
export function halftone(doc, w, hh, o = {}) {
  const cell = o.cell || 16, max = o.max ?? 0.62, f = o.f || (() => 0.5);
  const a = ((o.angle ?? 15) * Math.PI) / 180, ca = Math.cos(a), sa = Math.sin(a);
  const n = Math.ceil(Math.hypot(w, hh) / cell);
  const dots = [];
  for (let i = -n; i < n; i++) {
    for (let j = -n; j < n; j++) {
      const px = w / 2 + (i * ca - j * sa) * cell, py = hh / 2 + (i * sa + j * ca) * cell;
      if (px < -cell || py < -cell || px > w + cell || py > hh + cell) continue;
      const v = Math.max(0, Math.min(1, f(px / w, py / hh)));
      const rad = Math.sqrt(v) * cell * max;
      if (rad < 0.6) continue;
      dots.push([px, py, rad]);
    }
  }
  const bg = o.bg ? `<rect width="${w}" height="${hh}" fill="${col(o.bg)}"/>` : '';
  const s = svgEl(doc, w, hh, `${bg}<path fill="${col(o.color || 'magenta')}" d="${dotsPath(dots)}"/>`,
    { style: `position:absolute;left:0;top:0;overflow:hidden;${o.blend ? `mix-blend-mode:${o.blend};` : ''}` });
  s.setAttribute('class', 'cx-tone');
  return s;
}

/** Sunburst wedges radiating from (cx, cy) as an SVG big enough to rotate freely. Returns {el, cx, cy, R}. */
export function rays(doc, w, hh, cx, cy, n, color, seed = 1, inner = 0) {
  const r = rng(seed);
  const R = Math.hypot(Math.max(cx, w - cx), Math.max(cy, hh - cy)) + 40;
  let d = '';
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + r() * 0.05, wd = ((Math.PI * 2) / n) * (0.25 + r() * 0.3);
    const p = (ang, rr) => `${(R + Math.cos(ang) * rr).toFixed(1)},${(R + Math.sin(ang) * rr).toFixed(1)}`;
    d += `M${p(a, inner)}L${p(a - wd / 2, R)}L${p(a + wd / 2, R)}Z`;
  }
  const el = svgEl(doc, 2 * R, 2 * R, `<path d="${d}" fill="${col(color)}"/>`);
  el.setAttribute('class', 'cx-rays');
  el.style.left = `${(cx - R).toFixed(1)}px`;
  el.style.top = `${(cy - R).toFixed(1)}px`;
  return { el, cx, cy, R };
}

/** Focus (speed) lines: thin ink wedges from the box edge toward (cx, cy), leaving a clear centre. */
export function speedLines(doc, w, hh, cx, cy, o = {}) {
  const r = rng(o.seed || 5);
  const n = o.n || 70, R = Math.hypot(w, hh), clear = o.clear || Math.min(w, hh) * 0.36;
  let d = '';
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + r() * 0.09;
    const len = clear + r() * clear * 0.5;
    const wd = 0.004 + r() * 0.012;
    const p = (ang, rr) => `${(cx + Math.cos(ang) * rr).toFixed(1)},${(cy + Math.sin(ang) * rr).toFixed(1)}`;
    d += `M${p(a, len)}L${p(a - wd, R)}L${p(a + wd, R)}Z`;
  }
  return svgEl(doc, w, hh, `<path d="${d}" fill="${col(o.color || 'ink')}"/>`, { style: 'position:absolute;left:0;top:0;' });
}

/** Jagged burst polygon points (explosion balloon), inset for the stroke + shadow. */
function burstPts(w, hh, spikes, depth, seed, inset) {
  const r = rng(seed), cx = w / 2, cy = hh / 2, pts = [];
  for (let i = 0; i < spikes * 2; i++) {
    const a = (i / (spikes * 2)) * Math.PI * 2 - Math.PI / 2;
    const k = i % 2 ? 1 - depth - r() * 0.08 : 1 - r() * 0.06;
    pts.push([cx + Math.cos(a) * (w / 2 - inset) * k, cy + Math.sin(a) * (hh / 2 - inset) * k]);
  }
  return pts;
}

/** Burst balloon as an SVG string (hard offset shadow + filled, ink-stroked polygon). */
export function burstSvg(o) {
  const { w, h: hh } = o;
  const sw = o.sw ?? 8, shadow = o.shadow ?? 10;
  const pts = burstPts(w, hh, o.spikes || 16, o.depth ?? 0.28, o.seed || 2, sw + shadow).map((p) => p.map((v) => v.toFixed(1)).join(',')).join(' ');
  return `<polygon points="${pts}" transform="translate(${shadow},${shadow})" fill="${C.ink}"/>` +
    `<polygon points="${pts}" fill="${col(o.fill || 'yellow')}" stroke="${C.ink}" stroke-width="${sw}" stroke-linejoin="miter"/>`;
}

/** A positioned burst element with an optional label. Returns {el, label, w, h}. */
export function burst(doc, o) {
  const el = h('div', 'cx-burst');
  el.style.cssText = `width:${o.w}px;height:${o.h}px;`;
  el.appendChild(svgEl(doc, o.w, o.h, burstSvg(o)));
  let label = null;
  if (o.text != null) {
    label = h('div', 'cx-bl');
    label.style.fontSize = `${o.size || 60}px`;
    if (o.color) label.style.color = col(o.color);
    if (o.pad) label.style.padding = o.pad;
    const lines = String(o.text).split('\n');
    lines.forEach((line, i) => { if (i) label.appendChild(h('br')); label.append(line); });
    el.appendChild(label);
  }
  return { el, label, w: o.w, h: o.h };
}

/** Burst polygon as a CSS clip-path polygon() in % of the box (for iris transitions and masks). */
export function burstClip(spikes, depth, seed) {
  return burstPts(100, 100, spikes, depth, seed, 0).map(([x, y]) => `${x.toFixed(2)}% ${y.toFixed(2)}%`).join(',');
}

/**
 * Speech-balloon tail: wedge from (x0, y0) on the balloon edge to the tip (x1, y1), width wd, bent sideways;
 * filled white with ink sides; tucks under the balloon border. Returns an SVG element (panel coords).
 */
export function tail(doc, x0, y0, x1, y1, wd = 60, bend = 0.22, o = {}) {
  const dx = x1 - x0, dy = y1 - y0, L = Math.hypot(dx, dy) || 1, nx = -dy / L, ny = dx / L;
  const a = [x0 + (nx * wd) / 2, y0 + (ny * wd) / 2], b = [x0 - (nx * wd) / 2, y0 - (ny * wd) / 2];
  const m = [x0 + dx * 0.55 + nx * L * bend, y0 + dy * 0.55 + ny * L * bend];
  const f = (p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`;
  const s = svgEl(doc, 1, 1, `<path d="M${f(a)} Q${f(m)} ${x1.toFixed(1)},${y1.toFixed(1)} Q${f(m)} ${f(b)} Z" fill="${col(o.fill || 'white')}" stroke="${C.ink}" stroke-width="5" stroke-linejoin="round"/>`);
  s.setAttribute('class', 'cx-tail');
  return s;
}

// ------------------------------------------------------------------------------------------- figures
// swept-back helmet wing with three feather tips; s = +1 left side, -1 mirrored right side
const wing = (x, y, s) => `<path transform="translate(${x},${y}) scale(${s},1) rotate(-32)" d="M0 8 C-18 -2 -34 -22 -44 -58 C-30 -44 -22 -38 -14 -34 C-26 -54 -30 -74 -26 -96 C-14 -70 -4 -56 6 -44 C2 -62 4 -78 12 -92 C16 -62 18 -38 14 -6 Z"/>`;

/**
 * The agent: a heroic silhouette (winged helmet, play-button chest emblem, film reel). poses:
 * 'hero' (fist raised with a reel; viewBox -90 -80 560 800), 'type' (seated at a desk typing, side view;
 * 0 0 420 480), 'bust' (head and shoulders; 0 0 420 360), 'point' (arm out to the right; -90 -80 600 800).
 * Returns an SVG markup string sized by the container (width 100%).
 */
export function agentSvg({ pose = 'hero', fill = 'ink', rim = 'cyan', cape = 'red', emblem = 'yellow' } = {}) {
  const F = col(fill), R = col(rim), Cc = col(cape), E = col(emblem);
  const reel = (x, y) => `<g transform="translate(${x},${y})"><circle r="60" fill="${F}"/><circle r="51" fill="${E}" stroke="${F}" stroke-width="6"/>` +
    [0, 1, 2, 3, 4].map((i) => `<circle cx="${(Math.cos(i * 1.2566 - 1.57) * 29).toFixed(1)}" cy="${(Math.sin(i * 1.2566 - 1.57) * 29).toFixed(1)}" r="11" fill="${F}"/>`).join('') +
    `<circle r="8" fill="${F}"/></g>`;
  const head = `<ellipse cx="210" cy="112" rx="44" ry="52"/>${wing(172, 108, 1)}${wing(248, 108, -1)}<rect x="190" y="150" width="40" height="40"/>`;
  const torso = '<path d="M118 186 C150 168 270 168 302 186 L328 234 C320 272 298 302 274 330 L264 412 L156 412 L146 330 C122 302 100 272 92 234 Z"/>';
  const legs = '<path d="M160 404 L136 524 L104 694 L158 700 L184 544 L210 438 Z"/><path d="M260 404 L284 524 L316 694 L262 700 L236 544 L210 438 Z"/>';
  const emblemSvg = `<path d="M190 230 L246 262 L190 294 Z" fill="${E}" stroke="${F}" stroke-width="5"/>`;
  const belt = `<rect x="154" y="330" width="112" height="16" fill="${E}" stroke="${F}" stroke-width="4"/>`;
  if (pose === 'hero' || pose === 'point') {
    const armR = pose === 'hero'
      ? '<path d="M290 192 L324 176 L364 116 L392 50 L360 34 L332 104 L292 158 Z"/><circle cx="378" cy="40" r="28"/>'
      : '<path d="M290 190 L340 196 L430 196 L498 186 L500 222 L432 232 L340 236 L296 232 Z"/><circle cx="508" cy="204" r="26"/>';
    const armL = '<path d="M122 190 L94 208 L54 284 L74 304 L152 360 L164 332 L102 286 L130 238 Z"/>';
    const body = head + torso + armR + armL + legs;
    return `<svg viewBox="${pose === 'hero' ? '-90 -80 560 800' : '-90 -80 620 800'}" width="100%" style="overflow:visible">` +
      `<path d="M124 190 C64 300 14 480 -80 646 C-22 626 18 656 58 706 C90 646 122 606 162 566 L204 420 Z" fill="${Cc}" stroke="${F}" stroke-width="8" stroke-linejoin="round"/>` +
      `<path d="M124 190 C80 320 40 500 -20 640 L58 660 L110 560 Z" fill="${F}" opacity=".25"/>` +
      `<g fill="${R}" transform="translate(10,-5)">${body}</g><g fill="${F}">${body}</g>${belt}${emblemSvg}` +
      (pose === 'hero' ? reel(386, -14) : '') + '</svg>';
  }
  if (pose === 'bust') {
    const b = '<ellipse cx="210" cy="132" rx="58" ry="68"/>' + wing(162, 126, 1).replace('rotate(-32)', 'rotate(-32) scale(1.3)') +
      wing(258, 126, -1).replace('rotate(-32)', 'rotate(-32) scale(1.3)') + '<rect x="184" y="188" width="52" height="50"/>' +
      '<path d="M40 380 C48 286 120 236 210 234 C300 236 372 286 380 380 Z"/>';
    return `<svg viewBox="0 0 420 380" width="100%" style="overflow:visible"><g fill="${R}" transform="translate(9,-5)">${b}</g><g fill="${F}">${b}</g>` +
      `<path d="M182 290 L246 318 L182 346 Z" fill="${E}" stroke="${F}" stroke-width="5"/></svg>`;
  }
  // seated at a desk typing, side view facing right (desk + keyboard + monitor stand included)
  const body = `<circle cx="150" cy="112" r="44"/>${wing(116, 104, 1)}` +
    '<path d="M128 150 L176 152 C214 170 230 210 232 252 L222 320 L118 330 C104 270 104 200 128 150 Z"/>' +
    '<path d="M190 176 C230 196 252 236 262 270 L330 278 L332 300 L248 300 C230 280 206 240 188 214 Z"/>' +
    '<path d="M126 304 L262 300 L276 440 L238 444 L228 342 L126 346 Z"/>';
  const chair = '<rect x="40" y="340" width="150" height="20" rx="4"/><rect x="40" y="190" width="22" height="160" rx="6"/><rect x="102" y="356" width="18" height="110"/><rect x="62" y="456" width="96" height="12" rx="6"/>';
  const desk = '<rect x="296" y="300" width="960" height="20"/><rect x="1200" y="318" width="22" height="160"/><rect x="300" y="286" width="120" height="14" rx="3"/><rect x="845" y="262" width="60" height="40"/>';
  return `<svg viewBox="0 0 420 480" width="100%" style="overflow:visible"><g fill="${F}">${chair}${desk}</g><g fill="${R}" transform="translate(7,-4)">${body}</g><g fill="${F}">${body}</g></svg>`;
}

/** The user: head-and-shoulders bust from primitives with an offset rim colour (viewBox 0 0 300 330). */
export function userSvg({ fill = 'ink', rim = 'magenta' } = {}) {
  const shape = '<circle cx="150" cy="120" r="78"/><path d="M60 92 C70 30 150 10 210 40 C240 56 248 90 236 110 C200 80 120 70 60 92 Z"/>' +
    '<path d="M10 330 C20 230 90 200 150 200 C210 200 280 230 290 330 Z"/>';
  return `<svg viewBox="0 0 300 330" width="100%" style="overflow:visible"><g fill="${col(rim)}" transform="translate(-8,-4)">${shape}</g><g fill="${col(fill)}">${shape}</g></svg>`;
}

/** Figure container: absolutely placed, width in px (height follows the viewBox aspect). */
export function figure(markup, x, y, w) {
  const el = h('div', 'cx-fig', { html: markup });
  el.style.cssText = `left:${x}px;top:${y}px;width:${w}px;`;
  return el;
}

/** Skyline of terminal-window towers (seeded): cyan/blue blocks with lit "code" windows. */
export function skyline(doc, w, hh, seed = 9) {
  const r = rng(seed);
  let s = '';
  for (let x = -10; x < w + 10;) {
    const bw = 70 + Math.floor(r() * 90), bh = Math.round(hh * (0.32 + r() * 0.58)), c = r() > 0.5 ? C.blue : C.cyan;
    s += `<rect x="${x}" y="${hh - bh}" width="${bw}" height="${bh + 10}" fill="${c}" stroke="${C.ink}" stroke-width="6"/>`;
    s += `<rect x="${x}" y="${hh - bh}" width="${bw}" height="16" fill="${C.ink}"/>`;
    for (let yy = hh - bh + 30; yy < hh - 10; yy += 26) {
      for (let xx = x + 12; xx < x + bw - 18; xx += 22 + Math.floor(r() * 14)) {
        const ww = 8 + Math.floor(r() * 18);
        if (xx + ww > x + bw - 10) continue;
        s += `<rect x="${xx}" y="${yy}" width="${ww}" height="7" fill="${r() > 0.3 ? C.yellow : C.white}"/>`;
      }
    }
    x += bw - 4;
  }
  return svgEl(doc, w, hh, s, { style: 'position:absolute;' });
}

/** Ink check mark (thick ink under a coloured stroke). */
export function checkSvg(colour = 'green', sw = 16) {
  return `<svg viewBox="0 0 100 100" width="100%" height="100%" style="overflow:visible"><path d="M8 54 L38 84 L94 16" fill="none" stroke="${C.ink}" stroke-width="${sw * 2.1}" stroke-linecap="square"/>` +
    `<path d="M8 54 L38 84 L94 16" fill="none" stroke="${col(colour)}" stroke-width="${sw}" stroke-linecap="square"/></svg>`;
}

/** Ink splat (a seeded blob with droplets) behind a stamp. */
export function splatSvg(seed = 3, colour = 'ink') {
  const r = rng(seed);
  const pts = [];
  const n = 18;
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2, rr = 34 + r() * 14 + (i % 3 === 0 ? r() * 16 : 0);
    pts.push([50 + Math.cos(a) * rr, 50 + Math.sin(a) * rr]);
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 1; i <= n; i++) {
    const p = pts[i % n], q = pts[(i - 1) % n];
    d += ` Q${((p[0] + q[0]) / 2 + (r() - 0.5) * 8).toFixed(1)},${((p[1] + q[1]) / 2 + (r() - 0.5) * 8).toFixed(1)} ${p[0].toFixed(1)},${p[1].toFixed(1)}`;
  }
  let drops = '';
  for (let i = 0; i < 6; i++) {
    const a = r() * Math.PI * 2, rr = 58 + r() * 18;
    drops += `<circle cx="${(50 + Math.cos(a) * rr).toFixed(1)}" cy="${(50 + Math.sin(a) * rr).toFixed(1)}" r="${(2.5 + r() * 4).toFixed(1)}"/>`;
  }
  return `<svg viewBox="0 0 100 100" width="100%" height="100%" style="overflow:visible"><g fill="${col(colour)}"><path d="${d} Z"/>${drops}</g></svg>`;
}

/** Comic cursor: white glove-free arrow with a heavy ink outline. */
export const CURSOR_SVG = `<svg viewBox="0 0 32 38" width="100%" height="100%" style="overflow:visible"><path d="M3 2.5v26.5l7-6.6 4.8 11.4 5-2.2-4.8-11.1h9.6z" fill="${C.white}" stroke="${C.ink}" stroke-width="3" stroke-linejoin="round"/></svg>`;
