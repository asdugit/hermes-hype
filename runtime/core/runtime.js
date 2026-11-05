// The Showreel runtime: registries, boot, shot instances, seek/composite, cues, QA and the __sr contract.
import { ease } from './ease.js';
import { clamp, fract, keys, lerp, mix, path, remap, seg, shake, smoothstep, spring } from './motion.js';
import { makeNoise } from './noise.js';
import { makeRng, mixSeed } from './rand.js';
import { enterScene, installSafetyNet, leaveScene, realNow } from './safety.js';
import { drawText, measureText } from './text.js';
import { makePixel } from './pixel.js';
import { AssetStore } from './assets.js';
import { loadFonts } from './fonts.js';
import { clampTime, liveAt, normalizeFilm } from './film.js';
import { createSurface, makeShader } from './surfaces.js';
import { BUILTIN_TRANSITIONS } from './transitions.js';
import { Captions, Finish } from './layers.js';
import { checkBoxes, domTextBoxes } from './qa.js';

const SCENE_ID = /^(kit:[a-z0-9_-]+\/[a-z0-9_.-]+|lib:[a-z0-9_.-]+|custom:[a-z0-9_.-]+)$/i;
const LAYERS = new Set(['2d', 'three', 'webgl', 'dom']);
const MAX_ERRORS = 200;
const CACHE_MAX = 4;          // inactive shot instances kept alive (seeks are non-sequential)

const STAGE_CSS = `
html, body { margin: 0; padding: 0; overflow: hidden; background: #000; }
#sr-stage { position: absolute; left: 0; top: 0; overflow: hidden; transform-origin: 0 0; contain: strict; }
#sr-stage .sr-layer { position: absolute; inset: 0; }
#sr-stage .sr-shot { position: absolute; inset: 0; overflow: hidden; }
#sr-stage .sr-surface { position: absolute; left: 0; top: 0; width: 100%; height: 100%; display: block; }
#sr-stage .sr-root { position: absolute; left: 0; top: 0; overflow: hidden; }
#sr-stage .sr-tx { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
`;

function errText(e) {
  if (!e) return 'unknown error';
  const msg = e && e.message ? `${e.name && e.name !== 'Error' ? `${e.name}: ` : ''}${e.message}` : String(e);
  const stack = e && e.stack ? String(e.stack) : '';
  const m = /(?:https?:\/\/[^/]+\/[^/\s]+\/)?((?:kits|scenes|runtime)\/[^\s):]+:\d+:\d+)/.exec(stack);
  return m && !msg.includes(m[1]) ? `${msg} (at ${m[1]})` : msg;
}

