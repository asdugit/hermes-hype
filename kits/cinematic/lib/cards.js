// cinematic kit · evidence cards painted into OffscreenCanvases (uploaded as emissive textures).
// Every string comes verbatim from the scene data (TimelineScene.data shapes); nothing here invents content.
// Ported from the approved style frame (styleframes/cinematic/cards.js) and adapted to the storyboard shapes.
// Cards carry a transparent margin (PAD) so the per-object DOF blur can spread past the panel edge.

export const PAD = 48;
export const RADIUS = 22;

export const C = {
  body0: '#121822', body1: '#0a0e14', border: 'rgba(255,255,255,0.10)', head: 'rgba(255,255,255,0.035)',
  text: '#E9E4DA', mid: '#AEB4BE', dim: '#6F7682', faint: '#454B55',
  kw: '#F4F0E8', str: '#CDBB9E', num: '#D8C9B0', fn: '#FFFFFF', com: '#646B76',
  accent: '#FFB04C', accentBg: 'rgba(255,176,76,0.10)', addBg: 'rgba(255,214,160,0.07)', delBg: 'rgba(255,255,255,0.025)',
};
export const MONO = '"Geist Mono", "Plex Fallback", monospace';
export const SANS = '"Geist", sans-serif';
export const SERIF = '"Cormorant Garamond", serif';

export function rr(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}

function makeCanvas(w, h) {
  const cv = new OffscreenCanvas(Math.ceil(w + PAD * 2), Math.ceil(h + PAD * 2));
  const g = cv.getContext('2d');
  g.translate(PAD, PAD);
  g.textBaseline = 'alphabetic';
  return { cv, g };
}
const measureCtx = (() => { let m = null; return () => (m || (m = new OffscreenCanvas(8, 8).getContext('2d'))); })();

/** Truncate `s` with an ellipsis to fit maxW at the current font. */
function fit(g, s, maxW) {
  s = String(s ?? '');
  if (g.measureText(s).width <= maxW) return s;
  let lo = 0, hi = s.length;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (g.measureText(s.slice(0, m) + '…').width <= maxW) lo = m; else hi = m - 1; }
  return s.slice(0, lo) + '…';
}

function panel(g, w, h, { title, kind, headH = 76 }) {
  const gr = g.createLinearGradient(0, 0, w * 0.35, h);
  gr.addColorStop(0, C.body0); gr.addColorStop(1, C.body1);
  rr(g, 0, 0, w, h, RADIUS); g.fillStyle = gr; g.fill();
  g.save(); rr(g, 0, 0, w, h, RADIUS); g.clip();
  g.fillStyle = C.head; g.fillRect(0, 0, w, headH);
  g.fillStyle = 'rgba(255,255,255,0.07)'; g.fillRect(0, headH, w, 1.5);
  g.restore();
  rr(g, 0.75, 0.75, w - 1.5, h - 1.5, RADIUS); g.strokeStyle = C.border; g.lineWidth = 1.5; g.stroke();
  let kw = 0;
  if (kind) {
    g.font = `600 17px ${SANS}`; g.letterSpacing = '4px'; g.fillStyle = C.dim;
    kw = g.measureText(kind).width;
    g.fillText(kind, w - 34 - kw, headH / 2 + 6);
    g.letterSpacing = '0px';
  }
  g.font = `400 25px ${MONO}`; g.fillStyle = C.mid;
  g.fillText(fit(g, title, w - 100 - kw), 34, headH / 2 + 9);
  return headH;
}

const KW = new Set(('import from def return if try except pass and or not in is None True False finally as with for while class lambda else elif raise yield await async ' +
  'const let var function new this typeof instanceof export default extends static get set null undefined true false of do switch case break continue throw catch ' +
  'fn pub struct impl use mut match enum trait type interface package func go defer select chan map range nil').split(' '));

