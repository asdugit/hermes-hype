// Product media for scenes: assets/manifest.json entries -> ctx.asset(name) handles.
// Images and the first frame (or poster) of every sequence are decoded before __sr.ready resolves.
// Sequence frames decode on demand: a render that touches an undecoded frame is re-run once the
// frame is decoded (render is pure, so re-running is safe), and the frames just ahead are prefetched.

const FRAME_BUDGET = 72;    // decoded sequence frames kept across all assets (~150 MB at 960x540)
const PREFETCH_AHEAD = 6;

function loadImage(url) {
  const img = new Image();
  img.decoding = 'async';
  img.src = url;
  return img.decode().then(() => img, () => {
    throw new Error(`image failed to load: ${url.replace(/^.*?\/\/[^/]+\/[^/]+\//, '')}`);
  });
}

/** Expand a printf-style frame pattern ("assets/car/%06d.jpg") for 1-based frame number n. */
export function framePath(pattern, n) {
  return pattern.replace(/%0?(\d*)d/, (_, w) => String(n).padStart(Number(w || 0), '0'));
}

/** Frame index (0-based) for asset-local time t. loop wraps, otherwise clamps. */
export function frameIndex(t, fps, count, loop = true) {
  if (!count) return 0;
  let i = Math.floor((Number.isFinite(t) ? t : 0) * fps + 1e-6);
  if (loop) i = ((i % count) + count) % count;
  else i = Math.max(0, Math.min(count - 1, i));
  return i;
}

export class AssetStore {
  /** @param manifest {name: entry} (SDK §1) ; @param resolve (relPath) -> URL */
  constructor(manifest, resolve) {
    this.manifest = manifest || {};
    this.resolve = resolve;
    this.first = new Map();      // name -> decoded image (image asset or first frame/poster)
    this.frames = new Map();     // url -> decoded image (LRU order)
    this.pending = new Map();    // url -> Promise
    this.misses = new Set();     // urls requested by a render but not decoded yet
    this.handles = new Map();
  }

  names() { return Object.keys(this.manifest); }

  has(name) { return Object.prototype.hasOwnProperty.call(this.manifest, name); }

  /** Decode every image and every sequence's first frame/poster; throws a clear Error on failure. */
  async preloadAll() {
    const jobs = [];
    for (const [name, e] of Object.entries(this.manifest)) {
      jobs.push(this._loadFirst(name, e, false));
      if (e.cutout) jobs.push(this._loadFirst(name, e.cutout, true));
    }
    await Promise.all(jobs);
  }

  async _loadFirst(name, e, cutout) {
    const key = cutout ? `${name}#cutout` : name;
    let rel;
    if (e.type === 'image' || (!e.pattern && e.path)) rel = e.path;
    else if (e.pattern) rel = e.poster || framePath(e.pattern, 1);
    if (!rel) throw new Error(`asset '${name}'${cutout ? ' cutout' : ''}: manifest entry needs "path" (image) or "pattern" (frames)`);
    try {
      this.first.set(key, await loadImage(this.resolve(rel)));
    } catch (err) {
      throw new Error(`asset '${name}'${cutout ? ' cutout' : ''}: ${rel} failed to load (${err.message})`);
    }
  }

  /** The ctx.asset(name) handle (SDK §4). */
  handle(name) {
    if (this.handles.has(name)) return this.handles.get(name);
    if (!this.has(name)) {
      throw new Error(`unknown asset '${name}' (manifest has: ${this.names().join(', ') || 'none'})`);
    }
    const h = this._makeHandle(name, this.manifest[name], false);
    if (this.manifest[name].cutout) h.cutout = this._makeHandle(name, { ...this.manifest[name], ...this.manifest[name].cutout }, true);
    this.handles.set(name, h);
    return h;
  }

  _makeHandle(name, e, cutout) {
    const key = cutout ? `${name}#cutout` : name;
    const store = this;
    const isSeq = !!e.pattern && e.type !== 'image';
    const count = isSeq ? Number(e.count || 1) : 1;
    const fps = Number(e.fps || 30);
    const first = () => store.first.get(key);
    return {
      name,
      type: isSeq ? 'frames' : 'image',
      w: Number(e.w || (first() && first().naturalWidth) || 0),
      h: Number(e.h || (first() && first().naturalHeight) || 0),
      fps: isSeq ? fps : 0,
      count,
      dur: isSeq ? Number(e.dur || count / fps) : 0,
      get image() { return first(); },
      /** Decoded frame for asset-local time t ({loop: true} wraps; false clamps). */
      frame(t = 0, opts = {}) {
        if (!isSeq) return first();
        const i = frameIndex(t, fps, count, opts.loop !== false);
        return store._frame(e.pattern, i, count, first());
      },
      /** Decoded frame by 0-based index (clamped). */
      frameAt(i) {
        if (!isSeq) return first();
        return store._frame(e.pattern, Math.max(0, Math.min(count - 1, Math.floor(i))), count, first());
      },
    };
  }

  _frame(pattern, i, count, fallback) {
    const url = this.resolve(framePath(pattern, i + 1));
    const hit = this.frames.get(url);
    if (hit) {
      this.frames.delete(url);
      this.frames.set(url, hit);
      this._prefetch(pattern, i, count);
      return hit;
    }
    this.misses.add(url);
    this._prefetch(pattern, i, count);
    return this._nearest(pattern, i, count) || fallback;
  }

  _nearest(pattern, i, count) {
    for (let d = 1; d < 8; d++) {
      for (const j of [i - d, i + d]) {
        if (j < 0 || j >= count) continue;
        const hit = this.frames.get(this.resolve(framePath(pattern, j + 1)));
        if (hit) return hit;
      }
    }
    return null;
  }

  _prefetch(pattern, i, count) {
    for (let k = 1; k <= PREFETCH_AHEAD; k++) {
      const j = i + k;
      if (j >= count) break;
      const url = this.resolve(framePath(pattern, j + 1));
      if (!this.frames.has(url)) this._fetch(url).catch(() => {});
    }
  }

  _fetch(url) {
    if (this.pending.has(url)) return this.pending.get(url);
    const p = loadImage(url).then((img) => {
      this.frames.set(url, img);
      while (this.frames.size > FRAME_BUDGET) {
        const oldest = this.frames.keys().next().value;
        this.frames.delete(oldest);
      }
      return img;
    }).finally(() => this.pending.delete(url));
    this.pending.set(url, p);
    return p;
  }

  /** True if the last render(s) asked for frames that were not decoded. */
  hasMisses() { return this.misses.size > 0; }

  /** Decode every missed frame; returns the list of URLs that failed. */
  async resolveMisses() {
    const urls = [...this.misses];
    this.misses.clear();
    const failed = [];
    await Promise.all(urls.map((u) => this._fetch(u).catch(() => failed.push(u))));
    return failed;
  }
}
