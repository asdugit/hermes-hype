// cinematic kit · type on the 2D overlay (display-referred, composited over the graded plate).
// Cormorant Garamond titles (caps, wide tracking), Cormorant italic captions/taglines, Geist caps labels,
// Geist Mono CTA, register tag and the session-clock rail in the bottom letterbox bar. All alpha/rise from t.
import { clamp, outCubic, lerp } from './world.js';
import { SERIF, SANS, MONO, wrap } from './cards.js';

export const INK = { paper: '#EEE7DA', mist: '#A9ADB5', ash: '#6C717B', accent: '#FFB04C', accentHi: '#FFD9A0' };

const ramp = (t, t0, d = 0.6) => outCubic((t - t0) / d);

/** Letter-staggered title (caps, tracking .34em). Returns the drawn block height. */
export function title(g, F, text, t, o = {}) {
  const s = F.scale, size = (o.size ?? (F.portrait ? 96 : 132)) * s * (o.k ?? 1);
  const str = String(text || '').toUpperCase();
  g.save();
  const maxW = F.w - 2 * 110 * s;
  const setF = (z) => { g.font = `500 ${z}px ${SERIF}`; g.letterSpacing = `${(0.34 * z).toFixed(1)}px`; };
  const fitTo = (line, floor) => { let z = size; setF(z); while (g.measureText(line).width > maxW && z > floor) { z *= 0.92; setF(z); } return z; };
  let lines = [str], fs = fitTo(str, 40 * s);
  setF(fs);
  if (g.measureText(str).width > maxW) {
    // still wider than the frame at the 40 px floor (a 40-character name on 9:16 ran off both edges): two
    // balanced lines at a word boundary, the last one on the usual baseline; no space (CJK) -> just smaller
    lines = twoLines(str);
    fs = Math.min(...lines.map((l) => fitTo(l, 24)));        // px, not x scale (scale = H/1080 is 1.78 on 9:16)
  }
  const y0 = o.y ?? F.h / 2;
  g.textBaseline = 'alphabetic'; g.shadowColor = 'rgba(255,236,210,0.22)'; g.shadowBlur = 28 * s;
  let i = 0;
  lines.forEach((line, li) => {
    setF(fs);
    const total = g.measureText(line).width;
    let x = F.w / 2 - total / 2 + 0.17 * fs;
    const y = y0 - (lines.length - 1 - li) * fs * 1.12;
    for (const ch of [...line]) {
      const u = ramp(t, (o.t0 ?? 0.3) + i * 0.035, 0.7);
      g.globalAlpha = u * (o.alpha ?? 1); g.fillStyle = INK.paper;
      g.letterSpacing = '0px';
      g.fillText(ch, x, y + (1 - u) * 16 * s);
      x += g.measureText(ch).width + 0.34 * fs;
      i += 1;
    }
  });
  g.restore();
  return fs;
}

/** Split at the space that balances the two halves best ([s] when there is no space). */
function twoLines(s) {
  const ws = String(s).split(/\s+/).filter(Boolean);
  if (ws.length < 2) return [String(s)];
  let best = 1, bd = 1e9;
  for (let k = 1; k < ws.length; k++) {
    const d = Math.abs(ws.slice(0, k).join(' ').length - ws.slice(k).join(' ').length);
    if (d < bd) { bd = d; best = k; }
  }
  return [ws.slice(0, best).join(' '), ws.slice(best).join(' ')];
}

/** Italic serif line(s), centred or left. */
export function italic(g, F, text, t, o = {}) {
  const s = F.scale, size = (o.size ?? (F.portrait ? 64 : 52)) * s;
  g.save(); g.font = `italic 500 ${size}px ${SERIF}`; g.fillStyle = o.color || INK.paper;
  const lines = wrap(g, text, o.maxW ?? (F.w * (F.portrait ? 0.8 : 0.62)));
  const lh = size * 1.18, u = ramp(t, o.t0 ?? 0.6, 0.8);
  g.globalAlpha = u * (o.alpha ?? 0.9); g.textAlign = o.align || 'center';
  const x = o.x ?? F.w / 2;
  let y = (o.y ?? F.h * 0.6) + (1 - u) * 12 * s;
  if (o.anchor === 'bottom') y -= (lines.length - 1) * lh;
  for (const l of lines) { g.fillText(l, x, y); y += lh; }
  g.restore();
  return lines.length * lh;
}

/** Small caps label (Geist, tracking .26em). */
export function label(g, F, text, t, o = {}) {
  const s = F.scale, size = (o.size ?? (F.portrait ? 19 : 17)) * s;
  g.save(); g.font = `500 ${size}px ${SANS}`; g.letterSpacing = `${(0.26 * size).toFixed(1)}px`;
  g.fillStyle = o.color || INK.mist; g.globalAlpha = ramp(t, o.t0 ?? 0.2, 0.6) * (o.alpha ?? 1); g.textAlign = o.align || 'center';
  g.fillText(String(text || '').toUpperCase(), o.x ?? F.w / 2, o.y ?? F.h * 0.4);
  g.restore();
}

