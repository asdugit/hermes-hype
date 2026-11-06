// Layout QA for one frame (SDK §6 __sr.qa(t)): small, clipped, unsafe and overlapping text + scene errors.
// Canvas text comes from ctx.text registrations; DOM text (dom shots, DOM overlays, captions) is measured.

/** Visible text boxes under a DOM root, in film px. stage = {el, scale}. */
export function domTextBoxes(root, stage, owner) {
  const out = [];
  if (!root || !root.isConnected) return out;
  const sr = stage.el.getBoundingClientRect();
  const sc = stage.scale || 1;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  const opacityCache = new Map();
  const effOpacity = (el) => {
    if (!el || el === stage.el) return 1;
    if (opacityCache.has(el)) return opacityCache.get(el);
    const cs = getComputedStyle(el);
    const v = (cs.visibility === 'hidden' || cs.display === 'none' ? 0 : Number(cs.opacity)) * effOpacity(el.parentElement);
    opacityCache.set(el, v);
    return v;
  };
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.nodeValue || !n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (!el || effOpacity(el) < 0.05) continue;
    if (el.closest('[data-qa="off"]')) continue;     // decorative text opted out of layout QA
    range.selectNodeContents(n);
    const rects = [...range.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
    if (!rects.length) continue;
    const l = Math.min(...rects.map((r) => r.left)), t = Math.min(...rects.map((r) => r.top));
    const r = Math.max(...rects.map((q) => q.right)), b = Math.max(...rects.map((q) => q.bottom));
    const cs = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    const scaleY = el.offsetHeight > 0 ? box.height / el.offsetHeight : sc;
    const size = (parseFloat(cs.fontSize) || 16) * scaleY / sc;
    let clipped = false;
    for (let a = el; a && a !== root.parentElement; a = a.parentElement) {
      const acs = getComputedStyle(a);
      if (acs.overflow !== 'visible' || acs.overflowX !== 'visible' || acs.overflowY !== 'visible') {
        const ar = a.getBoundingClientRect();
        if (l < ar.left - 2 || t < ar.top - 2 || r > ar.right + 2 || b > ar.bottom + 2) clipped = true;
        break;
      }
    }
    let block = el;
    while (block && block !== root && /^inline/.test(getComputedStyle(block).display)) block = block.parentElement;
    out.push({
      rect: [(l - sr.left) / sc, (t - sr.top) / sc, (r - l) / sc, (b - t) / sc],
      size, text: n.nodeValue.trim().slice(0, 80), overflow: clipped, owner, el, block,
    });
  }
  return out;
}

const area = (r) => Math.max(0, r[2]) * Math.max(0, r[3]);
function inter(a, b) {
  const x0 = Math.max(a[0], b[0]), y0 = Math.max(a[1], b[1]);
  const x1 = Math.min(a[0] + a[2], b[0] + b[2]), y1 = Math.min(a[1] + a[3], b[1] + b[3]);
  return x1 > x0 && y1 > y0 ? (x1 - x0) * (y1 - y0) : 0;
}
const round = (r) => r.map((v) => Math.round(v));

/**
 * Check boxes against the frame. boxes: [{rect, size, text, overflow, owner: {id, kind}, fontOk?, font?}].
 * opts: {w, h, safe, minText, pairsToSkip: Set('a|b')}.
 */
export function checkBoxes(boxes, opts) {
  const { w, h, safe } = opts;
  const minText = opts.minText;
  const issues = [];
  const shotOf = (b) => (b.owner ? b.owner.id : null);
  const fonts = new Set();
  for (const b of boxes) {
    const [x, y, bw, bh] = b.rect;
    const shot = shotOf(b);
    const label = JSON.stringify(b.text.length > 40 ? `${b.text.slice(0, 40)}…` : b.text);
    if (b.size < minText - 0.01) {
      issues.push({ kind: 'small_text', msg: `text ${label} is ${b.size.toFixed(1)} px (min ${minText} px at this size)`, rect: round(b.rect), shot });
    }
    if (x < -2 || y < -2 || x + bw > w + 2 || y + bh > h + 2) {
      issues.push({ kind: 'clip', msg: `text ${label} runs off the frame`, rect: round(b.rect), shot });
    } else if (b.overflow) {
      issues.push({ kind: 'clip', msg: `text ${label} overflows its box (maxWidth/overflow)`, rect: round(b.rect), shot });
    }
    if (x < safe.l - 1 || y < safe.t - 1 || x + bw > w - safe.r + 1 || y + bh > h - safe.b + 1) {
      issues.push({ kind: 'safe', msg: `text ${label} is outside the safe area`, rect: round(b.rect), shot });
    }
    if (b.fontOk === false && !fonts.has(b.font)) {
      fonts.add(b.font);
      issues.push({ kind: 'error', msg: `font not loaded for ${label}: ${b.font} (a fallback font was used)`, rect: round(b.rect), shot });
    }
  }
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      const sa = shotOf(a), sb = shotOf(b);
      if (sa !== sb && opts.pairsToSkip && opts.pairsToSkip.has(`${sa}|${sb}`)) continue;
      if (a.el && b.el && (a.el.contains(b.el) || b.el.contains(a.el))) continue;
      if (a.block && a.block === b.block) continue;   // same paragraph flow (per-letter/word spans)
      const ov = inter(a.rect, b.rect);
      const small = Math.min(area(a.rect), area(b.rect));
      if (small > 0 && ov / small > 0.15) {
        issues.push({ kind: 'overlap', msg: `text ${JSON.stringify(a.text.slice(0, 30))} overlaps ${JSON.stringify(b.text.slice(0, 30))} (${Math.round((100 * ov) / small)}%)`, rect: round(a.rect), shot: sa });
      }
    }
  }
  return issues;
}
