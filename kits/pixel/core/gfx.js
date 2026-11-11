// gfx.js — index-buffer drawing for the pixel kit. One Screen = one game-resolution surface
// (e.g. 480x270); every write is a palette index, so off-palette colours cannot happen.
import { ci, NONE, WORDS, bayer } from './palette.js';

/** A sprite: w x h palette indices, NONE = transparent. */
export class Sprite {
  /** @param {number} w @param {number} h @param {Uint8Array} [d] */
  constructor(w, h, d) { this.w = w; this.h = h; this.d = d || new Uint8Array(w * h).fill(NONE); }
  get(x, y) { return (x < 0 || y < 0 || x >= this.w || y >= this.h) ? NONE : this.d[y * this.w + x]; }
  set(x, y, c) { if (x >= 0 && y >= 0 && x < this.w && y < this.h) this.d[y * this.w + x] = ci(c); }
  clone() { return new Sprite(this.w, this.h, this.d.slice()); }

  /** Build from string rows; `map` maps chars to palette tokens. '.' and ' ' are transparent. */
  static rows(rows, map) {
    const w = Math.max(...rows.map(r => r.length)), s = new Sprite(w, rows.length);
    rows.forEach((r, y) => { for (let x = 0; x < r.length; x++) { const ch = r[x]; if (ch !== '.' && ch !== ' ') s.d[y * w + x] = ci(map[ch] ?? ch); } });
    return s;
  }
  /** Copy with a 1-px ring of `c` around filled pixels (grows by 1 px on every side). */
  outlined(c = 'ink', diag = false) {
    const o = new Sprite(this.w + 2, this.h + 2), k = ci(c);
    for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) o.d[(y + 1) * o.w + x + 1] = this.d[y * this.w + x];
    const src = o.d.slice();
    for (let y = 0; y < o.h; y++) for (let x = 0; x < o.w; x++) {
      if (src[y * o.w + x] !== NONE) continue;
      const g = (i, j) => (i >= 0 && j >= 0 && i < o.w && j < o.h) && src[j * o.w + i] !== NONE;
      if (g(x - 1, y) || g(x + 1, y) || g(x, y - 1) || g(x, y + 1) || (diag && (g(x - 1, y - 1) || g(x + 1, y - 1) || g(x - 1, y + 1) || g(x + 1, y + 1)))) o.d[y * o.w + x] = k;
    }
    return o;
  }
  flipX() { const o = new Sprite(this.w, this.h); for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) o.d[y * this.w + x] = this.d[y * this.w + this.w - 1 - x]; return o; }
  flipY() { const o = new Sprite(this.w, this.h); for (let y = 0; y < this.h; y++) o.d.set(this.d.subarray((this.h - 1 - y) * this.w, (this.h - y) * this.w), y * this.w); return o; }
  /** 90-degree clockwise rotation (exact; for 8-direction spin cycles). */
  rot90() { const o = new Sprite(this.h, this.w); for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) o.d[x * o.w + (this.h - 1 - y)] = this.d[y * this.w + x]; return o; }
  /** Copy with colours replaced via {token: token} or a 256-entry remap table. */
  recolor(map) {
    const o = this.clone();
    if (map instanceof Uint8Array) { for (let i = 0; i < o.d.length; i++) if (o.d[i] !== NONE) o.d[i] = map[o.d[i]]; return o; }
    const m = new Map(Object.entries(map).map(([a, b]) => [ci(a), ci(b)]));
    for (let i = 0; i < o.d.length; i++) if (m.has(o.d[i])) o.d[i] = m.get(o.d[i]);
    return o;
  }
  /** Silhouette in one colour. */
  solid(c) { const o = this.clone(), k = ci(c); for (let i = 0; i < o.d.length; i++) if (o.d[i] !== NONE) o.d[i] = k; return o; }
  /** Integer upscale (k >= 1). */
  scaled(k) { const o = new Sprite(this.w * k, this.h * k); for (let y = 0; y < o.h; y++) for (let x = 0; x < o.w; x++) o.d[y * o.w + x] = this.d[((y / k) | 0) * this.w + ((x / k) | 0)]; return o; }
  /** Bounding box of opaque pixels {x, y, w, h} (null when empty) — place cutouts by their real feet. */
  bounds() {
    let x0 = this.w, y0 = this.h, x1 = -1, y1 = -1;
    for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) if (this.d[y * this.w + x] !== NONE) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    return x1 < 0 ? null : { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
  }
  /** Paste another sprite into this one at (x, y). */
  paste(s, x, y) { for (let j = 0; j < s.h; j++) for (let i = 0; i < s.w; i++) { const c = s.d[j * s.w + i]; if (c !== NONE) this.set(x + i, y + j, c); } return this; }
}

