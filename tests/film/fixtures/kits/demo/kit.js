// Demo kit for runtime tests: one scene per layer + a pixel shot + an overlay. Not shipped to users.
import { sr } from '../../runtime/showreel.js';

sr.defineKit('demo', {
  /** A rounded pill with readable text (registered for QA through ctx.text). */
  pill(ctx, g, text, x, y, o = {}) {
    const size = o.size || 30;
    g.font = `500 ${size}px "Demo Sans"`;
    const w = g.measureText(text).width + size * 1.2, h = size * 1.7;
    g.fillStyle = o.bg || 'rgba(10,12,18,.72)';
    g.beginPath();
    g.roundRect(x, y, w, h, h / 2);
    g.fill();
    ctx.text(g, text, { x: x + size * 0.6, y: y + h / 2, size, font: 'Demo Sans', weight: 500, baseline: 'middle', color: o.color || '#fff' });
    return { w, h };
  },
});

sr.defineScene('kit:demo/bars', {
  layer: '2d',
  describe: 'Gradient backdrop, noise-driven bars, a frames asset and a kinetic title.',
  params: {
    title: { type: 'string', default: 'Showreel', doc: 'headline' },
    clip: { type: 'asset', default: null, doc: 'frames asset shown on the right' },
  },
  render(ctx, t, p) {
    const { g, w, h } = ctx;
    const grd = g.createLinearGradient(0, 0, w, h);
    grd.addColorStop(0, '#0e1524');
    grd.addColorStop(1, '#3a1d4f');
    g.fillStyle = grd;
    g.fillRect(0, 0, w, h);
    const n = 24;
    for (let i = 0; i < n; i++) {
      const hh = h * 0.25 * (0.55 + 0.45 * ctx.noise2(i * 0.31, t * 0.9));
      g.fillStyle = `hsl(${205 + i * 4} 70% 62% / 0.45)`;
      g.fillRect((i * w) / n + 3, h - hh, w / n - 6, hh);
    }
    if (p.clip) {
      const a = ctx.asset(p.clip);
      const k = ctx.seg(t, 0.15, 0.8, 'outCubic');
      const cw = w * 0.34, ch = (cw * a.h) / a.w;
      g.globalAlpha = k;
      g.drawImage(a.frame(t), w * 0.6, h * 0.22 + (1 - k) * 30, cw, ch);
      g.globalAlpha = 1;
    }
    const u = ctx.seg(t, 0.1, 0.7, ctx.ease.snappy);
    ctx.text(g, p.title, { x: ctx.safe.l + 40, y: h * 0.4 + (1 - u) * 24, size: 104, font: 'Demo Sans', color: '#fff', alpha: u, baseline: 'top' });
    ctx.text(g, 'one runtime, four layers', { x: ctx.safe.l + 44, y: h * 0.4 + 130, size: 44, font: 'Demo Sans', color: '#b9c4dd', alpha: u, baseline: 'top' });
  },
  cues() { return [{ t: 0.1, sfx: 'whoosh_short_1' }]; },
});

sr.defineScene('kit:demo/card', {
  layer: 'dom',
  describe: 'A glass card with a title and a line of body text (DOM layer).',
  params: {
    title: { type: 'string', default: 'DOM shot' },
    body: { type: 'string', default: 'Laid out by the browser, measured by QA.' },
  },
  setup(ctx, p) {
    ctx.css(`
      :scope { background: radial-gradient(120% 90% at 30% 20%, #1d2a55, #0b0c10 70%); font-family: "Demo Sans"; }
      .card { position: absolute; left: 50%; top: 50%; width: 1000px; box-sizing: border-box; padding: 56px 64px;
              border-radius: 32px; background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.16); color: #fff; }
      .card h1 { font-size: 88px; line-height: 1.05; margin: 0 0 20px; font-weight: 400; }
      .card p { font-size: 42px; margin: 0; color: #c9d2e8; }`);
    const card = ctx.el('div', { class: 'card' }, ctx.el('h1', { text: p.title }), ctx.el('p', { text: p.body }));
    ctx.root.append(card);
    ctx.state.card = card;
  },
  render(ctx, t) {
    const u = ctx.seg(t, 0.05, 0.7, ctx.ease.snappy);
    const [dx, dy] = ctx.shake(t, { amp: 2, freq: 0.6, decay: 0 });
    const c = ctx.state.card;
    c.style.transform = `translate(-50%, -50%) translate(${dx.toFixed(2)}px, ${((1 - u) * 28 + dy).toFixed(2)}px) rotate(${ctx.lerp(-2, 0, u).toFixed(3)}deg)`;
    c.style.opacity = u.toFixed(3);
  },
});

