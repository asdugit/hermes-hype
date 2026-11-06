// Showreel kit "frames": full-bleed player for pre-rendered frame sequences (Blender shots, see BLENDER.md).
// The Blender pass rewrites every `blender:<kit>/<scene>` shot to `kit:frames/play` with
// params {asset, offset, fps, fit, alpha}. Frame index for shot-local t: floor((t + offset) * fps + 0.5), clamped,
// the same rounding the host uses to pick keyframe-only frames (showreel_core/blender/film.py frames_for_times).

import { sr } from '../../runtime/showreel.js';

/** 0-based frame index for shot-local t (offset = seconds rendered before the shot's t0). */
export function frameFor(t, offset, fps, count) {
  const tt = Number.isFinite(t) ? t : 0;
  const k = Math.floor((tt + offset) * fps + 0.5 + 1e-6);
  return Math.max(0, Math.min(count - 1, k));
}

/** Destination rect for an image of iw x ih in a w x h surface: 'cover' fills (crops), 'contain' letterboxes. */
export function fitRect(iw, ih, w, h, fit) {
  if (!iw || !ih) return [0, 0, w, h];
  const s = fit === 'contain' ? Math.min(w / iw, h / ih) : Math.max(w / iw, h / ih);
  const dw = iw * s, dh = ih * s;
  return [(w - dw) / 2, (h - dh) / 2, dw, dh];
}

sr.defineScene('kit:frames/play', {
  layer: '2d',
  describe: 'Full-bleed player for a pre-rendered frame sequence (Blender shots). Not for direct use by the Director: write blender:<kit>/<scene> shots instead.',
  params: {
    asset: { type: 'asset', default: null, doc: 'frames asset (manifest name)' },
    offset: { type: 'number', default: 0, doc: 'seconds rendered before the shot t0 (transition handle)' },
    fps: { type: 'number', default: 0, doc: 'sequence fps (0 = the asset fps)' },
    fit: { type: 'string', default: 'cover', doc: "'cover' (fill, crop) | 'contain' (letterbox)" },
    alpha: { type: 'boolean', default: false, doc: 'frames carry transparency: do not clear to the background' },
    background: { type: 'string', default: '#000', doc: "colour behind 'contain' letterboxing (ignored with alpha)" },
  },
  render(ctx, t, p) {
    const g = ctx.g;
    if (!p.alpha) {
      g.fillStyle = p.background || '#000';
      g.fillRect(0, 0, ctx.w, ctx.h);
    }
    if (!p.asset) return;
    const a = ctx.asset(p.asset);
    const fps = Number(p.fps) || a.fps || ctx.film.fps;
    const img = a.type === 'frames' ? a.frameAt(frameFor(t, Number(p.offset) || 0, fps, a.count)) : a.image;
    if (!img) return;
    const iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height;
    const [x, y, w, h] = fitRect(iw, ih, ctx.w, ctx.h, p.fit);
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = 'high';
    g.drawImage(img, x, y, w, h);
  },
});
