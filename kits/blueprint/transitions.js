// Hype kit "blueprint" — transitions. Drawings never crossfade: `sheet-slide` (the next sheet slides in over the
// old one with a hairline edge shadow; the old sheet shifts a little and dims) and `plot-wipe` (a vertical pen line
// sweeps across, revealing the next sheet behind it). Both are 'css' transitions (DOM shots); lines on tx.g.

import { sr } from '../base/scene.js';

function sheetSlide(tx, u) {
  const e = tx.ease.inOutCubic(u);
  tx.toEl.style.zIndex = String(Number(tx.fromEl.style.zIndex || 0) + 1);
  tx.toEl.style.transform = `translate(${((1 - e) * 100).toFixed(3)}%, 0)`;
  tx.toEl.style.boxShadow = '-18px 0 40px rgba(2,14,30,.45), -1px 0 0 rgba(238,246,255,.6)';
  tx.fromEl.style.transform = `translate(${(-e * 12).toFixed(3)}%, 0)`;
  tx.fromEl.style.filter = `brightness(${(1 - 0.35 * e).toFixed(3)})`;
}

function plotWipe(tx, u) {
  const e = tx.ease.inOutQuad(u);
  const x = e * tx.w;
  tx.toEl.style.zIndex = String(Number(tx.fromEl.style.zIndex || 0) + 1);
  tx.toEl.style.clipPath = `inset(0 ${(100 - e * 100).toFixed(3)}% 0 0)`;
  const g = tx.g;
  g.strokeStyle = 'rgba(121,211,255,.9)';
  g.lineWidth = Math.max(1, tx.w / 1920 * 1.6);
  g.beginPath(); g.moveTo(x, 0); g.lineTo(x, tx.h); g.stroke();
  // pen head riding the wipe
  const y = tx.h * (0.5 + 0.3 * Math.sin(u * 7));
  const k = tx.w / 1920;
  g.fillStyle = 'rgba(238,246,255,.12)';
  g.beginPath(); g.arc(x, y, 22 * k, 0, Math.PI * 2); g.fill();
  g.strokeStyle = 'rgba(238,246,255,.95)'; g.lineWidth = 1.4 * k;
  g.beginPath(); g.arc(x, y, 9 * k, 0, Math.PI * 2); g.stroke();
  g.beginPath(); g.moveTo(x - 18 * k, y); g.lineTo(x + 18 * k, y); g.moveTo(x, y - 18 * k); g.lineTo(x, y + 18 * k); g.stroke();
}

if (sr && typeof sr.defineTransition === 'function') {
  sr.defineTransition('kit:blueprint/sheet-slide', { kind: 'css', render: sheetSlide });
  sr.defineTransition('kit:blueprint/plot-wipe', { kind: 'css', render: plotWipe });
}

export const TRANSITIONS = ['kit:blueprint/sheet-slide', 'kit:blueprint/plot-wipe'];
