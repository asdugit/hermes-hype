// cinematic kit · lockup: the end title over the picture (2D overlay, transparent). Product name in wide-tracked
// Cormorant caps that rises letter by letter and catches a light sweep, a hairline that grows from the centre, an
// italic tagline, and a CTA pill. A soft scrim keeps the type legible over bright skies. Pure function of t; every
// line goes through ctx.text so layout QA sees it.

const SERIF = 'Cormorant Garamond';
const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
const outCubic = (u) => 1 - Math.pow(1 - clamp(u), 3);
const ramp = (t, t0, d) => outCubic((t - t0) / d);

export const LOCKUP_PARAMS = {
  title: { type: 'string', default: '', doc: 'product name (caps, <= 14 chars reads best)' },
  tagline: { type: 'string', default: '', doc: 'one italic line (<= 8 words)' },
  cta: { type: 'string', default: '', doc: 'call to action in the pill (<= 4 words), e.g. "Make it yours"' },
  eyebrow: { type: 'string', default: '', doc: 'small caps line above the title (optional)' },
  at: { type: 'enum', values: ['upper', 'center', 'lower'], default: 'upper', doc: 'vertical band for the block (upper = above a product-hero)' },
  accent: { type: 'string', default: '#E8384A', doc: 'accent colour (hairline, CTA arrow) — use the product colour' },
  scrim: { type: 'number', default: 0.5, doc: 'soft plum scrim behind the type (0 = none)' },
  hold: { type: 'bool', default: true, doc: 'stay to the end of the overlay (false = fade out over the last 0.4 s)' },
  cta_at: { type: 'enum', values: ['stack', 'bottom'], default: 'stack', doc: 'CTA under the tagline (stack) or in the bottom band (bottom: product sits between title and CTA)' },
};

/**
 * Draw the lockup at overlay time t. ctx: SDK 2D ctx (ctx.g, ctx.text, ctx.w, ctx.h, ctx.safe, ctx.dur).
 */
