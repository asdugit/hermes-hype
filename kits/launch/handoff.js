// Hype kit "launch" — headline -> hero handoff timing and camera blending (pure: no DOM, testable under Node).

import { clamp, seg, ease } from '../base/motion.js';

/**
 * Headline -> hero handoff (landscape): the headline reads big beside the product first, then the product swells to
 * fill the frame while the headline settles small in the top-left corner. Returns {t0, u(t)} (u: 0 -> 1).
 * `early` = short opening shots (HOOK). Portrait frames keep the band layout and very short shots keep their
 * layout (t0 = Infinity, u stays 0).
 */
export function handoff(F, dur, early = false) {
  if (F.portrait || !(dur >= 2.0)) return { t0: Infinity, u: () => 0 };
  const t0 = early ? clamp(dur * 0.4, 0.7, 1.1) : clamp(dur * 0.3, 1.1, 1.9);
  return { t0, u: (t) => seg(t, t0, t0 + 0.85, ease.inOutCubic) };
}

/** Blend two camera states (log-distance, linear angles and lens shift); u <= 0 -> a, u >= 1 -> b. */
export function blendCam(a, b, u) {
  if (!b || !(u > 0)) return a;
  if (u >= 1) return b;
  const L = (x, y) => (x || 0) + ((y || 0) - (x || 0)) * u;
  const out = { ...a, target: [L(a.target[0], b.target[0]), L(a.target[1], b.target[1]), L(a.target[2], b.target[2])],
    dist: Math.exp(L(Math.log(a.dist), Math.log(b.dist))), yaw: L(a.yaw, b.yaw), pitch: L(a.pitch, b.pitch), roll: L(a.roll, b.roll) };
  if (a.shift || b.shift) {
    const sa = a.shift || [0, 0], sb = b.shift || [0, 0];
    out.shift = [L(sa[0], sb[0]), L(sa[1], sb[1])];
  }
  return out;
}

/** FEATURE copy: the storyboard label (benefit line) is the headline, the short feature name its eyebrow. */
export function featureCopy(feature, label) {
  const feat = String(feature || '').trim(), lab = String(label || '').trim();
  const head = lab || feat;
  const eyebrow = lab && feat && lab.toLowerCase() !== feat.toLowerCase() && feat.length <= 32 ? feat : 'Feature';
  return { head, eyebrow };
}