function relOf(url) {
  return String(url).replace(/^[a-z]+:\/\/[^/]+\/[^/]+\//i, '');
}

/** Scene/kit-relative base dir from a scene id (kit:<k>/x -> kits/<k>/, custom:/lib: -> scenes/). */
function baseForId(id) {
  const m = /^kit:([^/]+)\//.exec(id);
  return m ? `kits/${m[1]}/` : 'scenes/';
}

/** Defaults from the scene's params doc, overlaid with the shot's params. */
function resolveParams(doc, given) {
  const p = {};
  for (const [k, d] of Object.entries(doc || {})) {
    if (d && typeof d === 'object' && 'default' in d) p[k] = d.default;
  }
  return Object.assign(p, given || {});
}

/** Asset names a shot uses: params typed 'asset' plus any string param that names a manifest asset. */
function assetRefs(doc, p, store) {
  const out = new Set();
  const walk = (v) => {
    if (typeof v === 'string') { if (store.has(v)) out.add(v); }
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(p);
  for (const [k, d] of Object.entries(doc || {})) {
    if (d && (d.type === 'asset' || d.type === 'media') && p[k] != null && !store.has(p[k])) {
      throw new Error(`param '${k}' names asset '${p[k]}', which is not in assets/manifest.json (have: ${store.names().join(', ') || 'none'})`);
    }
  }
  return [...out];
}

export class Runtime {
  constructor() {
    this.scenes = new Map();
    this.transitions = new Map();
    this.kits = new Map();
    this.sceneBase = new Map();
    this.errors = [];
    this._errSeen = new Map();
    this.cues = [];
    this.film = null;
    this.assets = null;
    this.instances = new Map();
    this.queue = Promise.resolve();
    this.lastT = null;
    this.frameErrors = [];
    this.lenient = false;
    this.warnings = [];
    this.ready = new Promise((res, rej) => { this._res = res; this._rej = rej; });
    this.ready.catch(() => {});
    this.txPool = [];
    this.txCache = new Map();
    for (const [name, def] of Object.entries(BUILTIN_TRANSITIONS)) this.transitions.set(name, def);
  }

  // ------------------------------------------------------------------------------- registries
  defineScene(id, def) {
    if (typeof id !== 'string' || !SCENE_ID.test(id)) {
      throw new Error(`sr.defineScene: bad id ${JSON.stringify(id)} (use kit:<kit>/<name>, lib:<name> or custom:<name>)`);
    }
    if (!def || typeof def.render !== 'function') throw new Error(`sr.defineScene('${id}'): render(ctx, t, p) is required`);
    const layer = def.layer || '2d';
    if (!LAYERS.has(layer)) throw new Error(`sr.defineScene('${id}'): layer must be '2d', 'three', 'webgl' or 'dom' (got ${JSON.stringify(layer)})`);
    if (this.scenes.has(id)) this.warnings.push(`scene '${id}' defined twice; the later definition wins`);
    this.scenes.set(id, { ...def, id, layer });
    this.sceneBase.set(id, def.base ? relOf(new URL('.', def.base).href) : baseForId(id));
  }

  defineTransition(id, def) {
    if (typeof id !== 'string' || !id) throw new Error('sr.defineTransition: id must be a non-empty string');
    if (!def || typeof def.render !== 'function') throw new Error(`sr.defineTransition('${id}'): render(tx, u, p) is required`);
    const kind = def.kind || 'canvas';
    if (kind !== 'canvas' && kind !== 'css') throw new Error(`sr.defineTransition('${id}'): kind must be 'canvas' or 'css'`);
    this.transitions.set(id, { ...def, kind });
  }

  defineKit(name, blocks) {
    if (typeof name !== 'string' || !/^[a-z0-9_-]+$/i.test(name)) throw new Error(`sr.defineKit: bad kit name ${JSON.stringify(name)}`);
    this.kits.set(name, blocks || {});
  }

  kit(name) {
    const k = this.kits.get(name);
    if (!k) throw new Error(`kit '${name}' is not loaded in this job (loaded: ${[...this.kits.keys()].join(', ') || 'none'}); list it in film.json "kits"`);
    return k;
  }

  /** URL for a job-relative path. */
  url(rel) { return new URL(rel, this.base).href; }

  /** Resolve a scene/kit-relative path ('/x' = job root). */
  sceneUrl(sceneId, p) {
    if (/^[a-z]+:/i.test(p)) throw new Error(`external or absolute URLs are not allowed: ${p}`);
    if (p.startsWith('/')) return this.url(p.slice(1));
    return this.url((this.sceneBase.get(sceneId) || 'scenes/') + p);
  }

  // ----------------------------------------------------------------------------------- errors
  recordError(where, t, e, shot = null) {
    const text = `${where}${t != null ? ` t=${Number(t).toFixed(3)}` : ''}: ${errText(e)}`;
    const key = `${where}|${errText(e)}`;
    const n = (this._errSeen.get(key) || 0) + 1;
    this._errSeen.set(key, n);
    this.frameErrors.push({ kind: 'error', msg: text, rect: null, shot, src: where });
    if (n === 1 && this.errors.length < MAX_ERRORS) {
      this.errors.push(text);
      console.error(`[showreel] ${text}`);
    }
  }

  // ------------------------------------------------------------------------------------- boot
  async boot(opts = {}) {
    try {
      await this._boot(opts);
      this._res();
    } catch (e) {
      const msg = errText(e);
      console.error(`[showreel] not ready: ${msg}`);
      this._rej(new Error(msg));
    }
  }

  async _boot({ film = 'film.json', manifest = 'assets/manifest.json', modules = [], fonts = [], lenient } = {}) {
    const q = new URLSearchParams(location.search);
    this.base = new URL('.', location.href).href;
    this.lenient = lenient ?? (q.has('lenient') && q.get('lenient') !== '0');
    const soft = (what, e) => {
      if (!this.lenient) throw e;
      this.recordError(what, null, e);
    };
    installSafetyNet();
    const getJson = async (rel, optional) => {
      let r;
      try { r = await fetch(this.url(rel)); } catch (e) { throw new Error(`could not fetch ${rel}: ${e.message}`); }
      if (!r.ok) {
        if (optional && r.status === 404) return null;
        throw new Error(`could not fetch ${rel}: HTTP ${r.status}`);
      }
      try { return await r.json(); } catch (e) { throw new Error(`${rel} is not valid JSON: ${e.message}`); }
    };
    const raw = typeof film === 'object' ? film : await getJson(film);
    this.film = normalizeFilm(raw);
    const F = this.film;
    Object.assign(this.api, { dur: F.dur, fps: F.fps, w: F.w, h: F.h, title: F.title });
    const noise = makeNoise(mixSeed(F.seed, 'noise'));
    this.noise = noise;
    this.assets = new AssetStore((typeof manifest === 'object' ? manifest : await getJson(manifest, true)) || {}, (rel) => this.url(rel));
    for (const m of modules) {
      try {
        await import(this.url(m));
      } catch (e) {
        soft(`module ${m}`, new Error(`module ${m} failed to load: ${errText(e)}`));
      }
    }
    this._buildStage(fonts);
    // scene and transition ids
    const missing = [];
    for (const it of [...F.shots, ...F.overlays]) if (!this.scenes.has(it.scene)) missing.push(`${it.kind} '${it.id}' uses unknown scene '${it.scene}'`);
    for (const tr of F.transitions) if (!this.transitions.has(tr.type)) missing.push(`transition ${tr.index} (${tr.from.id} -> ${tr.to.id}) uses unknown type '${tr.type}'`);
    if (missing.length) {
      const avail = `available scenes: ${[...this.scenes.keys()].join(', ') || 'none'}; transitions: ${[...this.transitions.keys()].join(', ')}`;
      soft('film', new Error(`${missing.join('; ')} (${avail})`));
    }
    // fonts: film, kits, used scenes
    const fontJobs = [
      loadFonts(F.fonts, (src) => this.url(src), 'film.json').catch((e) => soft('fonts', e)),
      loadFonts(fonts, (src) => this.url(src), 'kit.json').catch((e) => soft('fonts', e)),
    ];
    for (const [name, k] of this.kits) {
      if (Array.isArray(k.fonts)) fontJobs.push(loadFonts(k.fonts, (src) => (src.startsWith('/') ? this.url(src.slice(1)) : this.url(`kits/${name}/${src}`)), `kit ${name}`).catch((e) => soft('fonts', e)));
    }
    const used = new Set([...F.shots, ...F.overlays].map((s) => s.scene));
    for (const id of used) {
      const d = this.scenes.get(id);
      if (d && Array.isArray(d.fonts) && d.fonts.length) fontJobs.push(loadFonts(d.fonts, (src) => this.sceneUrl(id, src), id).catch((e) => soft('fonts', e)));
    }
    await Promise.all(fontJobs);
    await document.fonts.ready;
    // assets
    for (const name of Object.keys(F.assets)) {
      if (!this.assets.has(name)) soft('assets', new Error(`film.json asset '${name}' is missing from assets/manifest.json`));
    }
    await this.assets.preloadAll().catch((e) => soft('assets', e));
    this.finish.update(0);
    // set up every shot once: surfaces setup() errors and collects cues; keeps a few instances warm
    const cues = [];
    for (const it of [...F.shots, ...F.overlays]) {
      const inst = await this._instance(it, true);
      for (const c of inst.cues) cues.push({ ...c, t: c.t + it.t0 });
      this._evict(new Set());
    }
    for (const c of F.cues) cues.push({ t: Number(c.t), sfx: String(c.sfx), gain_db: Number(c.gain_db || 0), align: c.align || 'auto', shot: null });
    this.cues = cues.filter((c) => Number.isFinite(c.t) && c.t >= 0 && c.t <= F.dur && c.sfx)
      .sort((a, b) => a.t - b.t || String(a.sfx).localeCompare(String(b.sfx)));
    this.api.cues = this.cues;
  }

  _buildStage(kitFonts = []) {
    const F = this.film;
    const style = document.createElement('style');
    style.textContent = STAGE_CSS;
    document.head.appendChild(style);
    let stage = document.getElementById('sr-stage');
    if (!stage) {
      stage = document.createElement('div');
      stage.id = 'sr-stage';
      document.body.appendChild(stage);
    }
    stage.style.width = `${F.w}px`;
    stage.style.height = `${F.h}px`;
    stage.style.background = F.background;
    const mk = (cls, z) => {
      const d = document.createElement('div');
      d.className = `sr-layer ${cls}`;
      d.style.zIndex = String(z);
      stage.appendChild(d);
      return d;
    };
    this.shotLayer = mk('sr-shots', 1);
    this.overlayLayer = mk('sr-overlays', 2);
    this.captionLayer = mk('sr-captions-layer', 3);
    this.finishLayer = mk('sr-finish-layer', 4);
    this.stage = { el: stage, scale: 1 };
    const fit = () => {
      const s = Math.min(window.innerWidth / F.w, window.innerHeight / F.h) || 1;
      this.stage.scale = s;
      stage.style.transform = Math.abs(s - 1) < 1e-6 ? 'none' : `scale(${s})`;
    };
    fit();
    window.addEventListener('resize', fit);
    this.captions = new Captions(this.captionLayer, F, kitFonts);
    this.finish = new Finish(this.finishLayer, F);
  }

  // -------------------------------------------------------------------------------- instances
  async _instance(item, booting = false) {
    let inst = this.instances.get(item.key);
    if (inst) { inst.used = this._tick(); return inst; }
    inst = await this._create(item, booting);
    this.instances.set(item.key, inst);
    return inst;
  }

  _tick() { this._clock = (this._clock || 0) + 1; return this._clock; }

  _evict(live) {
    const idle = [...this.instances.values()].filter((i) => !live.has(i.item.key)).sort((a, b) => a.used - b.used);
    while (idle.length > CACHE_MAX) this._dispose(idle.shift());
  }

  _dispose(inst) {
    this.instances.delete(inst.item.key);
    try { if (inst.def.dispose && !inst.broken) inst.def.dispose(inst.ctx); } catch (e) { this.recordError(`${inst.item.kind} ${inst.item.id}: dispose()`, null, e); }
    try { inst.surf && inst.surf.dispose(); } catch (_) { /* context already gone */ }
    if (inst.surf) inst.surf.el.remove();
  }

  /** Drop every cached instance (determinism probe: the next seek re-runs setup()). */
  purge() {
    for (const inst of [...this.instances.values()]) this._dispose(inst);
  }

  async _create(item, booting) {
    const F = this.film;
    const where = `${item.kind} '${item.id}' (${item.scene})`;
    let def = this.scenes.get(item.scene);
    const inst = { item, def, surf: null, ctx: null, p: null, boxes: [], cues: [], broken: null, used: this._tick(), stats: { setupMs: 0, renders: 0, totalMs: 0, maxMs: 0 } };
    const fail = (e) => {
      if (!this.lenient && booting) throw new Error(`${where}: ${errText(e)}`);
      inst.broken = errText(e);
      this.recordError(`${item.kind} ${item.id}: setup()`, null, e, item.id);
    };
    if (!def) {
      def = { id: item.scene, layer: '2d', render() {} };
      inst.def = def;
      fail(new Error(`unknown scene '${item.scene}'`));
    }
    const [w, h] = item.res;
    try {
      inst.surf = await createSurface(def.layer, { w, h, filmW: F.w, filmH: F.h, upscale: item.upscale, sceneId: item.scene });
    } catch (e) {
      def = { id: item.scene, layer: '2d', render() {} };
      inst.def = def;
      inst.surf = await createSurface('2d', { w, h, filmW: F.w, filmH: F.h, upscale: item.upscale, sceneId: item.scene });
      fail(e);
    }
    inst.surf.el.style.display = 'none';
    inst.surf.el.dataset.shot = item.id;
    (item.kind === 'overlay' ? this.overlayLayer : this.shotLayer).appendChild(inst.surf.el);
    inst.ctx = this._ctx(item, def, inst);
    if (inst.broken) return inst;
    const t0 = realNow();
    try {
      inst.p = resolveParams(def.params, item.params);
      inst.ctx.params = inst.p;
      inst.assetRefs = assetRefs(def.params, inst.p, this.assets);
      inst.ctx._phase = 'setup';
      enterScene(F.seed, item.id, -1, item.t0);
      if (def.setup) await def.setup(inst.ctx, inst.p);
      if (def.cues) {
        const list = def.cues(inst.ctx, inst.p) || [];
        if (!Array.isArray(list)) throw new Error('cues() must return an array');
        for (const c of list) inst.cues.push(this._cue(c.t, c.sfx, c, item));
      }
    } catch (e) {
      fail(e);
    } finally {
      leaveScene();
      inst.ctx._phase = 'render';
      inst.stats.setupMs = realNow() - t0;
    }
    return inst;
  }

  _cue(t, sfx, o, item) {
    if (!Number.isFinite(Number(t)) || !sfx) throw new Error(`cue needs a numeric t and an sfx name (got t=${t}, sfx=${sfx})`);
    return { t: Number(t), sfx: String(sfx), gain_db: Number((o && o.gain_db) || 0), align: (o && o.align) || 'auto', shot: item.id };
  }

  _ctx(item, def, inst) {
    const F = this.film;
    const rt = this;
    const s = inst.surf;
    const [w, h] = item.res;
    const kx = w / F.w, ky = h / F.h;
    const seed = mixSeed(F.seed, item.id);
    const sink = (box) => {
      inst.boxes.push({
        rect: [box.rect[0] / kx, box.rect[1] / ky, box.rect[2] / kx, box.rect[3] / ky],
        size: box.size / ky, text: box.text, overflow: box.overflow, fontOk: box.fontOk, font: box.font,
        owner: { id: item.id, kind: item.kind },
      });
    };
    const text = (g, str, o = {}) => drawText(g, str, o, g && g.canvas === s.canvas ? sink : null);
    const ctx = {
      w, h, dur: item.dur, id: item.id, seed, layer: def.layer, params: item.params,
      film: { w: F.w, h: F.h, fps: F.fps, dur: F.dur, aspect: F.aspect, title: F.title, seed: F.seed },
      shot: { t0: item.t0, t1: item.t1, kind: item.kind },
      safe: { l: F.safe.l * kx, r: F.safe.r * kx, t: F.safe.t * ky, b: F.safe.b * ky },
      rng: (k = 0) => makeRng(mixSeed(seed, k)),
      noise2: this.noise.noise2, noise3: this.noise.noise3, fbm2: this.noise.fbm2, fbm3: this.noise.fbm3,
      ease, lerp, clamp, smoothstep, remap, mix, fract, seg, spring, keys, path,
      shake: (t, o = {}) => shake(t, { seed, ...o }),
      asset: (name) => rt.assets.handle(name),
      text,
      measure: (g, str, o) => measureText(g, str, o),
      kit: (name) => rt.kit(name),
      url: (p) => rt.sceneUrl(item.scene, p),
      cue(t, sfx, o = {}) {
        if (ctx._phase !== 'setup') throw new Error('ctx.cue() may only be called in setup()');
        inst.cues.push(rt._cue(t, sfx, o, item));
      },
      async loadImage(p) {
        if (ctx._phase !== 'setup') throw new Error('ctx.loadImage() may only be called in setup()');
        const img = new Image();
        img.src = rt.sceneUrl(item.scene, p);
        try { await img.decode(); } catch (_) { throw new Error(`ctx.loadImage('${p}'): ${relOf(img.src)} failed to load`); }
        return img;
      },
      state: {},
      _phase: 'render',
    };
    ctx.pixel = makePixel(text);
    if (def.layer === '2d') { ctx.g = s.g; ctx.canvas = s.canvas; }
    if (def.layer === 'webgl') {
      ctx.gl = s.gl; ctx.canvas = s.canvas;
      ctx.shader = (frag) => makeShader(s.gl, frag);
    }
    if (def.layer === 'three') { ctx.THREE = s.THREE; ctx.three = s.three; ctx.addons = s.addons; ctx.canvas = s.canvas; }
    if (def.layer === 'dom') {
      ctx.root = s.root;
      ctx.css = (cssText) => rt._scopedCss(item.scene, cssText);
      ctx.h = (tag, props = {}, ...kids) => {
        const el = document.createElement(tag);
        for (const [k, v] of Object.entries(props || {})) {
          if (k === 'class' || k === 'className') el.className = v;
          else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
          else if (k === 'style') el.style.cssText = v;
          else if (k === 'text') el.textContent = v;
          else el.setAttribute(k, v);
        }
        for (const c of kids.flat()) if (c != null) el.append(c instanceof Node ? c : String(c));
        return el;
      };
      s.root.dataset.srScene = item.scene;
    }
    return ctx;
  }

  _scopedCss(sceneId, cssText) {
    this._css = this._css || new Set();
    const key = `${sceneId}\u0000${cssText}`;
    if (this._css.has(key)) return;
    this._css.add(key);
    const st = document.createElement('style');
    st.dataset.scene = sceneId;
    st.textContent = `@scope ([data-sr-scene="${sceneId.replace(/"/g, '')}"]) {\n${cssText}\n}`;
    document.head.appendChild(st);
  }

  // ------------------------------------------------------------------------------------- seek
  seek(t) {
    const run = this.queue.then(() => this._seek(t));
    this.queue = run.catch(() => {});
    return run;
  }

  async _seek(tIn) {
    await this.ready;
    const F = this.film;
    const t = clampTime(F, tIn);
    const frame = Math.round(t * F.fps);
    this.lastT = t;
    this.frameErrors = [];
    const live = liveAt(F, t);
    const items = [...live.shots, ...live.overlays];
    const insts = [];
    for (const it of items) insts.push(await this._instance(it));
    const liveKeys = new Set(items.map((i) => i.key));
    for (const inst of this.instances.values()) if (!liveKeys.has(inst.item.key)) inst.surf.el.style.display = 'none';
    for (const inst of insts) this._render(inst, t, frame);
    if (this.assets.hasMisses()) {
      const failed = await this.assets.resolveMisses();
      for (const u of failed) this.recordError('assets', t, new Error(`frame failed to load: ${relOf(u)}`));
      this.frameErrors = this.frameErrors.filter((e) => e.src === 'assets');
      for (const inst of insts) this._render(inst, t, frame);
      this.assets.misses.clear();
    }
    this._composite(live, insts, t, frame);
    this.captions.update(t);
    this.finish.update(frame);
    this._evict(liveKeys);
    await new Promise((r) => requestAnimationFrame(() => r()));
  }

  _render(inst, t, frame) {
    const F = this.film;
    const { item, def, surf: s, ctx } = inst;
    inst.boxes = [];
    if (inst.broken) { this._drawBroken(inst); return; }
    const lt = t - item.t0;
    const t0 = realNow();
    enterScene(F.seed, item.id, frame, t);
    try {
      if (def.layer === '2d') {
        const g = s.g;
        g.setTransform(1, 0, 0, 1, 0, 0);
        g.globalAlpha = 1;
        g.globalCompositeOperation = 'source-over';
        g.filter = 'none';
        g.shadowColor = 'rgba(0,0,0,0)';
        g.imageSmoothingEnabled = !s.pixel;
        g.clearRect(0, 0, s.w, s.h);
        g.save();
        try { def.render(ctx, lt, inst.p); } finally { g.restore(); }
      } else {
        def.render(ctx, lt, inst.p);
        if (def.layer === 'three' && !ctx.three.manual) ctx.three.render();
      }
    } catch (e) {
      this.recordError(`${item.kind} ${item.id}`, t, e, item.id);
    } finally {
      leaveScene();
    }
    const ms = realNow() - t0;
    inst.stats.renders += 1;
    inst.stats.totalMs += ms;
    inst.stats.maxMs = Math.max(inst.stats.maxMs, ms);
  }

  _drawBroken(inst) {
    const s = inst.surf;
    if (!s.g) return;
    const g = s.g;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = '#3a0d14';
    g.fillRect(0, 0, s.w, s.h);
    g.fillStyle = '#ffd6dc';
    g.font = `${Math.max(8, Math.round(s.h / 24))}px monospace`;
    g.fillText(`scene error: ${inst.item.scene}`.slice(0, 80), 8, s.h / 2 - s.h / 20);
    g.fillText(String(inst.broken).slice(0, 90), 8, s.h / 2 + s.h / 20);
  }

  _txCanvas(i) {
    while (this.txPool.length <= i) {
      const c = document.createElement('canvas');
      c.className = 'sr-tx';
      c.width = this.film.w; c.height = this.film.h;
      c.style.display = 'none';
      this.shotLayer.appendChild(c);
      this.txPool.push(c);
    }
    return this.txPool[i];
  }

  _composite(live, insts, t, frame) {
    const F = this.film;
    const byKey = new Map(insts.map((i) => [i.item.key, i]));
    const order = live.shots.map((s) => byKey.get(s.key));
    // incoming shot of each transition is drawn above the outgoing one
    for (const { tr } of live.transitions) {
      const a = order.indexOf(byKey.get(tr.from.key)), b = order.indexOf(byKey.get(tr.to.key));
      if (a > b && b >= 0) { const [x] = order.splice(b, 1); order.splice(a, 0, x); }
    }
    order.forEach((inst, i) => {
      const el = inst.surf.el;
      el.style.cssText = '';
      el.style.zIndex = String(10 + i * 10);
    });
    live.overlays.forEach((o, i) => {
      const el = byKey.get(o.key).surf.el;
      el.style.cssText = '';
      el.style.zIndex = String(10 + i * 10);
    });
    let used = 0;
    live.transitions.forEach(({ tr, u }) => {
      const def = this.transitions.get(tr.type);
      const fromI = byKey.get(tr.from.key), toI = byKey.get(tr.to.key);
      if (!def || !fromI || !toI) return;
      const c = this._txCanvas(used++);
      const g = c.getContext('2d');
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.globalAlpha = 1;
      g.globalCompositeOperation = 'source-over';
      g.filter = 'none';
      g.imageSmoothingEnabled = true;
      g.clearRect(0, 0, c.width, c.height);
      const hasPixels = (i) => i.def.layer !== 'dom' && !!i.surf.canvas;
      let render = def.render;
      let canvasMode = def.kind === 'canvas';
      if (canvasMode && !(hasPixels(fromI) && hasPixels(toI)) && def.fallback) { render = def.fallback; canvasMode = false; }
      const top = Math.max(Number(fromI.surf.el.style.zIndex), Number(toI.surf.el.style.zIndex));
      c.style.display = 'block';
      c.style.zIndex = String(top + 5);
      if (canvasMode) {
        fromI.surf.el.style.visibility = 'hidden';
        toI.surf.el.style.visibility = 'hidden';
      }
      const key = `${tr.index}`;
      if (!this.txCache.has(key)) this.txCache.set(key, {});
      const seed = mixSeed(F.seed, 'tx', tr.index);
      const tx = {
        g, w: F.w, h: F.h, t, frame, seed, u,
        from: hasPixels(fromI) ? fromI.surf.canvas : null,
        to: hasPixels(toI) ? toI.surf.canvas : null,
        fromEl: fromI.surf.el, toEl: toI.surf.el,
        rng: makeRng(mixSeed(seed, frame)),
        ease, noise2: this.noise.noise2, fbm2: this.noise.fbm2,
        cache: this.txCache.get(key),
        draw(src, o = {}) {
          if (!src) return;
          g.save();
          if (o.alpha != null) g.globalAlpha *= o.alpha;
          g.imageSmoothingEnabled = o.smooth ?? !(src.dataset && src.dataset.pixel === '1');
          g.drawImage(src, o.x || 0, o.y || 0, o.w ?? F.w, o.h ?? F.h);
          g.restore();
        },
      };
      enterScene(F.seed, `tx:${tr.index}`, frame, t);
      try {
        g.save();
        render(tx, Math.max(0, Math.min(1, u)), tr.params);
        g.restore();
      } catch (e) {
        this.recordError(`transition ${tr.index} (${tr.type})`, t, e, tr.to.id);
      } finally {
        leaveScene();
      }
    });
    for (let i = used; i < this.txPool.length; i++) this.txPool[i].style.display = 'none';
  }

  // --------------------------------------------------------------------------------------- QA
  async qa(t) {
    const F = this.film;
    if (t != null && (this.lastT == null || Math.abs(clampTime(F, t) - this.lastT) > 1e-9)) await this.seek(t);
    const live = liveAt(F, this.lastT ?? 0);
    const boxes = [];
    for (const it of [...live.shots, ...live.overlays]) {
      const inst = this.instances.get(it.key);
      if (!inst) continue;
      if (inst.def.layer === 'dom') boxes.push(...domTextBoxes(inst.surf.root, this.stage, { id: it.id, kind: it.kind }));
      else boxes.push(...inst.boxes);
    }
    boxes.push(...domTextBoxes(this.captions.root, this.stage, { id: 'captions', kind: 'caption' }));
    const skip = new Set();
    for (const { tr } of live.transitions) { skip.add(`${tr.from.id}|${tr.to.id}`); skip.add(`${tr.to.id}|${tr.from.id}`); }
    const k = Math.min(F.w, F.h) / 1080;
    const minText = Number(F.qa.min_text_px || 22) * k;
    const issues = checkBoxes(boxes, { w: F.w, h: F.h, safe: F.safe, minText, pairsToSkip: skip });
    return [...this.frameErrors.map(({ src, ...e }) => e), ...issues];
  }

  shots() {
    const F = this.film;
    if (!F) return [];
    return [...F.shots, ...F.overlays].map((it) => {
      const inst = this.instances.get(it.key);
      const st = inst ? inst.stats : null;
      return {
        id: it.id, kind: it.kind, scene: it.scene, layer: inst ? inst.def.layer : (this.scenes.get(it.scene) || {}).layer || null,
        t0: it.t0, t1: it.t1, res: it.res, z: it.z, cached: !!inst, broken: inst ? inst.broken : null,
        setup_ms: st ? +st.setupMs.toFixed(2) : null, renders: st ? st.renders : 0,
        render_ms_avg: st && st.renders ? +(st.totalMs / st.renders).toFixed(2) : null,
        render_ms_max: st ? +st.maxMs.toFixed(2) : null,
      };
    });
  }

  /** The window.__sr object (SDK §6). */
  get api() {
    if (this._api) return this._api;
    const rt = this;
    this._api = {
      ready: this.ready,
      dur: 0, fps: 30, w: 0, h: 0, title: '',
      cues: [],
      errors: this.errors,
      warnings: this.warnings,
      seek: (t) => rt.seek(t),
      qa: (t) => rt.qa(t),
      shots: () => rt.shots(),
      purge: () => rt.purge(),
      scenes: () => [...rt.scenes.entries()].map(([id, d]) => ({ id, layer: d.layer, describe: d.describe || '', params: d.params || {} })),
      transitions: () => [...rt.transitions.entries()].map(([id, d]) => ({ id, kind: d.kind })),
      kits: () => [...rt.kits.keys()],
    };
    return this._api;
  }
}