export function drawLockup(ctx, t, p) {
  const g = ctx.g, W = ctx.w, H = ctx.h, V = H > W, s = Math.min(W, H) / 1080, dur = ctx.dur;
  const out = p.hold === false ? 1 - clamp((t - (dur - 0.4)) / 0.4) : 1;
  const cx = W / 2;
  const cy = p.at === 'center' ? H * 0.5 : p.at === 'lower' ? H * 0.7 : V ? H * 0.22 : H * 0.2;
  g.clearRect(0, 0, W, H);
  // scrim: soft radial plum glow behind the block (darkens a bright sky just enough)
  if (p.scrim > 0) {
    const a = p.scrim * ramp(t, 0, 0.8) * out, rx = (V ? 0.62 : 0.42) * W, ry = (V ? 0.16 : 0.24) * H;
    g.save(); g.translate(cx, cy); g.scale(1, ry / rx);
    const gr = g.createRadialGradient(0, 0, 0, 0, 0, rx);
    gr.addColorStop(0, `rgba(58, 28, 70, ${a.toFixed(3)})`); gr.addColorStop(0.55, `rgba(58, 28, 70, ${(a * 0.55).toFixed(3)})`); gr.addColorStop(1, 'rgba(58, 28, 70, 0)');
    g.fillStyle = gr; g.fillRect(-rx, -rx, rx * 2, rx * 2); g.restore();
  }
  const title = String(p.title || '').toUpperCase();
  let size = (V ? 156 : 210) * s;
  const track = 0.32;
  g.save(); g.font = `600 ${size}px "${SERIF}"`;
  const widthOf = (sz) => { g.font = `600 ${sz}px "${SERIF}"`; g.letterSpacing = `${(track * sz).toFixed(1)}px`; return g.measureText(title).width; };
  const maxW = W - (ctx.safe ? ctx.safe.l + ctx.safe.r : 200 * s) - 40 * s;
  while (title && widthOf(size) > maxW && size > 60 * s) size *= 0.94;
  g.restore();
  let y = cy;
  // eyebrow
  if (p.eyebrow) {
    const a = ramp(t, 0.1, 0.6) * out;
    ctx.text(g, String(p.eyebrow).toUpperCase(), { x: cx, y: y - size * 0.95, font: SERIF, size: 34 * s, weight: 600, color: '#FFF4EC', align: 'center', baseline: 'middle',
      letterSpacing: 12 * s, alpha: a, shadow: { color: 'rgba(60,20,60,0.55)', blur: 14 * s, x: 0, y: 2 * s } });
  }
  // title: letters rise + fade in, staggered; a light sweep passes across at ~1.3 s
  if (title) {
    const total = widthOf(size);
    g.save(); g.font = `600 ${size}px "${SERIF}"`; g.letterSpacing = '0px';
    let x = cx - total / 2 + (track * size) / 2;
    const sweep = clamp((t - 1.2) / 0.9);
    [...title].forEach((ch, i) => {
      const u = ramp(t, 0.15 + i * 0.06, 0.8), w = g.measureText(ch).width;
      const rel = (x + w / 2 - (cx - total / 2)) / Math.max(total, 1);
      const shine = sweep > 0 && sweep < 1 ? Math.exp(-Math.pow((rel - sweep * 1.3 + 0.15) / 0.08, 2)) : 0;
      const col = shine > 0.02 ? mixHex('#FFF6EE', '#FFFFFF', shine) : '#FFF6EE';
      ctx.text(g, ch, { x, y: y + (1 - u) * 26 * s, font: SERIF, size, weight: 600, color: col, align: 'left', baseline: 'middle', alpha: u * out,
        shadow: { color: `rgba(90, 30, 70, ${(0.55 - 0.2 * shine).toFixed(2)})`, blur: (22 + 30 * shine) * s, x: 0, y: 3 * s }, qa: ch.trim() ? undefined : false });
      x += w + track * size;
    });
    g.restore();
  }
  y += size * 0.62;
  // hairline in the accent colour, growing from the centre
  const hl = ramp(t, 0.9, 0.7) * (V ? 0.5 : 0.26) * W;
  if (hl > 1) { g.save(); g.globalAlpha = 0.9 * out; g.fillStyle = p.accent || '#E8384A'; g.fillRect(cx - hl / 2, y, hl, Math.max(2, 3 * s)); g.restore(); }
  y += 58 * s;
  if (p.tagline) {
    const a = ramp(t, 1.15, 0.8) * out;
    ctx.text(g, String(p.tagline), { x: cx, y: y + (1 - a) * 14 * s, font: SERIF, style: 'italic', size: (V ? 66 : 62) * s, weight: 500, color: '#FFF1EA', align: 'center',
      baseline: 'middle', alpha: a, maxWidth: maxW, shadow: { color: 'rgba(70,25,70,0.6)', blur: 18 * s, x: 0, y: 2 * s } });
    y += 92 * s;
  }
  if (p.cta) {
    if (p.cta_at === 'bottom') y = H - (ctx.safe ? ctx.safe.b : 120 * s) - (V ? 160 : 110) * s;
    const a = ramp(t, 1.7, 0.7) * out, label = `${String(p.cta).toUpperCase()}`;
    g.save(); g.font = `700 ${46 * s}px "${SERIF}"`; g.letterSpacing = `${(9 * s).toFixed(1)}px`;
    const tw = g.measureText(label).width, pw = tw + 170 * s, ph = 96 * s, px = cx - pw / 2, py = y + (1 - a) * 18 * s;
    g.globalAlpha = a;
    g.fillStyle = 'rgba(70, 28, 64, 0.42)'; g.strokeStyle = 'rgba(255, 248, 244, 0.95)'; g.lineWidth = 3 * s;
    rounded(g, px, py, pw, ph, ph / 2); g.fill(); g.stroke();
    g.restore();
    ctx.text(g, label, { x: cx - 24 * s, y: py + ph / 2 + 2 * s, font: SERIF, size: 46 * s, weight: 700, color: '#FFFFFF', align: 'center', baseline: 'middle',
      letterSpacing: 9 * s, alpha: a, shadow: { color: 'rgba(60,20,60,0.5)', blur: 10 * s, x: 0, y: 1 * s } });
    // arrow in the accent colour
    g.save(); g.globalAlpha = a; g.strokeStyle = p.accent || '#E8384A'; g.lineWidth = 4 * s; g.lineCap = 'round'; g.lineJoin = 'round';
    const ax = cx + tw / 2 + 12 * s + Math.sin(Math.max(0, t - 2.4) * 3.2) * 4 * s, ay = py + ph / 2;
    g.beginPath(); g.moveTo(ax, ay); g.lineTo(ax + 34 * s, ay); g.moveTo(ax + 22 * s, ay - 11 * s); g.lineTo(ax + 34 * s, ay); g.lineTo(ax + 22 * s, ay + 11 * s); g.stroke();
    g.restore();
  }
}

function rounded(g, x, y, w, h, r) {
  g.beginPath(); g.moveTo(x + r, y); g.lineTo(x + w - r, y); g.arc(x + w - r, y + r, r, -Math.PI / 2, Math.PI / 2); g.lineTo(x + r, y + h);
  g.arc(x + r, y + r, r, Math.PI / 2, Math.PI * 1.5); g.closePath();
}

function mixHex(a, b, u) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * clamp(u))).join(',')})`;
}