sr.defineScene('kit:demo/cube', {
  layer: 'three',
  describe: 'A lit cube wearing an image asset (three layer).',
  params: { image: { type: 'asset', default: null } },
  setup(ctx, p) {
    const { THREE, three } = ctx;
    three.scene.background = new THREE.Color('#0b0d12');
    let tex = null;
    if (p.image) {
      tex = new THREE.Texture(ctx.asset(p.image).image);
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.needsUpdate = true;
    }
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(2.4, 2.4, 2.4),
      new THREE.MeshStandardMaterial({ map: tex, color: tex ? 0xffffff : 0x4a7bd1, roughness: 0.45 }));
    three.scene.add(mesh);
    three.scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const key = new THREE.DirectionalLight(0xffffff, 2.6);
    key.position.set(3, 4, 5);
    three.scene.add(key);
    ctx.state.mesh = mesh;
  },
  render(ctx, t) {
    ctx.state.mesh.rotation.set(0.45 + t * 0.5, t * 0.8, 0);
    ctx.three.camera.position.z = 9 - 1.5 * ctx.seg(t, 0, 2, 'outCubic');
  },
});

const HERO = [
  '...aaaa...',
  '..abbbba..',
  '..abcbca..',
  '..abbbba..',
  '...aaaa...',
  '..dddddd..',
  '.d.dddd.d.',
  '...d..d...',
  '..dd..dd..',
];

sr.defineScene('kit:demo/pixel', {
  layer: '2d',
  describe: 'Pixel-art strip: dithered dusk sky, a walking sprite, crisp 1-bit text.',
  params: { label: { type: 'string', default: 'LEVEL 2' } },
  setup(ctx) {
    const pal = ctx.pixel.palette('dusk32');
    ctx.state.pal = pal.named;
    ctx.state.hero = ctx.pixel.sprite(HERO, { a: pal.named.ink, b: pal.named.peach, c: pal.named.ink, d: pal.named.royal });
  },
  render(ctx, t, p) {
    const { g, w, h } = ctx;
    const P = ctx.state.pal;
    ctx.pixel.bands(g, 0, 0, w, Math.round(h * 0.72), [P.night, P.navy, P.plum, P.violet, P.lilac, P.rose]);
    g.fillStyle = P.forestdk;
    g.fillRect(0, Math.round(h * 0.72), w, h);
    ctx.pixel.dither(g, 0, Math.round(h * 0.72), w, 6, P.forest, P.forestdk, 0.5);
    const x = Math.round(ctx.lerp(-30, w * 0.62, ctx.seg(t, 0, 2.2)));
    const bob = Math.round(Math.abs(Math.sin(t * 9)) * 2);
    ctx.pixel.blit(g, ctx.state.hero, x, Math.round(h * 0.72) - 36 - bob, { scale: 4 });
    ctx.text(g, p.label, { x: w / 2, y: 36, size: 16, font: 'Demo Sans', align: 'center', color: P.gold, pixel: true, baseline: 'top', shadow: { color: P.ink, x: 1, y: 1 } });
  },
});

sr.defineScene('kit:demo/badge', {
  layer: '2d',
  describe: 'Overlay pill in the top-left safe corner.',
  params: { text: { type: 'string', default: 'RUNTIME DEMO' } },
  render(ctx, t, p) {
    const a = ctx.seg(t, 0, 0.4) * (1 - ctx.seg(t, ctx.dur - 0.4, ctx.dur));
    if (a <= 0) return;
    ctx.g.globalAlpha = a;
    ctx.kit('demo').pill(ctx, ctx.g, p.text, ctx.safe.l, ctx.safe.t, { size: 30 });
  },
});

// ------------------------------------------------------------------ deliberately broken scenes (tests only)
sr.defineScene('kit:demo/qa-bad', {
  layer: '2d',
  describe: 'Text that breaks every layout rule (QA tests).',
  render(ctx) {
    const { g, w, h } = ctx;
    g.fillStyle = '#123';
    g.fillRect(0, 0, w, h);
    ctx.text(g, 'tiny footnote', { x: w / 2, y: h / 2, size: 12, font: 'Demo Sans', align: 'center' });
    ctx.text(g, 'EDGE', { x: 8, y: 8, size: 48, font: 'Demo Sans', baseline: 'top' });
    ctx.text(g, 'Off the frame', { x: w - 60, y: h * 0.3, size: 64, font: 'Demo Sans' });
    ctx.text(g, 'Overlap one', { x: w * 0.3, y: h * 0.7, size: 56, font: 'Demo Sans' });
    ctx.text(g, 'Overlap two', { x: w * 0.3 + 20, y: h * 0.7 + 10, size: 56, font: 'Demo Sans' });
    ctx.text(g, 'missing font', { x: w * 0.3, y: h * 0.45, size: 40, font: 'No Such Font' });
  },
});

