// ctx.text: readable text on a 2D surface + QA box registration (SDK §4 "Text").
// Boxes are reported in FILM pixels (surface px x surface->film scale), with the effective glyph size,
// so __sr.qa(t) can flag small, clipped, unsafe or overlapping text.

const PIXEL_CACHE = new Map();
const PIXEL_CACHE_MAX = 400;

/** Build a CSS font string from {font, size, weight, style} (a full CSS font with 'px' passes through). */
export function cssFont(o) {
  const f = o.font || 'sans-serif';
  if (/\d+(\.\d+)?px/.test(f)) return f;
  const fam = /[",]/.test(f) || /^(serif|sans-serif|monospace|system-ui|cursive|fantasy)$/.test(f) ? f : `"${f}"`;
  return `${o.style || 'normal'} ${o.weight || 400} ${o.size || 32}px ${fam}`;
}

/** Font size in px parsed back out of a CSS font string. */
export function fontPx(font) {
  const m = /(\d+(?:\.\d+)?)px/.exec(font);
  return m ? Number(m[1]) : 16;
}

/** Greedy word wrap honouring '\n'; words wider than maxWidth are broken by characters. */
export function wrapLines(g, text, maxWidth) {
  const out = [];
  for (const para of String(text).split('\n')) {
    if (!maxWidth || maxWidth <= 0) { out.push(para); continue; }
    const words = para.split(/(\s+)/).filter((w) => w.length);
    let line = '';
    for (const w of words) {
      const cand = line + w;
      if (g.measureText(cand.trimEnd()).width <= maxWidth || line.trim() === '') {
        if (g.measureText(cand.trim()).width > maxWidth && line.trim() === '') {
          // single overlong word: break by characters
          let chunk = '';
          for (const ch of w) {
            if (g.measureText(chunk + ch).width > maxWidth && chunk) { out.push(chunk); chunk = ch; }
            else chunk += ch;
          }
          line = chunk;
        } else line = cand;
      } else {
        out.push(line.trimEnd());
        line = /^\s+$/.test(w) ? '' : w;
      }
    }
    out.push(line.trimEnd());
  }
  return out;
}

function pixelGlyphs(g, line, font, color, stroke, shadow, letterSpacing) {
  const key = [font, line, color, stroke ? `${stroke.color}/${stroke.width || 1}` : '', shadow ? `${shadow.color}/${shadow.x ?? 1}/${shadow.y ?? 1}` : '', letterSpacing || ''].join('|');
  let hit = PIXEL_CACHE.get(key);
  if (hit) { PIXEL_CACHE.delete(key); PIXEL_CACHE.set(key, hit); return hit; }
  const probe = document.createElement('canvas').getContext('2d');
  probe.font = font;
  if (letterSpacing) probe.letterSpacing = letterSpacing;
  const m = probe.measureText(line);
  const asc = Math.ceil(m.fontBoundingBoxAscent || fontPx(font));
  const desc = Math.ceil(m.fontBoundingBoxDescent || fontPx(font) * 0.25);
  const sw = stroke ? Math.max(1, Math.round(stroke.width || 1)) : 0;
  const sx = shadow ? Math.round(shadow.x ?? 1) : 0, sy = shadow ? Math.round(shadow.y ?? 1) : 0;
  const pad = sw + Math.max(Math.abs(sx), Math.abs(sy)) + 1;
  const w = Math.ceil(m.width) + pad * 2, h = asc + desc + pad * 2;
  const mask = document.createElement('canvas');
  mask.width = w; mask.height = h;
  const mg = mask.getContext('2d', { willReadFrequently: true });
  mg.font = font; mg.textBaseline = 'alphabetic'; mg.fillStyle = '#fff';
  if (letterSpacing) mg.letterSpacing = letterSpacing;
  mg.fillText(line, pad, pad + asc);
  const id = mg.getImageData(0, 0, w, h);
  const a = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) a[i] = id.data[i * 4 + 3] >= 128 ? 1 : 0;
  const out = document.createElement('canvas');
  out.width = w; out.height = h;
  const og = out.getContext('2d');
  const stamp = (col, dx, dy) => {
    const img = og.createImageData(w, h);
    const c = parseColor(col);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const xx = x - dx, yy = y - dy;
        if (xx < 0 || yy < 0 || xx >= w || yy >= h || !a[yy * w + xx]) continue;
        const k = (y * w + x) * 4;
        img.data[k] = c[0]; img.data[k + 1] = c[1]; img.data[k + 2] = c[2]; img.data[k + 3] = 255;
      }
    }
    const tmp = document.createElement('canvas');
    tmp.width = w; tmp.height = h;
    tmp.getContext('2d').putImageData(img, 0, 0);
    og.drawImage(tmp, 0, 0);
  };
  if (shadow) stamp(shadow.color || '#000', sx, sy);
  if (stroke) {
    for (let dy = -sw; dy <= sw; dy++) for (let dx = -sw; dx <= sw; dx++) if (dx || dy) stamp(stroke.color || '#000', dx, dy);
  }
  stamp(color, 0, 0);
  hit = { canvas: out, pad, asc, desc, width: m.width };
  PIXEL_CACHE.set(key, hit);
  if (PIXEL_CACHE.size > PIXEL_CACHE_MAX) PIXEL_CACHE.delete(PIXEL_CACHE.keys().next().value);
  return hit;
}

