// Burned-in captions (film.captions) and the cheap in-page finish (grain, vignette, bloom).
import { mixSeed, mulberry32 } from './rand.js';
import { typeset } from './typeset.js';

const FADE = 0.14;      // s, caption fade in/out
const JOIN = 0.3;       // s, gaps shorter than this keep the plate up (one plate per run of phrases)
const GENERIC = /^(serif|sans-serif|monospace|system-ui|cursive|fantasy)$/;

/** CSS font-family value: quote real family names, keep generic keywords and lists as they are. */
export function familyCss(fam) {
  return /[",]/.test(fam) || GENERIC.test(fam) ? fam : `"${fam}"`;
}

/** Caption layer: one plate, text swaps per caption; plate stays up across short gaps. */
export class Captions {
  constructor(parent, film, kitFonts = []) {
    this.film = film;
    this.list = [...film.captions]
      .filter((c) => c && Number.isFinite(Number(c.t0)) && Number.isFinite(Number(c.t1)) && c.text)
      .map((c) => ({ t0: Number(c.t0), t1: Number(c.t1), text: typeset(String(c.text)) }))
      .sort((a, b) => a.t0 - b.t0);
    const st = film.captionStyle || {};
    const k = Math.min(film.w, film.h) / 1080;
    const size = Math.max(42, Number(st.size || 46)) * k;
    const fam = st.font || (film.fonts[0] && film.fonts[0].family) || (kitFonts[0] && kitFonts[0].family) || 'sans-serif';
    this.root = document.createElement('div');
    this.root.className = 'sr-captions';
    const s = film.safe;
    const vertical = film.h > film.w;
    const maxW = vertical ? film.w - s.l - s.r : Math.round(film.w * 0.7);
    Object.assign(this.root.style, {
      position: 'absolute', left: '0', right: '0', bottom: `${s.b + (vertical ? 0 : 8 * k)}px`,
      display: 'flex', justifyContent: 'center', pointerEvents: 'none',
    });
    this.plate = document.createElement('div');
    this.plate.className = 'sr-caption-plate';
    const plate = st.plate !== false;
    Object.assign(this.plate.style, {
      maxWidth: `${maxW}px`, boxSizing: 'border-box', textAlign: 'center',
      font: `${st.weight || 600} ${size.toFixed(1)}px ${familyCss(fam)}`,
      lineHeight: '1.22', color: st.color || '#fff', letterSpacing: st.letterSpacing || '0.005em',
      padding: plate ? `${(0.3 * size).toFixed(1)}px ${(0.62 * size).toFixed(1)}px` : '0',
      background: plate ? (st.bg || 'rgba(8,9,12,0.66)') : 'transparent',
      borderRadius: plate ? `${(0.28 * size).toFixed(1)}px` : '0',
      textShadow: plate ? 'none' : '0 2px 3px rgba(0,0,0,.85), 0 0 2px rgba(0,0,0,.9)',
      visibility: 'hidden', fontSynthesis: 'none',
    });
    this.root.appendChild(this.plate);
    parent.appendChild(this.root);
    this.current = null;
  }

  update(t) {
    const i = this.list.findIndex((c) => t >= c.t0 && t < c.t1);
    if (i < 0) { this.plate.style.visibility = 'hidden'; this.current = null; return; }
    const c = this.list[i];
    const prev = this.list[i - 1], next = this.list[i + 1];
    const joinedIn = prev && c.t0 - prev.t1 < JOIN;
    const joinedOut = next && next.t0 - c.t1 < JOIN;
    let a = 1;
    if (!joinedIn) a = Math.min(a, (t - c.t0) / FADE);
    if (!joinedOut) a = Math.min(a, (c.t1 - t) / FADE);
    a = Math.max(0, Math.min(1, a));
    if (this.current !== c.text) { this.plate.textContent = c.text; this.current = c.text; }
    this.plate.style.visibility = a > 0 ? 'visible' : 'hidden';
    this.plate.style.opacity = a.toFixed(3);
  }
}

/** Grain (seeded per frame), vignette and a cheap backdrop-filter bloom, all above captions. */
export class Finish {
  constructor(parent, film) {
    this.film = film;
    const f = film.finish || {};
    this.grain = Math.max(0, Math.min(1, Number(f.grain || 0)));
    this.vignette = Math.max(0, Math.min(1, Number(f.vignette || 0)));
    this.bloom = Math.max(0, Math.min(1, Number(f.bloom || 0)));
    this.root = document.createElement('div');
    this.root.className = 'sr-finish';
    Object.assign(this.root.style, { position: 'absolute', inset: '0', pointerEvents: 'none' });
    parent.appendChild(this.root);
    if (this.bloom > 0) {
      const b = document.createElement('div');
      const k = Math.min(film.w, film.h) / 1080;
      Object.assign(b.style, {
        position: 'absolute', inset: '0', mixBlendMode: 'screen', opacity: String(Math.min(1, this.bloom * 1.6)),
        backdropFilter: `brightness(0.7) contrast(3.2) saturate(1.2) blur(${Math.round(22 * k)}px)`,
      });
      this.root.appendChild(b);
    }
    if (this.vignette > 0) {
      const v = document.createElement('div');
      Object.assign(v.style, {
        position: 'absolute', inset: '0',
        background: `radial-gradient(ellipse 75% 72% at 50% 50%, rgba(0,0,0,0) 52%, rgba(0,0,0,${(this.vignette * 0.9).toFixed(3)}) 100%)`,
      });
      this.root.appendChild(v);
    }
    if (this.grain > 0) {
      this.canvas = document.createElement('canvas');
      this.canvas.width = Math.ceil(film.w / 2);
      this.canvas.height = Math.ceil(film.h / 2);
      Object.assign(this.canvas.style, {
        position: 'absolute', inset: '0', width: '100%', height: '100%', mixBlendMode: 'overlay',
        opacity: String(Math.min(1, this.grain * 4)),
      });
      this.root.appendChild(this.canvas);
      this.g = this.canvas.getContext('2d');
      this.tiles = [0, 1, 2, 3].map((i) => this._tile(mixSeed(film.seed, 'grain', i)));
    }
  }

  _tile(seed) {
    const n = 256;
    const c = document.createElement('canvas');
    c.width = c.height = n;
    const g = c.getContext('2d');
    const img = g.createImageData(n, n);
    const r = mulberry32(seed);
    for (let i = 0; i < n * n; i++) {
      // approx gaussian (sum of 3 uniforms), centred on mid grey
      const v = 128 + ((r() + r() + r() - 1.5) / 0.5) * 48;
      const q = v < 0 ? 0 : v > 255 ? 255 : v;
      img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = q;
      img.data[i * 4 + 3] = 255;
    }
    g.putImageData(img, 0, 0);
    return this.g.createPattern(c, 'repeat');
  }

  update(frame) {
    if (!this.g) return;
    const r = mulberry32(mixSeed(this.film.seed, 'grainframe', frame));
    const pat = this.tiles[Math.floor(r() * this.tiles.length)];
    const ox = Math.floor(r() * 256), oy = Math.floor(r() * 256);
    const g = this.g;
    g.setTransform(1, 0, 0, 1, ox, oy);
    g.fillStyle = pat;
    g.fillRect(-ox, -oy, this.canvas.width, this.canvas.height);
    g.setTransform(1, 0, 0, 1, 0, 0);
  }
}