sr.defineScene('kit:demo/qa-dom', {
  layer: 'dom',
  describe: 'DOM text that overflows its box and is too small (QA tests).',
  setup(ctx) {
    ctx.css(`.box { position: absolute; left: 400px; top: 400px; width: 300px; height: 64px; overflow: hidden;
               white-space: nowrap; font: 48px "Demo Sans"; color: #fff; }
             .small { position: absolute; left: 400px; top: 600px; font: 14px "Demo Sans"; color: #fff; }
             .deco { top: 700px; }`);
    ctx.root.append(ctx.el('div', { class: 'box', text: 'This line is far too long for its box' }),
      ctx.el('div', { class: 'small', text: 'tiny dom text' }),
      ctx.el('div', { class: 'small deco', 'data-qa': 'off', text: 'decorative' }));
  },
  render() {},
});

sr.defineScene('kit:demo/throws', {
  layer: '2d',
  render(ctx, t) {
    ctx.g.fillStyle = '#222';
    ctx.g.fillRect(0, 0, ctx.w, ctx.h);
    if (t > 0.5) throw new Error(`boom at ${t.toFixed(2)}`);
  },
});

sr.defineScene('kit:demo/setup-throws', {
  layer: '2d',
  setup() { throw new Error('setup exploded'); },
  render() {},
});

sr.defineScene('kit:demo/impure', {
  layer: '2d',
  setup(ctx) { ctx.state.n = 0; },
  render(ctx) {
    ctx.state.n += 1;
    const { g } = ctx;
    g.fillStyle = '#000';
    g.fillRect(0, 0, ctx.w, ctx.h);
    g.fillStyle = '#fff';
    g.fillRect((ctx.state.n * 97) % (ctx.w - 200), 100, 200, 200);
  },
});

sr.defineScene('kit:demo/sloppy', {
  layer: '2d',
  describe: 'Uses Math.random and Date.now; the runtime safety net must keep it deterministic.',
  render(ctx) {
    const { g } = ctx;
    g.fillStyle = '#000';
    g.fillRect(0, 0, ctx.w, ctx.h);
    for (let i = 0; i < 40; i++) {
      g.fillStyle = `hsl(${Math.floor(Math.random() * 360)} 80% 60%)`;
      g.fillRect(Math.random() * ctx.w, Math.random() * ctx.h, 40, 40);
    }
    g.fillRect((Date.now() / 10) % ctx.w, 10, 20, 20);
  },
});

// ------------------------------------------------------------------ SDK additions (wave 3)
sr.defineScene('kit:demo/probe', {
  layer: 'dom',
  describe: 'Checks ctx.h is the surface height on DOM layers, ctx.film.safe exists, qaText works on DOM layers.',
  setup(ctx) {
    if (typeof ctx.h !== 'number' || ctx.h <= 0) throw new Error(`ctx.h is not the surface height: ${typeof ctx.h}`);
    if (typeof ctx.el !== 'function') throw new Error('ctx.el (DOM builder) missing');
    const s = ctx.film.safe;
    if (!s || !(s.l > 0) || !(s.b > 0)) throw new Error(`ctx.film.safe missing: ${JSON.stringify(s)}`);
    ctx.root.append(ctx.el('div', { style: { position: 'absolute', left: '0', top: '0', width: `${ctx.w}px`, height: `${ctx.h}px`, background: '#111' } }));
  },
  render(ctx) {
    // text "painted into a texture": registered by hand, deliberately tiny so QA reports it
    ctx.qaText([ctx.w / 2, ctx.h / 2, 120, 10], 9, 'texture text');
  },
});

sr.defineTransition('kit:demo/flash', {
  kind: 'css',
  render(tx, u) {
    tx.toEl.style.opacity = String(u);
    tx.g.fillStyle = `rgba(255,255,255,${(1 - Math.abs(u * 2 - 1)).toFixed(3)})`;
    tx.g.fillRect(0, 0, tx.w, tx.h);
  },
  cues(p, tr) { return [{ u: 0.5, sfx: p.sfx || 'pop' }, { t: 0, sfx: 'whoosh_short', gain_db: -6 }]; },
});
