// Hype kit "blueprint" — product captures on the sheet: a screenshot is first traced as white line art (edge
// detection, revealed by the pen), then "develops" inside its outline like a cyanotype exposure (blue print ->
// the real colours). Plates are painted once in setup; render only moves clip edges and opacities.

import { h, css } from '../base/dom.js';
import { mediaOf } from '../base/media.js';
import { seg, ease, clamp } from '../base/motion.js';

/** Edge (Sobel) + cyanotype + real plates for an image param shown at w x h reference px. o: {crop:[x,y,w,h] fractions}. */
export function mediaPlates(ctx, F, img, w, h0, o = {}) {
  const doc = F.el.ownerDocument;
  const m = mediaOf(ctx, img);
  const k = F.k, W = Math.max(1, Math.round(w * k)), H = Math.max(1, Math.round(h0 * k));
  const crop = o.crop || [0, 0, 1, 1];
  const src = [crop[0] * m.w, crop[1] * m.h, crop[2] * m.w, crop[3] * m.h];
  const el = h('div', 'bp-media');
  el.style.cssText = `width:${Math.round(w)}px;height:${Math.round(h0)}px;`;
  const mk = () => { const c = doc.createElement('canvas'); c.width = W; c.height = H; c.style.cssText = `width:${Math.round(w)}px;height:${Math.round(h0)}px;`; el.appendChild(c); return c; };
  const cCy = mk(), cReal = mk(), cEdge = mk();
  if (m.image) {
    const gR = cReal.getContext('2d');
    gR.imageSmoothingQuality = 'high';
    gR.drawImage(m.image, src[0], src[1], src[2], src[3], 0, 0, W, H);
    // analysis grid (<= 640 px wide)
    const aw = Math.min(640, W), ah = Math.max(2, Math.round(aw * H / W));
    const a = doc.createElement('canvas'); a.width = aw; a.height = ah;
    const ga = a.getContext('2d', { willReadFrequently: true });
    ga.drawImage(m.image, src[0], src[1], src[2], src[3], 0, 0, aw, ah);
    let data = null;
    try { data = ga.getImageData(0, 0, aw, ah).data; } catch (e) { data = null; }
    if (data) {
      const lum = new Float32Array(aw * ah);
      for (let i = 0; i < aw * ah; i++) lum[i] = (0.2126 * data[i * 4] + 0.7152 * data[i * 4 + 1] + 0.0722 * data[i * 4 + 2]) / 255;
      // cyanotype: luminance -> Prussian blue .. paper white
      const cy = ga.createImageData(aw, ah), ed = ga.createImageData(aw, ah);
      for (let i = 0; i < aw * ah; i++) {
        const v = Math.pow(lum[i], 1.1);
        cy.data[i * 4] = 8 + v * 222; cy.data[i * 4 + 1] = 42 + v * 204; cy.data[i * 4 + 2] = 76 + v * 179; cy.data[i * 4 + 3] = 255;
      }
      for (let y = 1; y < ah - 1; y++) for (let x = 1; x < aw - 1; x++) {
        const i = y * aw + x;
        const gx = -lum[i - aw - 1] - 2 * lum[i - 1] - lum[i + aw - 1] + lum[i - aw + 1] + 2 * lum[i + 1] + lum[i + aw + 1];
        const gy = -lum[i - aw - 1] - 2 * lum[i - aw] - lum[i - aw + 1] + lum[i + aw - 1] + 2 * lum[i + aw] + lum[i + aw + 1];
        const g = Math.min(1, Math.hypot(gx, gy) * 2.2);
        const al = g < 0.12 ? 0 : Math.min(1, (g - 0.12) * 1.6);
        ed.data[i * 4] = 238; ed.data[i * 4 + 1] = 246; ed.data[i * 4 + 2] = 255; ed.data[i * 4 + 3] = Math.round(al * 255);
      }
      const tmp = doc.createElement('canvas'); tmp.width = aw; tmp.height = ah;
      const gt = tmp.getContext('2d');
      gt.putImageData(cy, 0, 0);
      const gC = cCy.getContext('2d'); gC.imageSmoothingQuality = 'high'; gC.drawImage(tmp, 0, 0, W, H);
      gt.clearRect(0, 0, aw, ah); gt.putImageData(ed, 0, 0);
      const gE = cEdge.getContext('2d'); gE.imageSmoothingQuality = 'high'; gE.drawImage(tmp, 0, 0, W, H);
    }
  }
  /** st = {trace: [t0, t1] (left->right reveal of the line art), develop: [t0, t1] (blue print -> colour)}. */
  function update(t, st) {
    const ut = seg(t, st.trace[0], st.trace[1]);
    const ud = seg(t, st.develop[0], st.develop[1], ease.inOutQuad);
    const uc = seg(t, st.develop[0] - 0.15, st.develop[0] + 0.25, ease.outQuad);
    css(cEdge, { visibility: ut > 0 ? 'visible' : 'hidden', clipPath: ut >= 1 ? 'none' : `inset(0 ${((1 - ut) * 100).toFixed(2)}% 0 0)`,
      opacity: (1 - 0.75 * ud).toFixed(3) });
    css(cCy, { visibility: uc > 0 ? 'visible' : 'hidden', opacity: uc.toFixed(3) });
    css(cReal, { visibility: ud > 0 ? 'visible' : 'hidden', opacity: ud.toFixed(3) });
    return ut;
  }
  return { el, w, h: h0, update, media: m };
}

export { clamp };