let colorProbe = null;
/** Parse any CSS colour to [r,g,b,a(0..1)] via a 1x1 canvas (cached per string). */
const COLOR_CACHE = new Map();
export function parseColor(col) {
  const k = String(col);
  if (COLOR_CACHE.has(k)) return COLOR_CACHE.get(k);
  if (!colorProbe) {
    const c = document.createElement('canvas');
    c.width = c.height = 1;
    colorProbe = c.getContext('2d', { willReadFrequently: true });
  }
  colorProbe.clearRect(0, 0, 1, 1);
  colorProbe.fillStyle = '#000';
  colorProbe.fillStyle = k;
  colorProbe.fillRect(0, 0, 1, 1);
  const d = colorProbe.getImageData(0, 0, 1, 1).data;
  const v = [d[0], d[1], d[2], d[3] / 255];
  COLOR_CACHE.set(k, v);
  return v;
}

/**
 * Draw text and register its box. Options: x, y, font, size, weight, style, color, align
 * ('left'|'center'|'right'), baseline ('alphabetic'|'top'|'middle'|'bottom'), maxWidth, lineHeight
 * (multiplier if < 4 else px), maxLines, shadow ({color, blur, x, y} or a colour string), stroke
 * ({color, width}), letterSpacing (px number or CSS length), alpha, pixel (1-bit crisp glyphs), qa (false =
 * decorative, not checked). Returns {x, y, w, h, lines, size}.
 * @param {(box: object) => void} sink receives {rect:[x,y,w,h] surface px, size (surface px), text, overflow}
 */
