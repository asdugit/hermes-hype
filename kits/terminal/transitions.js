// Showreel kit "terminal" — transitions. A CRT does not fade, it redraws: `channel-switch` (between acts: the
// picture tears sideways, a static burst, a vertical-hold roll into the next channel) and `persist` (a hard cut
// with a 4-frame phosphor-persistence trail of the previous picture). Both are 'css' transitions so they work on
// DOM shots; static bars are painted on the transition overlay canvas (tx.g).

import { sr } from '../base/scene.js';

const PH = { p3: [255, 177, 59], p1: [75, 255, 134] };

/** Channel switch: u 0..0.5 old picture tears + dims, burst of static at the cut, u 0.5..1 new picture rolls in. */
function channelSwitch(tx, u, p) {
  const r = tx.rng;
  const [cr, cg, cb] = PH[p.phosphor] || PH.p3;
  const first = u < 0.5;
  (first ? tx.toEl : tx.fromEl).style.visibility = 'hidden';
  const el = first ? tx.fromEl : tx.toEl;
  const k = first ? u * 2 : (1 - u) * 2;                 // 0 -> 1 at the cut -> 0
  const tear = (r() - 0.5) * 90 * k * k;
  const roll = first ? 0 : -((1 - (u - 0.5) * 2) ** 2) * tx.h * 0.18;
  el.style.transform = `translate(${tear.toFixed(1)}px, ${roll.toFixed(1)}px) skewX(${((r() - 0.5) * 8 * k).toFixed(2)}deg) scaleY(${(1 - 0.06 * k).toFixed(3)})`;
  el.style.filter = `brightness(${(1 + 1.4 * k * k - (Math.abs(u - 0.5) < 0.08 ? 0.9 : 0)).toFixed(3)}) contrast(${(1 + 0.5 * k).toFixed(2)})`;
  const { g, w, h } = tx;
  // static: phosphor-coloured noise bands, densest at the cut
  const bands = Math.round(4 + 26 * k * k);
  for (let i = 0; i < bands; i++) {
    const y = r() * h, bh = 2 + r() * (6 + 30 * k);
    g.globalAlpha = (0.08 + 0.5 * r()) * k;
    g.fillStyle = r() < 0.3 ? '#fff' : `rgb(${cr},${cg},${cb})`;
    g.fillRect(0, y, w, bh);
  }
  if (Math.abs(u - 0.5) < 0.1) {               // the dead frame between channels
    g.globalAlpha = 0.85;
    g.fillStyle = '#000';
    g.fillRect(0, 0, w, h);
    for (let i = 0; i < 900; i++) {
      g.globalAlpha = 0.35 + 0.5 * r();
      g.fillStyle = r() < 0.5 ? `rgb(${cr},${cg},${cb})` : '#000';
      g.fillRect(r() * w, r() * h, 2 + r() * 10, 2 + r() * 3);
    }
  }
}

/** Phosphor persistence: hard cut at the midpoint; the old picture decays on top (screen blend, 35 % -> 0). */
function persist(tx, u) {
  if (u < 0.5) { tx.toEl.style.visibility = 'hidden'; return; }
  const a = 0.35 * (1 - (u - 0.5) * 2);
  tx.fromEl.style.zIndex = String(Number(tx.toEl.style.zIndex || 0) + 1);
  tx.fromEl.style.opacity = a.toFixed(3);
  tx.fromEl.style.mixBlendMode = 'screen';
}

if (sr && typeof sr.defineTransition === 'function') {
  sr.defineTransition('kit:terminal/channel-switch', { kind: 'css', render: channelSwitch });
  sr.defineTransition('kit:terminal/persist', { kind: 'css', render: persist });
}

export const TRANSITIONS = ['kit:terminal/channel-switch', 'kit:terminal/persist'];