/** A game-resolution framebuffer of palette indices. */
export class Screen {
  /** @param {number} w @param {number} h */
  constructor(w, h) {
    this.w = w; this.h = h; this.d = new Uint8Array(w * h);
    this.cx0 = 0; this.cy0 = 0; this.cx1 = w; this.cy1 = h;   // clip rect [x0,x1) x [y0,y1)
    this._img = null; this._u32 = null;
  }
  clip(x = 0, y = 0, w = this.w, h = this.h) {
    this.cx0 = Math.max(0, x | 0); this.cy0 = Math.max(0, y | 0);
    this.cx1 = Math.min(this.w, (x + w) | 0); this.cy1 = Math.min(this.h, (y + h) | 0); return this;
  }
  unclip() { return this.clip(); }
  fill(c) { this.d.fill(ci(c)); return this; }
  px(x, y, c) { x |= 0; y |= 0; if (x >= this.cx0 && y >= this.cy0 && x < this.cx1 && y < this.cy1) this.d[y * this.w + x] = ci(c); }
  get(x, y) { x |= 0; y |= 0; return (x < 0 || y < 0 || x >= this.w || y >= this.h) ? NONE : this.d[y * this.w + x]; }
  rect(x, y, w, h, c) {
    const k = ci(c); if (k === NONE) return;
    const x0 = Math.max(this.cx0, Math.round(x)), y0 = Math.max(this.cy0, Math.round(y));
    const x1 = Math.min(this.cx1, Math.round(x) + Math.round(w)), y1 = Math.min(this.cy1, Math.round(y) + Math.round(h));
    for (let j = y0; j < y1; j++) this.d.fill(k, j * this.w + x0, j * this.w + Math.max(x0, x1));
  }
  /** Rectangle outline 1 px thick. */
  frame(x, y, w, h, c) { this.rect(x, y, w, 1, c); this.rect(x, y + h - 1, w, 1, c); this.rect(x, y, 1, h, c); this.rect(x + w - 1, y, 1, h, c); }
  /** Ordered-dither `c` over a rect with density t (0..1). */
  dither(x, y, w, h, c, t) {
    const k = ci(c);
    for (let j = Math.max(this.cy0, y | 0); j < Math.min(this.cy1, (y + h) | 0); j++)
      for (let i = Math.max(this.cx0, x | 0); i < Math.min(this.cx1, (x + w) | 0); i++) if (bayer(i, j) < t) this.d[j * this.w + i] = k;
  }
  /** Vertical stepped gradient: solid bands with an ordered-dither seam. */
  vbands(x, y, w, h, cols, seam = 3) {
    const n = cols.length, bh = h / n, ks = cols.map(ci);
    for (let j = 0; j < h; j++) {
      const k = Math.min(n - 1, Math.floor(j / bh)), local = j - k * bh, yy = y + j;
      if (yy < this.cy0 || yy >= this.cy1) continue;
      for (let i = 0; i < w; i++) {
        const xx = x + i; if (xx < this.cx0 || xx >= this.cx1) continue;
        let c = ks[k];
        if (k < n - 1 && local > bh - seam && bayer(xx, yy) < ((local - (bh - seam)) / seam) * 0.5) c = ks[k + 1];
        else if (k > 0 && local < seam && bayer(xx, yy) < (1 - local / seam) * 0.5) c = ks[k - 1];
        this.d[yy * this.w + xx] = c;
      }
    }
  }
  /** Bresenham-ish line of square brush `t`. */
  line(x0, y0, x1, y1, c, t = 1) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    const n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0), 1), o = t >> 1;
    for (let i = 0; i <= n; i++) this.rect(Math.round(x0 + (x1 - x0) * i / n) - o, Math.round(y0 + (y1 - y0) * i / n) - o, t, t, c);
  }
  /** Filled ellipse (centre, radii) — pixel-centred test, symmetric. */
  ellipse(cx, cy, rx, ry, c, ditherT = 1) {
    const k = ci(c);
    for (let y = Math.floor(cy - ry); y <= Math.ceil(cy + ry); y++) {
      if (y < this.cy0 || y >= this.cy1) continue;
      for (let x = Math.floor(cx - rx); x <= Math.ceil(cx + rx); x++) {
        if (x < this.cx0 || x >= this.cx1) continue;
        const nx = (x + 0.5 - cx) / rx, ny = (y + 0.5 - cy) / ry;
        if (nx * nx + ny * ny <= 1 && (ditherT >= 1 || bayer(x, y) < ditherT)) this.d[y * this.w + x] = k;
      }
    }
  }
  /** Ring of thickness th between radii r-th..r. */
  ring(cx, cy, r, th, c) {
    const k = ci(c);
    for (let y = Math.floor(cy - r); y <= Math.ceil(cy + r); y++) for (let x = Math.floor(cx - r); x <= Math.ceil(cx + r); x++) {
      const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy);
      if (d <= r && d > r - th) this.px(x, y, k);
    }
  }
  /** Filled convex/concave polygon via even-odd scanlines. pts: [[x,y],...]. */
  poly(pts, c) {
    const k = ci(c);
    let y0 = Infinity, y1 = -Infinity; for (const [, y] of pts) { y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    for (let y = Math.max(this.cy0, Math.floor(y0)); y <= Math.min(this.cy1 - 1, Math.ceil(y1)); y++) {
      const yc = y + 0.5, xs = [];
      for (let i = 0; i < pts.length; i++) {
        const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length];
        if ((ay <= yc && by > yc) || (by <= yc && ay > yc)) xs.push(ax + (yc - ay) / (by - ay) * (bx - ax));
      }
      xs.sort((a, b) => a - b);
      for (let i = 0; i + 1 < xs.length; i += 2) {
        const a = Math.max(this.cx0, Math.round(xs[i])), b = Math.min(this.cx1, Math.round(xs[i + 1]));
        if (b > a) this.d.fill(k, y * this.w + a, y * this.w + b);
      }
    }
  }
  /**
   * Draw a sprite at integer (x, y).
   * o: {flip, remap (Uint8Array), solid (token), only (token), alpha (0..1 ordered-dither coverage), scale (int)}
   */
  blit(s, x, y, o = {}) {
    if (!s) return;
    x = Math.round(x); y = Math.round(y);
    const k = o.scale | 0 || 1, flip = !!o.flip, rm = o.remap || null, solid = o.solid != null ? ci(o.solid) : NONE;
    const only = o.only != null ? ci(o.only) : NONE, a = o.alpha ?? 1;
    const W = s.w * k, H = s.h * k;
    const i0 = Math.max(0, this.cx0 - x), i1 = Math.min(W, this.cx1 - x);
    const j0 = Math.max(0, this.cy0 - y), j1 = Math.min(H, this.cy1 - y);
    for (let j = j0; j < j1; j++) {
      const sy = (j / k) | 0, row = (y + j) * this.w;
      for (let i = i0; i < i1; i++) {
        const sx = (i / k) | 0, c = s.d[sy * s.w + (flip ? s.w - 1 - sx : sx)];
        if (c === NONE || (only !== NONE && c !== only)) continue;
        if (a < 1 && bayer(x + i, y + j) >= a) continue;
        this.d[row + x + i] = solid !== NONE ? solid : rm ? rm[c] : c;
      }
    }
  }
  /** Apply a remap table to a rect (optionally only where bayer < t, for dithered tints). */
  remap(map, x = 0, y = 0, w = this.w, h = this.h, t = 1) {
    for (let j = Math.max(0, y | 0); j < Math.min(this.h, (y + h) | 0); j++)
      for (let i = Math.max(0, x | 0); i < Math.min(this.w, (x + w) | 0); i++)
        if (t >= 1 || bayer(i, j) < t) { const p = j * this.w + i; this.d[p] = map[this.d[p]]; }
  }
  /**
   * Radial light/tint: applies `map` with ordered-dither coverage falling off from 1 at the centre to 0 at r.
   * `k` scales coverage (>1 = solid core), `sy` squashes vertically (floor pools).
   */
  glow(cx, cy, r, map, k = 1.4, sy = 1) {
    const ry = r * sy;
    for (let j = Math.max(this.cy0, Math.floor(cy - ry)); j < Math.min(this.cy1, Math.ceil(cy + ry)); j++)
      for (let i = Math.max(this.cx0, Math.floor(cx - r)); i < Math.min(this.cx1, Math.ceil(cx + r)); i++) {
        const dx = (i + 0.5 - cx) / r, dy = (j + 0.5 - cy) / ry, d = dx * dx + dy * dy;
        if (d >= 1) continue;
        if (bayer(i, j) < (1 - Math.sqrt(d)) * k) { const p = j * this.w + i; this.d[p] = map[this.d[p]]; }
      }
  }
  /**
   * Lighting pass over a rect: each pixel's light level l = max over lights of (1 - d/r) picks one of
   * `maps` (dark -> bright remap tables; null = leave as is) with ordered-dither blending between levels.
   * lights: [{x, y, r, sy?, k?}] in screen coords (sy squashes vertically, k scales intensity).
   */
  light(lights, maps, x = 0, y = 0, w = this.w, h = this.h, spread = 0.9) {
    const n = maps.length;
    for (let j = Math.max(0, y | 0); j < Math.min(this.h, (y + h) | 0); j++)
      for (let i = Math.max(0, x | 0); i < Math.min(this.w, (x + w) | 0); i++) {
        let l = 0;
        for (const L of lights) {
          const dx = (i + 0.5 - L.x) / L.r, dy = (j + 0.5 - L.y) / (L.r * (L.sy || 1)), d = Math.sqrt(dx * dx + dy * dy);
          if (d < 1) l = Math.max(l, (1 - d) * (L.k || 1));
        }
        const lv = Math.max(0, Math.min(n - 1, Math.floor(l * (n - 0.2) + (bayer(i, j) - 0.5) * spread)));
        const m = maps[lv]; if (m) { const p = j * this.w + i; this.d[p] = m[this.d[p]]; }
      }
  }
  /** Copy a region of this screen into a new Sprite. */
  grab(x, y, w, h) { const s = new Sprite(w, h); for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) s.d[j * w + i] = this.get(x + i, y + j); return s; }
  /** Scroll the whole buffer by integer (dx, dy), filling exposed pixels with `c` (screen shake). */
  shift(dx, dy, c = 'ink') {
    dx = Math.round(dx); dy = Math.round(dy); if (!dx && !dy) return;
    const src = this.d.slice(), k = ci(c);
    for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) {
      const sx = x - dx, sy = y - dy;
      this.d[y * this.w + x] = (sx < 0 || sy < 0 || sx >= this.w || sy >= this.h) ? k : src[sy * this.w + sx];
    }
  }
  /** Write the buffer to a 2D context at (0,0) (putImageData; 1 screen px = 1 canvas px); `words` = palette words. */
  present(g, words = WORDS) {
    if (!this._img) { this._img = g.createImageData(this.w, this.h); this._u32 = new Uint32Array(this._img.data.buffer); }
    const u = this._u32, d = this.d;
    for (let i = 0; i < d.length; i++) u[i] = words[d[i]];
    g.putImageData(this._img, 0, 0);
    return this._img;
  }
}