export function drawText(g, str, o = {}, sink = null) {
  const text = String(str ?? '');
  const font = cssFont(o);
  const size = fontPx(font);
  const ls = o.letterSpacing == null ? '' : (typeof o.letterSpacing === 'number' ? `${o.letterSpacing}px` : String(o.letterSpacing));
  g.save();
  g.font = font;
  g.textAlign = 'left';
  g.textBaseline = 'alphabetic';
  g.letterSpacing = ls || '0px';
  if (o.alpha != null) g.globalAlpha *= o.alpha;
  let lines = wrapLines(g, text, o.maxWidth);
  let truncated = false;
  if (o.maxLines && lines.length > o.maxLines) {
    lines = lines.slice(0, o.maxLines);
    let last = lines[lines.length - 1];
    while (last.length && g.measureText(`${last}…`).width > (o.maxWidth || Infinity)) last = last.slice(0, -1);
    lines[lines.length - 1] = `${last.trimEnd()}…`;
    truncated = true;
  }
  const ms = lines.map((l) => g.measureText(l));
  const asc = ms.length ? Math.max(...ms.map((m) => m.fontBoundingBoxAscent || size * 0.8)) : size * 0.8;
  const desc = ms.length ? Math.max(...ms.map((m) => m.fontBoundingBoxDescent || size * 0.2)) : size * 0.2;
  const lh = o.lineHeight == null ? size * 1.2 : (o.lineHeight < 4 ? o.lineHeight * size : o.lineHeight);
  const blockH = lh * (lines.length - 1) + asc + desc;
  const x = o.x || 0, y = o.y || 0;
  const base = o.baseline || 'alphabetic';
  let y0 = y;
  if (base === 'top' || base === 'hanging') y0 = y + asc;
  else if (base === 'middle') y0 = y - blockH / 2 + asc;
  else if (base === 'bottom' || base === 'ideographic') y0 = y - blockH + asc;
  const align = o.align || 'left';
  const widths = ms.map((m) => m.width);
  const maxW = widths.length ? Math.max(...widths) : 0;
  const color = o.color || '#fff';
  let ink = null;
  const shadow = typeof o.shadow === 'string' ? { color: o.shadow, blur: 8, x: 0, y: 2 } : o.shadow;
  lines.forEach((line, i) => {
    const w = widths[i];
    const lx = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
    const by = y0 + i * lh;
    if (o.pixel) {
      const gl = pixelGlyphs(g, line, font, color, o.stroke, shadow, ls);
      const prev = g.imageSmoothingEnabled;
      g.imageSmoothingEnabled = false;
      g.drawImage(gl.canvas, Math.round(lx - gl.pad), Math.round(by - gl.asc - gl.pad));
      g.imageSmoothingEnabled = prev;
    } else {
      if (shadow) {
        g.shadowColor = shadow.color || 'rgba(0,0,0,.5)';
        g.shadowBlur = shadow.blur ?? 8;
        g.shadowOffsetX = shadow.x ?? 0;
        g.shadowOffsetY = shadow.y ?? 2;
      }
      if (o.stroke && (o.stroke.width || 0) > 0) {
        g.lineJoin = 'round';
        g.lineWidth = o.stroke.width * 2;
        g.strokeStyle = o.stroke.color || '#000';
        g.strokeText(line, lx, by);
        g.shadowColor = 'transparent';
      }
      g.fillStyle = color;
      g.fillText(line, lx, by);
    }
    const m = ms[i];
    const l = lx - (m.actualBoundingBoxLeft || 0), r = lx + (m.actualBoundingBoxRight || w);
    const top = by - (m.actualBoundingBoxAscent || asc), bot = by + (m.actualBoundingBoxDescent || 0);
    if (line.trim()) ink = ink ? [Math.min(ink[0], l), Math.min(ink[1], top), Math.max(ink[2], r), Math.max(ink[3], bot)] : [l, top, r, bot];
  });
  const fontOk = typeof document === 'undefined' || !document.fonts || document.fonts.check(font, text || 'A');
  if (sink && o.qa !== false && ink && g.globalAlpha > 0.05) {
    const M = g.getTransform();
    const pts = [[ink[0], ink[1]], [ink[2], ink[1]], [ink[0], ink[3]], [ink[2], ink[3]]]
      .map(([px, py]) => [M.a * px + M.c * py + M.e, M.b * px + M.d * py + M.f]);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const rect = [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
    const overflow = !!(o.maxWidth && maxW > o.maxWidth + 0.5);
    sink({ rect, size: size * Math.hypot(M.c, M.d), text: text.slice(0, 80), overflow, truncated, fontOk, font });
  }
  g.restore();
  const left = align === 'center' ? x - maxW / 2 : align === 'right' ? x - maxW : x;
  return { x: left, y: y0 - asc, w: maxW, h: blockH, lines, size, lineHeight: lh, ascent: asc };
}

/** Measure without drawing (same wrapping rules as drawText). */
export function measureText(g, str, o = {}) {
  g.save();
  g.font = cssFont(o);
  if (o.letterSpacing != null) g.letterSpacing = typeof o.letterSpacing === 'number' ? `${o.letterSpacing}px` : String(o.letterSpacing);
  const lines = wrapLines(g, String(str ?? ''), o.maxWidth);
  const size = fontPx(g.font);
  const lh = o.lineHeight == null ? size * 1.2 : (o.lineHeight < 4 ? o.lineHeight * size : o.lineHeight);
  const ms = lines.map((l) => g.measureText(l));
  const asc = ms.length ? Math.max(...ms.map((m) => m.fontBoundingBoxAscent || size * 0.8)) : 0;
  const desc = ms.length ? Math.max(...ms.map((m) => m.fontBoundingBoxDescent || size * 0.2)) : 0;
  g.restore();
  return { w: ms.length ? Math.max(...ms.map((m) => m.width)) : 0, h: lh * (lines.length - 1) + asc + desc, lines, size };
}