/** Tiny tokenizer → [{t, c, w}] with monochrome colour roles. */
export function tokens(line) {
  const out = []; const re = /(#.*$|\/\/.*$)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$][A-Za-z0-9_$]*)|(\s+)|(.)/g;
  let m; let prev = '';
  while ((m = re.exec(line))) {
    if (m[1]) out.push({ t: m[1], c: C.com });
    else if (m[2]) out.push({ t: m[2], c: C.str });
    else if (m[3]) out.push({ t: m[3], c: C.num });
    else if (m[4]) out.push({ t: m[4], c: KW.has(m[4]) ? C.kw : (prev === 'def' || prev === 'function' ? C.fn : C.mid), w: KW.has(m[4]) ? 600 : 400 });
    else out.push({ t: m[0], c: m[5] ? C.mid : C.dim });
    if (m[4]) prev = m[4]; else if (!m[5]) prev = '';
  }
  return out;
}

function drawTokens(g, toks, x, y, size, alpha = 1, maxX = 1e9) {
  g.globalAlpha = alpha;
  for (const k of toks) {
    g.font = `${k.w || 400} ${size}px ${MONO}`; g.fillStyle = k.c;
    const tw = g.measureText(k.t).width;
    if (x + tw > maxX) { g.fillText(fit(g, k.t, Math.max(0, maxX - x)), x, y); break; }
    g.fillText(k.t, x, y); x += tw;
  }
  g.globalAlpha = 1;
}

/** CODE {path, lang, lines, start, focus:[a,b]} → card; returns rows' y for focus pushes. */
export function codeCard(d) {
  const lines = (d.lines || []).slice(0, 18).map((l) => String(l).replace(/\t/g, '    '));
  const size = 29, lh = 48, w = 1480, head = 76, start = Number(d.start || 1);
  const h = head + 40 + Math.max(1, lines.length) * lh + 30;
  const { cv, g } = makeCanvas(w, h);
  panel(g, w, h, { title: d.path || 'code', kind: String(d.lang || '').toUpperCase() });
  let [f0, f1] = d.focus || [0, -1];
  if (f0 < start && f1 < start + lines.length && f0 > 0) { f0 += start - 1; f1 += start - 1; }
  const rows = [];
  lines.forEach((ln, i) => {
    const n = start + i, y = head + 40 + i * lh + size, focus = n >= f0 && n <= f1;
    if (focus) { g.fillStyle = 'rgba(255,255,255,0.035)'; g.fillRect(0, y - size - 10, w, lh); g.fillStyle = C.accent; g.fillRect(0, y - size - 10, 4, lh); }
    g.font = `400 ${size - 4}px ${MONO}`; g.fillStyle = focus ? C.accent : C.faint;
    g.fillText(String(n).padStart(3, ' '), 22, y);
    drawTokens(g, tokens(ln), 104, y, size, focus ? 1 : 0.62, w - 30);
    rows.push({ y: y - size * 0.4, focus });
  });
  return { cv, w, h, tint: [0.55, 0.62, 0.75], rows, kind: 'code' };
}

/** DIFF {path, hunks:[{header, lines:[[op,text]]}], adds, dels} → card. */
export function diffCard(d) {
  const flat = [];
  for (const hk of d.hunks || []) {
    if (hk.header) flat.push(['@', hk.header]);
    for (const l of hk.lines || []) flat.push([l[0] === '-' ? '-' : l[0] === '+' ? '+' : ' ', String(l[1] ?? '')]);
  }
  const rowsIn = flat.slice(0, 24);
  const size = 27, lh = 46, w = 1560, head = 76;
  const h = head + 34 + Math.max(1, rowsIn.length) * lh + 28;
  const { cv, g } = makeCanvas(w, h);
  panel(g, w, h, { title: d.path || 'diff', kind: '' });
  g.font = `500 24px ${MONO}`; const s1 = `+${d.adds ?? 0}`, s2 = `\u2212${d.dels ?? 0}`;
  const w2 = g.measureText(s2).width, w1 = g.measureText(s1).width;
  g.fillStyle = C.dim; g.fillText(s2, w - 34 - w2, 47);
  g.fillStyle = C.accent; g.fillText(s1, w - 34 - w2 - 22 - w1, 47);
  const rows = [];
  rowsIn.forEach(([op, ln], i) => {
    const y = head + 34 + i * lh + size;
    if (op === '+') { g.fillStyle = C.addBg; g.fillRect(0, y - size - 10, w, lh); g.fillStyle = C.accent; g.fillRect(0, y - size - 10, 4, lh); }
    if (op === '-') { g.fillStyle = C.delBg; g.fillRect(0, y - size - 10, w, lh); }
    if (op === '@') { g.font = `400 ${size - 3}px ${MONO}`; g.fillStyle = C.faint; g.fillText(fit(g, ln, w - 80), 30, y); rows.push({ y, op }); return; }
    g.font = `500 ${size}px ${MONO}`; g.fillStyle = op === '+' ? C.accent : op === '-' ? C.dim : C.faint;
    g.fillText(op === '-' ? '\u2212' : op, 30, y);
    if (op === '-') {
      g.font = `400 ${size}px ${MONO}`; g.fillStyle = C.dim; const s = fit(g, ln.replace(/\t/g, '    '), w - 110); g.fillText(s, 70, y);
      const tw = g.measureText(s).width; g.fillStyle = 'rgba(160,166,176,0.55)'; g.fillRect(70, y - size * 0.33, tw, 1.5);
    } else drawTokens(g, tokens(ln.replace(/\t/g, '    ')), 70, y, size, op === '+' ? 1 : 0.6, w - 30);
    rows.push({ y: y - size * 0.4, op });
  });
  return { cv, w, h, tint: [0.75, 0.66, 0.52], rows, kind: 'diff' };
}

const LIT = /(\bpass(ed)?\b|\u2713|\bok\b|success|\b0 failed\b|all tests)/i;
/** TERMINAL {cmd, output, exit_code, ok} → card; the PASS/✓ line is marked lit (blooms). */
export function terminalCard(d) {
  const out = (Array.isArray(d.output) ? d.output : String(d.output || '').split('\n')).slice(-12);
  const size = 28, lh = 48, w = 1380, head = 76;
  const rowsN = 1 + out.length;
  const h = head + 38 + rowsN * lh + lh * 0.25 + 30;
  const { cv, g } = makeCanvas(w, h);
  const exit = d.exit_code ?? (d.ok === false ? 1 : 0);
  panel(g, w, h, { title: 'terminal', kind: `EXIT ${exit}` });
  let y = head + 38 + size;
  g.font = `500 ${size}px ${MONO}`; g.fillStyle = C.accent; g.fillText('$', 34, y);
  g.fillStyle = C.text; g.fillText(fit(g, d.cmd || '', w - 110), 70, y);
  y += lh * 1.25;
  const rows = [];
  for (const ln of out) {
    const on = LIT.test(ln) && exit === 0;
    if (on) { g.fillStyle = C.accentBg; g.fillRect(0, y - size - 10, w, lh); g.fillStyle = C.accent; g.fillRect(0, y - size - 10, 4, lh); }
    g.font = `${on ? 600 : 400} ${size}px ${MONO}`; g.fillStyle = on ? '#FFE3BC' : C.mid;
    g.fillText(fit(g, ln, w - 60), 34, y); rows.push({ y: y - size * 0.4, lit: on }); y += lh;
  }
  return { cv, w, h, tint: [0.62, 0.62, 0.66], rows, kind: 'terminal' };
}

function check(g, x, y, s, col) {
  g.strokeStyle = col; g.lineWidth = 3.2; g.lineCap = 'round'; g.lineJoin = 'round';
  g.beginPath(); g.moveTo(x, y - s * 0.42); g.lineTo(x + s * 0.36, y - s * 0.08); g.lineTo(x + s, y - s * 0.86); g.stroke();
}

/** PLAN {items:[{text,status}], more} → card. */
export function planCard(d) {
  const items = (d.items || []).slice(0, 7);
  const w = 1180, head = 76, lh = 70, size = 32;
  const h = head + 30 + Math.max(1, items.length) * lh + (d.more ? 50 : 0) + 26;
  const { cv, g } = makeCanvas(w, h);
  panel(g, w, h, { title: 'plan', kind: 'TODO' });
  const rows = [];
  items.forEach((it, i) => {
    const y = head + 30 + i * lh + 44, st = it.status;
    const done = st === 'completed' || st === 'done', active = st === 'in_progress' || st === 'active';
    if (done) check(g, 38, y - 4, 24, C.mid);
    else if (active) { g.beginPath(); g.arc(50, y - 14, 8, 0, Math.PI * 2); g.fillStyle = C.accent; g.fill(); }
    else { g.beginPath(); g.arc(50, y - 14, 8, 0, Math.PI * 2); g.strokeStyle = C.faint; g.lineWidth = 2; g.stroke(); }
    g.font = `${active ? 500 : 400} ${size}px ${SANS}`;
    g.fillStyle = done ? C.mid : active ? C.text : C.dim;
    g.fillText(fit(g, it.text, w - 130), 92, y);
    rows.push({ y: y - 12, done, active });
  });
  if (d.more) { g.font = `400 26px ${SANS}`; g.fillStyle = C.faint; g.fillText(`+ ${d.more} more`, 92, head + 30 + items.length * lh + 36); }
  return { cv, w, h, tint: [0.6, 0.6, 0.62], rows, kind: 'plan' };
}

export function wrap(g, text, maxW) {
  const words = String(text || '').split(/\s+/).filter(Boolean); const lines = []; let cur = '';
  for (const wd of words) { const t = cur ? cur + ' ' + wd : wd; if (g.measureText(t).width > maxW && cur) { lines.push(cur); cur = wd; } else cur = t; }
  if (cur) lines.push(cur); return lines;
}

/** PROBLEM {text} → the user's prompt card. */
export function promptCard(d) {
  const w = 1240, head = 76, size = 38, lh = 56;
  const m = measureCtx(); m.font = `400 ${size}px ${SANS}`;
  let lines = wrap(m, d.text, w - 90);
  if (lines.length > 8) { lines = lines.slice(0, 8); lines[7] += ' …'; }
  const h = head + 40 + Math.max(1, lines.length) * lh + 34;
  const { cv, g } = makeCanvas(w, h);
  panel(g, w, h, { title: 'you', kind: 'PROMPT' });
  g.font = `400 ${size}px ${SANS}`; g.fillStyle = C.text;
  lines.forEach((l, i) => g.fillText(l, 44, head + 40 + i * lh + size));
  return { cv, w, h, tint: [0.7, 0.68, 0.64], kind: 'prompt' };
}

/** Browser capture: the real screenshot under a slim URL strip. `maxH` crops tall full-page captures (SCROLL uses uv). */
export function screenshotCard(img, url, o = {}) {
  const iw = img.naturalWidth || img.width || 1440, ih = img.naturalHeight || img.height || 900;
  const scale = Math.min(1, (o.maxW || 1600) / iw);
  const w = Math.round(iw * scale), fullH = Math.round(ih * scale);
  const viewH = Math.min(fullH, o.viewH || fullH);
  const bar = url ? 58 : 0, h = viewH + bar;
  const { cv, g } = makeCanvas(w, h);
  rr(g, 0, 0, w, h, RADIUS); g.fillStyle = '#0b0d11'; g.fill();
  g.save(); rr(g, 0, 0, w, h, RADIUS); g.clip();
  if (bar) { g.fillStyle = '#14171d'; g.fillRect(0, 0, w, bar); }
  const sy = o.scroll ? (fullH - viewH) * o.scroll : 0;
  g.drawImage(img, 0, sy / scale, iw, viewH / scale, 0, bar, w, viewH);
  g.restore();
  if (bar) {
    rr(g, 26, 12, w - 52, bar - 24, (bar - 24) / 2); g.fillStyle = 'rgba(255,255,255,0.05)'; g.fill();
    g.font = `400 20px ${MONO}`; g.fillStyle = C.mid; g.fillText(fit(g, String(url).replace(/^[a-z]+:\/\//i, ''), w - 120), 52, bar / 2 + 7);
  }
  rr(g, 0.75, 0.75, w - 1.5, h - 1.5, RADIUS); g.strokeStyle = 'rgba(255,255,255,0.12)'; g.lineWidth = 1.5; g.stroke();
  return { cv, w, h, tint: [0.62, 0.58, 0.48], bar, kind: 'screen', imgW: w, imgH: viewH };
}

/** Tool-call chip (MONTAGE item {tool, arg}). */
export function chipCard(item) {
  const tool = String(item.tool || item.kind || 'tool'), arg = String(item.arg || '');
  const m = measureCtx();
  m.font = `600 30px ${MONO}`; const w1 = m.measureText(tool).width; m.font = `400 30px ${MONO}`;
  const argS = arg.length > 48 ? arg.slice(0, 47) + '…' : arg; const w2 = m.measureText(argS).width;
  const w = Math.ceil(56 + w1 + (argS ? 22 + w2 : 0) + 40), h = 78;
  const { cv, g } = makeCanvas(w, h);
  rr(g, 0, 0, w, h, 39); g.fillStyle = '#10151d'; g.fill();
  rr(g, 0.75, 0.75, w - 1.5, h - 1.5, 38); g.strokeStyle = 'rgba(255,255,255,0.14)'; g.lineWidth = 1.5; g.stroke();
  g.beginPath(); g.arc(34, h / 2, 6, 0, Math.PI * 2); g.fillStyle = C.accent; g.fill();
  g.font = `600 30px ${MONO}`; g.fillStyle = C.text; g.fillText(tool, 56, h / 2 + 10);
  if (argS) { g.font = `400 30px ${MONO}`; g.fillStyle = C.mid; g.fillText(argS, 56 + w1 + 22, h / 2 + 10); }
  return { cv, w, h, tint: [0.6, 0.6, 0.62], radius: 39, kind: 'chip' };
}

/** Abstract ambient glass panel (no text: unreadable texture bars only — never fake content). */
export function ghostCard(rnd, w = 1100 + rnd() * 500, h = 520 + rnd() * 420) {
  const { cv, g } = makeCanvas(w, h);
  const gr = g.createLinearGradient(0, 0, w * 0.35, h); gr.addColorStop(0, C.body0); gr.addColorStop(1, C.body1);
  rr(g, 0, 0, w, h, RADIUS); g.fillStyle = gr; g.fill();
  g.fillStyle = C.head; g.fillRect(0, 0, w, 64);
  rr(g, 0.75, 0.75, w - 1.5, h - 1.5, RADIUS); g.strokeStyle = C.border; g.lineWidth = 1.5; g.stroke();
  let y = 110;
  while (y < h - 40) {
    const x = 40 + Math.floor(rnd() * 3) * 40, len = (0.25 + rnd() * 0.6) * (w - x - 60);
    g.fillStyle = rnd() < 0.08 ? 'rgba(255,176,76,0.35)' : `rgba(200,206,216,${0.10 + rnd() * 0.12})`;
    rr(g, x, y - 10, len, 12, 6); g.fill();
    y += 38 + (rnd() < 0.15 ? 30 : 0);
  }
  return { cv, w, h, tint: [0.55, 0.6, 0.7], kind: 'ghost' };
}

/** Product media card (image/frames asset): glass frame around the real media. `src` must be drawable. */
export function mediaCard(src, w0, h0, o = {}) {
  const scale = Math.min(1, (o.maxW || 1500) / w0);
  const w = Math.round(w0 * scale), h = Math.round(h0 * scale);
  const { cv, g } = makeCanvas(w, h);
  g.save(); rr(g, 0, 0, w, h, RADIUS); g.clip(); g.drawImage(src, 0, 0, w, h); g.restore();
  rr(g, 0.75, 0.75, w - 1.5, h - 1.5, RADIUS); g.strokeStyle = 'rgba(255,255,255,0.14)'; g.lineWidth = 1.5; g.stroke();
  return { cv, w, h, tint: [0.7, 0.6, 0.5], kind: 'media' };
}
