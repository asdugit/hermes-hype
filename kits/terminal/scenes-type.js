// Showreel kit "terminal" — type scenes: TITLE (boot log + block-letter logo), STATS (odometer drums),
// CALLOUT (one hot `# comment` line), END ($ exit -> logout -> lockup -> tube switches off).

import { css } from '../base/dom.js';
import { seg, ease, clamp } from '../base/motion.js';
import { tubeScene } from './tube.js';
import { contentBox } from './scenes-panes.js';
import { ADV, lineH, sp, esc, len, fit, wrap, row, txt, typing, printing, blink, cursor, leader, logo, logoable, logoLines, logoWidth } from './crt.js';
import { odometer } from './pane.js';

/**
 * Block-letter logo lockup for `title` inside width w: one or more logo lines (words wrap), or null when a
 * glyph is missing / a word cannot fit at >= minFs (callers fall back to VT323 display type).
 * Returns {lines: [{word, html(rows)}], fs, w, h}.
 */
export function logoBlock(title, w, maxFs = 20, minFs = 10, maxLines = 2) {
  if (!logoable(title)) return null;
  for (let fs = maxFs; fs >= minFs; fs -= 1) {
    const px = Math.floor(w / (fs * ADV * 2)) - 1;
    const ls = logoLines(title, px);
    if (!ls || ls.length > maxLines) continue;
    const width = Math.max(...ls.map((l) => (logoWidth(l) + 1) * 2)) * fs * ADV;
    return { words: ls, fs, w: width, h: ls.length * 9 * lineH(fs) + (ls.length - 1) * lineH(fs) };
  }
  return null;
}

/** VT323 size so `s` fits `w` px on `lines` lines (VT323 advance ~0.4 em). */
const dispSize = (s, w, max, min = 48, lines = 1) => {
  for (let z = max; z >= min; z -= 4) if (Math.ceil(len(s) * z * 0.42 / w) <= lines) return z;
  return min;
};