/** ● CAPTURED · session register tag (honesty marker). */
export function register(g, F, t, o = {}) {
  const s = F.scale, x = o.x ?? 120 * s, y = o.y ?? F.barH + 52 * s;
  g.save(); g.globalAlpha = ramp(t, o.t0 ?? 0.4, 0.5);
  g.beginPath(); g.arc(x, y - 6 * s, 5 * s, 0, Math.PI * 2); g.fillStyle = INK.accent; g.fill();
  g.font = `500 ${15 * s}px ${SANS}`; g.letterSpacing = `${(0.26 * 15 * s).toFixed(1)}px`; g.fillStyle = INK.mist;
  g.fillText(o.text || 'CAPTURED · SESSION', x + 16 * s, y);
  g.restore();
}

/** Session-clock rail in the bottom bar: START → SHIP, ticks, amber spark at `progress` (0..1). */
export function rail(g, F, progress, ticks = [], o = {}) {
  if (!F.barH && !F.portrait) return;
  const s = F.scale, y = F.portrait ? F.h - 300 * s : F.h - F.barH / 2 + 4 * s;
  const x0 = 120 * s + 178 * s, x1 = F.w - 120 * s - 76 * s;
  g.save();
  g.font = `500 ${13 * s}px ${SANS}`; g.letterSpacing = `${(0.28 * 13 * s).toFixed(1)}px`; g.fillStyle = INK.ash;
  g.fillText('SESSION START', 120 * s, y + 4 * s); g.textAlign = 'right'; g.fillText('SHIP', F.w - 120 * s, y + 4 * s); g.textAlign = 'left';
  g.fillStyle = 'rgba(108,113,123,0.55)'; g.fillRect(x0, y, x1 - x0, 1);
  const px = lerp(x0, x1, clamp(progress));
  const gr = g.createLinearGradient(x0, 0, px, 0); gr.addColorStop(0, 'rgba(255,176,76,0)'); gr.addColorStop(1, 'rgba(255,176,76,0.75)');
  g.fillStyle = gr; g.fillRect(x0, y - 0.5, px - x0, 2);
  for (const tk of ticks) { const tx = lerp(x0, x1, tk); g.fillStyle = tk <= progress ? 'rgba(255,176,76,0.8)' : 'rgba(169,173,181,0.5)'; g.fillRect(tx, y - 5 * s, 1, 10 * s); }
  const rg = g.createRadialGradient(px, y, 0, px, y, 14 * s); rg.addColorStop(0, '#FFE9C8'); rg.addColorStop(0.3, 'rgba(255,176,76,0.9)'); rg.addColorStop(1, 'rgba(255,176,76,0)');
  g.fillStyle = rg; g.beginPath(); g.arc(px, y, 14 * s, 0, Math.PI * 2); g.fill();
  if (o.label) { g.font = `500 ${13 * s}px ${SANS}`; g.fillStyle = INK.mist; g.textAlign = 'center'; g.fillText(String(o.label).toUpperCase(), px, y - 16 * s); }
  g.restore();
}

/** Big number + caps label pairs (STATS). */
export function stats(g, F, items, t, o = {}) {
  const s = F.scale, n = Math.min(items.length, 4);
  if (!n) return;
  const size = (F.portrait ? 170 : n > 2 ? 170 : 220) * s;
  g.save();
  items.slice(0, n).forEach((it, i) => {
    const u = ramp(t, 0.35 + i * 0.45, 1.1);
    const cx = F.portrait ? F.w / 2 : F.w * (i + 0.5) / n;
    const cy = F.portrait ? F.h * (0.3 + i * 0.18) : F.h * 0.52;
    g.globalAlpha = u; g.textAlign = 'center';
    g.font = `500 ${size}px ${SERIF}`; g.fillStyle = INK.paper; g.shadowColor = 'rgba(255,236,210,0.18)'; g.shadowBlur = 30 * s;
    g.fillText(String(it.display ?? it.value ?? ''), cx, cy);
    g.shadowBlur = 0; g.font = `500 ${17 * s}px ${SANS}`; g.letterSpacing = `${(0.26 * 17 * s).toFixed(1)}px`; g.fillStyle = INK.mist;
    g.fillText(String(it.label || it.key || '').toUpperCase(), cx, cy + 56 * s); g.letterSpacing = '0px';
  });
  g.restore();
}

/** CTA in Geist Mono inside a hairline pill. */
export function cta(g, F, text, t, o = {}) {
  const s = F.scale;
  let size = 30 * s;
  g.save(); g.font = `400 ${size}px ${MONO}`;
  // a long command shrinks (to 20 px) to stay inside the frame (9:16 cut a 40-character command on both sides)
  const room = F.w - 2 * 80 * s - 64 * s, w0 = g.measureText(text).width;
  if (w0 > room) { size = Math.max(20, size * room / w0); g.font = `400 ${size}px ${MONO}`; }   // px (scale = H/1080)
  const tw = g.measureText(text).width, pw = tw + 64 * s, ph = 64 * s, x = F.w / 2 - pw / 2, y = o.y ?? F.h * 0.62;
  g.globalAlpha = ramp(t, o.t0 ?? 1.0, 0.7);
  g.strokeStyle = 'rgba(255,176,76,0.7)'; g.lineWidth = 1.5 * s;
  g.beginPath(); g.roundRect(x, y - ph / 2, pw, ph, ph / 2); g.stroke();
  g.fillStyle = INK.accentHi; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, F.w / 2, y + 1);
  g.restore();
}
