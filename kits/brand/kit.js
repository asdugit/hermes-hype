// Auteur kit "brand": customization overlays (showreel_core/customize). `kit:brand/logo` is the user's logo as
// a corner bug above every shot (the `logo=` knob), drawn with smoothing, eased in over the first half second.

import { sr } from '../../runtime/showreel.js';

/** Corner rect for a logo of iw x ih: height `size` px at a 1080 short side, inside the safe area. */
export function cornerRect(iw, ih, w, h, safe, corner, size) {
  const k = Math.min(w, h) / 1080;
  const hh = Math.max(8, size * k);
  const ww = iw && ih ? hh * (iw / ih) : hh;
  const maxW = w * 0.28;
  const s = ww > maxW ? maxW / ww : 1;
  const dw = ww * s, dh = hh * s;
  const m = { l: Math.max(safe.l, 24 * k), r: Math.max(safe.r, 24 * k), t: Math.max(safe.t, 24 * k), b: Math.max(safe.b, 24 * k) };
  const x = corner.endsWith('left') ? m.l : w - m.r - dw;
  const y = corner.startsWith('bottom') ? h - m.b - dh : m.t;
  return [x, y, dw, dh];
}

sr.defineScene('kit:brand/logo', {
  layer: '2d',
  describe: 'The user\'s logo as a small corner bug above the film (customization overlay; params asset, corner, size, opacity).',
  params: {
    asset: { type: 'asset', default: null, doc: 'logo image asset' },
    corner: { type: 'string', default: 'top-right', doc: 'top-right | top-left | bottom-right | bottom-left' },
    size: { type: 'number', default: 84, doc: 'logo height in px at a 1080 short side' },
    opacity: { type: 'number', default: 0.92, doc: '0..1' },
  },
  render(ctx, t, p) {
    const g = ctx.g;
    g.clearRect(0, 0, ctx.w, ctx.h);
    if (!p.asset) return;
    const a = ctx.asset(p.asset);
    const img = a && a.image;
    if (!img) return;
    const iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height;
    const [x, y, w, h] = cornerRect(iw, ih, ctx.w, ctx.h, ctx.safe, String(p.corner || 'top-right'), Number(p.size) || 84);
    const fade = ctx.seg(t, 0, 0.5, ctx.ease.outCubic);
    const out = 1 - ctx.seg(t, ctx.dur - 0.35, ctx.dur, ctx.ease.inCubic);
    g.save();
    g.globalAlpha = Math.max(0, Math.min(1, Number(p.opacity ?? 0.92))) * fade * out;
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = 'high';
    g.drawImage(img, x, y, w, h);
    g.restore();
  },
});