// --------------------------------------------------------------------------------------------- TITLE
tubeScene('kit:terminal/TITLE', {
  describe: 'Boot sequence + name: a short boot log prints at line rate, the product name builds row by row as a block-letter logo with a phosphor drop shadow, the tagline prints in VT323, a prompt cursor blinks.',
  params: {
    title: { type: 'string', default: '', doc: 'product / film title' }, tagline: { type: 'string', default: '', doc: '<= 10 words' },
    product: { type: 'string', default: '', doc: 'product name (used when title is empty)' },
    one_liner: { type: 'string', default: '', doc: 'printed as a # comment in the boot log' },
  },
  build(ctx, p, F, T) {
    const L = F.portrait, M = T.M;
    const title = String(p.title || p.product || '').trim() || 'untitled';
    const W = F.W - M.l - M.r;
    // boot log (texture, the real names only)
    const bootFs = L ? 22 : 22, bootCols = L ? 38 : 58;
    const bootLines = [
      row(sp('m', 'SHOWREEL ') + sp('d', '\u00b7 tty1 \u00b7 phosphor ' + (String(p.phosphor || 'p3').toUpperCase())), 0),
      txt('', ''),
      leader(`load ${fit(title, 30)}`, '[  OK  ]', bootCols, 'm'),
      ...(p.tagline ? [leader('tagline', '[  OK  ]', bootCols, 'm')] : []),
      ...(p.one_liner ? wrap(String(p.one_liner), bootCols - 2).slice(0, 2).map((s) => txt('d', '# ' + s)) : []),
    ];
    const boot = T.pre(M.l, L ? M.t - 6 : M.t + 10, bootFs);
    const bootPr = printing(bootLines.length, 0.08, 0.05);
    // logo
    const lb = logoBlock(title, W * (L ? 1 : 0.84), L ? 18 : 24, 10, L ? 3 : 2);
    const cy = L ? F.H * 0.42 : F.H * 0.5;
    let logoEls = [], fallback = null, logoH;
    const logoAt = 0.42, rowGap = 0.045;
    if (lb) {
      logoH = lb.h;
      let y = cy - lb.h / 2 - (L ? 0 : 30);
      for (const word of lb.words) {
        const wpx = (logoWidth(word) + 1) * 2 * lb.fs * ADV;
        const el = T.pre(F.W / 2 - wpx / 2, y, lb.fs);
        el.style.fontWeight = '400';
        el.dataset.qa = 'off'; // decorative block glyphs (the name is also in the status line)
        logoEls.push({ el, word });
        y += 10 * lineH(lb.fs);
      }
    } else {
      const z = dispSize(title, W, L ? 150 : 220, 64, L ? 3 : 2);
      fallback = T.disp(M.l, cy - z * 0.6, z, 'h');
      fallback.style.width = `${W}px`; fallback.style.textAlign = 'center'; fallback.style.whiteSpace = 'normal';
      logoH = z * 1.1;
    }
    const tagY = cy + logoH / 2 + (L ? 70 : 40);
    const tagZ = L ? 56 : 58;
    const tag = T.disp(M.l, tagY, tagZ, '');
    tag.style.width = `${W}px`; tag.style.textAlign = 'center'; tag.style.whiteSpace = 'normal'; tag.style.lineHeight = '1.05';
    const tagTy = typing(String(p.tagline || ''), logoAt + 9 * rowGap + 0.2, { cps: 42, maxDur: 0.9, seed: 5 });
    const prompt = T.pre(M.l, tagY + (L ? 190 : 108), 30);
    prompt.style.width = `${W}px`; prompt.style.textAlign = 'center';
    T.bar('', '');
    T.barEl.style.top = `${F.H - M.b - (L ? 56 : 40)}px`;   // above the caption band, inside the safe area
    const cues = [{ t: logoAt, sfx: 'appear', gain_db: -10 }];
    return {
      cues,
      render(t) {
        const k = bootPr.count(t);
        boot.set(bootLines.slice(0, k).map((r) => r.html).join('\n'));
        css(boot, { opacity: '0.82' });
        const rows = clamp(Math.floor((t - logoAt) / rowGap) + 1, 0, 9);
        for (const l of logoEls) l.el.set(logo(l.word, rows).lines.join('\n'));
        if (fallback) { fallback.textContent = t >= logoAt ? title : ''; css(fallback, { clipPath: `inset(0 0 ${((1 - seg(t, logoAt, logoAt + 0.4)) * 100).toFixed(1)}% 0)` }); }
        const n = tagTy.count(t);
        tag.set(esc([...tagTy.chars].slice(0, n).join('')));
        prompt.set(t >= tagTy.end + 0.1 ? sp('d', '$ ') + cursor(blink(t - tagTy.end)) : '');
        T.barEl.set(t > 0.3 ? T.barHtml(title, '') : '');
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- STATS
tubeScene('kit:terminal/STATS', {
  describe: 'Real session numbers on odometer drums (VT323): the drums roll from 0 with per-digit inertia (the last digit spins longest) and settle with a click; caps labels; never invented numbers.',
  params: { stats: { type: 'array', default: [], doc: '[{key, label, value, display}] 1-3, computed from the session' } },
  build(ctx, p, F, T) {
    const L = F.portrait, B = contentBox(F, T);
    const stats = (p.stats || []).slice(0, 3);
    const n = Math.max(1, stats.length);
    const size = L ? (n === 1 ? 220 : 170) : n === 1 ? 260 : n === 2 ? 210 : 170;
    const odos = stats.map((s) => odometer(String(s.display ?? s.value ?? ''), size));
    const lblFs = L ? 30 : 30;
    const t0 = 0.3;
    const roll = (i) => [t0 + i * 0.14, t0 + 1.0 + i * 0.14];
    const items = odos.map((o, i) => {
      T.scr.appendChild(o.el);
      const lbl = T.disp(0, 0, lblFs);
      lbl.className = 'tm-lbl';
      lbl.style.fontSize = `${lblFs}px`;
      lbl.textContent = String(stats[i].label || stats[i].key || '');
      return { o, lbl, i };
    });
    // layout: a row of columns (16:9) or a stack (9:16); measured after mount
    const rowH = size * 0.96 + 24 + lblFs * 1.3;
    if (L) {
      const total = n * rowH + (n - 1) * 60;
      items.forEach(({ o, lbl, i }) => {
        const y = B.y + (B.h - total) / 2 + i * (rowH + 60);
        css(o.el, { left: `${B.x}px`, top: `${y}px` });
        css(lbl, { left: `${B.x}px`, top: `${y + size * 0.96 + 20}px` });
      });
    } else {
      const colW = B.w / n;
      items.forEach(({ o, lbl, i }) => {
        const x = B.x + colW * i + (n === 1 ? colW / 2 - size * 0.9 : 30);
        const y = B.y + (B.h - rowH) / 2;
        css(o.el, { left: `${x}px`, top: `${y}px` });
        css(lbl, { left: `${x}px`, top: `${y + size * 0.96 + 24}px` });
      });
    }
    const head = String(p.label || '').trim();
    T.bar('stats', head);
    const cues = items.map(({ o, i }) => ({ t: roll(i)[1] + (o.digits - 1) * 0.12, sfx: 'hit', gain_db: -6 }));
    return {
      cues,
      render(t) {
        for (const { o, lbl, i } of items) {
          const [a, b] = roll(i);
          const vis = t >= a - 0.1;
          css(o.el, { visibility: vis ? 'visible' : 'hidden' });
          css(lbl, { visibility: t >= a + 0.25 ? 'visible' : 'hidden' });
          o.update(t, a, b + (o.digits - 1) * 0.12);
        }
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- CALLOUT
tubeScene('kit:terminal/CALLOUT', {
  describe: 'One verbatim line as a hot `# comment` centred on the dark glass; it prints in word chunks (types letter by letter when the user said it), the cursor blinks at the end, attribution in a dim comment; the longest hold.',
  params: {
    text: { type: 'string', default: '', doc: 'verbatim quote (<= 12 words ideal)' }, who: { type: 'string', default: 'agent', doc: 'user | agent | test' },
    ref: { type: 'string', default: '', doc: 'event id' },
  },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, B = contentBox(F, T);
    const fs = L ? 40 : 50;
    const cols = Math.min(L ? 32 : 40, Math.floor(B.w / (fs * ADV)) - 2);
    const lines = wrap(String(p.text || ''), cols - 2);
    const who = String(p.who || 'agent');
    const human = who === 'user';
    const ty = typing(lines.join('\n'), 0.35, { cps: human ? 18 : 60, maxDur: Math.min(dur * 0.45, human ? 2.2 : 0.9), seed: 9 });
    const maxLen = Math.max(...lines.map(len)) + 2;
    const pw = maxLen * fs * ADV, ph = (lines.length + 2) * lineH(fs);
    const el = T.pre(B.x + (B.w - pw) / 2, B.y + (B.h - ph) / 2, fs);
    T.bar('', '');
    return {
      cues: human ? ty.cues({ every: 3 }) : [{ t: 0.35, sfx: 'appear', gain_db: -12 }],
      render(t) {
        const n = ty.count(t);
        const typed = [...ty.chars].slice(0, n).join('').split('\n');
        const out = typed.map((s, i) => sp('d', '# ') + sp('h', s) + (i === typed.length - 1 ? cursor(n < ty.n || blink(t - ty.end)) : ''));
        if (t >= ty.end + 0.25) out.push('', sp('d', `#   \u2014 ${who}`));
        el.set(out.join('\n'));
      },
    };
  },
});

// --------------------------------------------------------------------------------------------- END
tubeScene('kit:terminal/END', {
  describe: 'End card: `$ exit` -> logout, then the block-letter name, the CTA as a hot prompt line, the URL and the "made with Hermes · Showreel" credit (speedrun: the PB time); the tube switches off in the last 0.45 s (the frame before is the thumbnail).',
  powerOff: true,
  params: {
    title: { type: 'string', default: '', doc: 'product name' }, cta: { type: 'string', default: '', doc: 'command or link to try it' },
    url: { type: 'string', default: '', doc: 'repo / site URL' }, credit: { type: 'string', default: 'made with Hermes \u00b7 Showreel', doc: 'small credit line' },
    tagline: { type: 'string', default: '', doc: 'optional line under the title' }, pb_display: { type: 'string', default: '', doc: 'speedrun final time (PB)' },
  },
  build(ctx, p, F, T) {
    const dur = ctx.dur, L = F.portrait, M = T.M;
    const W = F.W - M.l - M.r;
    const title = String(p.title || '').trim() || 'showreel';
    const exitTy = typing('exit', 0.15, { cps: 14, seed: 2 });
    const head = T.pre(M.l, L ? M.t - 6 : M.t + 10, 26);
    const lb = logoBlock(title, W * 0.8, L ? 14 : 16, 8, 2);
    const cy = L ? F.H * 0.36 : F.H * 0.38;
    const lockAt = exitTy.end + 0.45;
    const logoEls = [];
    let fallback = null, logoH;
    if (lb) {
      logoH = lb.h;
      let y = cy - lb.h / 2;
      for (const word of lb.words) {
        const wpx = (logoWidth(word) + 1) * 2 * lb.fs * ADV;
        const el = T.pre(F.W / 2 - wpx / 2, y, lb.fs);
        el.dataset.qa = 'off';
        logoEls.push({ el, word });
        y += 10 * lineH(lb.fs);
      }
    } else {
      const z = dispSize(title, W, L ? 140 : 180, 60, 2);
      fallback = T.disp(M.l, cy - z * 0.55, z, 'h');
      fallback.style.width = `${W}px`; fallback.style.textAlign = 'center'; fallback.style.whiteSpace = 'normal';
      logoH = z;
    }
    let y = cy + logoH / 2 + (L ? 60 : 44);
    const pb = String(p.pb_display || '').trim();
    let pbEl = null;
    if (pb) { pbEl = T.disp(M.l, y, L ? 84 : 90, 'h'); pbEl.style.width = `${W}px`; pbEl.style.textAlign = 'center'; y += L ? 110 : 108; }
    const ctaFs = L ? 30 : 36;
    const cta = String(p.cta || '');
    const ctaLines = wrap(cta, Math.floor(W / (ctaFs * ADV)) - 3, '  ');
    const ctaEl = T.pre(M.l, y, ctaFs);
    ctaEl.style.width = `${W}px`; ctaEl.style.textAlign = 'center';
    const ctaTy = typing(ctaLines.join('\n'), lockAt + 0.35, { cps: 34, maxDur: 0.9, seed: 4 });
    y += ctaLines.length * lineH(ctaFs) + (L ? 40 : 28);
    const urlEl = T.pre(M.l, y, L ? 26 : 28);
    urlEl.style.width = `${W}px`; urlEl.style.textAlign = 'center';
    const credit = String(p.credit || '');
    T.bar('', '');
    T.barEl.style.top = `${F.H - M.b - (L ? 56 : 40)}px`;   // above the caption band, inside the safe area
    const cues = [...exitTy.cues({ every: 2 }), { t: lockAt, sfx: 'appear', gain_db: -8 }];
    return {
      cues,
      render(t) {
        const n = exitTy.count(t);
        const hl = [sp('d', '$ ') + sp('h', 'exit'.slice(0, n)) + (t < exitTy.end + 0.2 ? cursor(true) : '')];
        if (t >= exitTy.end + 0.2) hl.push(sp('m', 'logout'));
        if (t >= exitTy.end + 0.32) hl.push('', sp('d', 'Connection closed.'));
        head.set(hl.join('\n'));
        css(head, { opacity: t > lockAt ? '0.55' : '1' });
        const rows = clamp(Math.floor((t - lockAt) / 0.04) + 1, 0, 9);
        for (const l of logoEls) l.el.set(logo(l.word, rows).lines.join('\n'));
        if (fallback) fallback.textContent = t >= lockAt ? title : '';
        if (pbEl) pbEl.textContent = t >= lockAt + 0.2 ? `PB ${pb}` : '';
        const k = ctaTy.count(t);
        const typed = [...ctaTy.chars].slice(0, k).join('').split('\n');
        ctaEl.set(t >= ctaTy.at[0] - 0.1 && cta ? typed.map((s, i) => (i === 0 ? sp('d', '$ ') : '') + sp('h', s) + (i === typed.length - 1 ? cursor(k < ctaTy.n || blink(t - ctaTy.end)) : '')).join('\n') : '');
        const u = t >= ctaTy.end + 0.15;
        urlEl.set(u ? [p.url ? sp('m', String(p.url)) : '', credit ? sp('d', credit) : ''].filter(Boolean).join('\n') : '');
        T.barEl.set(t > lockAt ? T.barHtml(title, '') : '');
      },
    };
  },
});

export { fit };
