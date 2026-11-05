// film.json normalisation and timeline queries (which shots/overlays/transitions are live at t).
// Python (showreel_core/film/schema.py) validates precisely; this module only fills defaults and
// throws short messages for structural problems so __sr.ready can reject clearly.

const DEFAULT_SAFE = {
  '16:9': { l: 96, r: 96, t: 64, b: 120 },
  '9:16': { l: 120, r: 120, t: 220, b: 420 },
  '1:1': { l: 96, r: 96, t: 96, b: 140 },
};

export function aspectOf(w, h) {
  if (w > h) return '16:9';
  if (h > w) return '9:16';
  return '1:1';
}

/** Default safe area for a film size (reference values are at a 1080 px short side). */
export function defaultSafe(w, h) {
  const k = Math.min(w, h) / 1080;
  const s = DEFAULT_SAFE[aspectOf(w, h)];
  return { l: Math.round(s.l * k), r: Math.round(s.r * k), t: Math.round(s.t * k), b: Math.round(s.b * k) };
}

function num(v, what) {
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error(`film.json: ${what} must be a number (got ${JSON.stringify(v)})`);
  return n;
}

function normItem(raw, i, kind, film) {
  const where = `${kind}[${i}]`;
  if (!raw || typeof raw !== 'object') throw new Error(`film.json: ${where} must be an object`);
  const id = String(raw.id ?? (kind === 'overlays' ? `overlay${i}` : `shot${i}`));
  const scene = raw.scene ?? raw.type;
  if (typeof scene !== 'string' || !scene) throw new Error(`film.json: ${where}.scene is required`);
  const t0 = num(raw.t0, `${where}.t0`), t1 = num(raw.t1, `${where}.t1`);
  if (!(t1 > t0)) throw new Error(`film.json: ${where}: t1 (${t1}) must be greater than t0 (${t0})`);
  let res = raw.res;
  if (res == null) res = [film.w, film.h];
  if (!Array.isArray(res) || res.length !== 2) throw new Error(`film.json: ${where}.res must be [w, h] or null`);
  res = [Math.max(1, Math.round(num(res[0], `${where}.res[0]`))), Math.max(1, Math.round(num(res[1], `${where}.res[1]`)))];
  return {
    kind: kind === 'overlays' ? 'overlay' : 'shot',
    key: `${kind === 'overlays' ? 'o' : 's'}:${id}`,
    id, scene, t0, t1, dur: t1 - t0, res,
    upscale: raw.upscale === 'smooth' ? 'smooth' : 'pixel',
    params: raw.params && typeof raw.params === 'object' ? raw.params : {},
    z: raw.z == null ? null : num(raw.z, `${where}.z`),
    order: i,
  };
}

/** Fill defaults and derive helper fields. Throws Error(message) on structural problems. */
export function normalizeFilm(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('film.json: not an object');
  const size = Array.isArray(raw.size) ? raw.size : [1920, 1080];
  const film = {
    raw,
    version: raw.version ?? 1,
    fps: num(raw.fps ?? 30, 'fps'),
    w: Math.round(num(size[0], 'size[0]')),
    h: Math.round(num(size[1], 'size[1]')),
    dur: num(raw.dur, 'dur'),
    seed: Math.round(num(raw.seed ?? 0, 'seed')),
    title: String(raw.title ?? ''),
    background: String(raw.background ?? '#000'),
    fonts: Array.isArray(raw.fonts) ? raw.fonts : [],
    assets: raw.assets && typeof raw.assets === 'object' ? raw.assets : {},
    finish: raw.finish && typeof raw.finish === 'object' ? raw.finish : {},
    cues: Array.isArray(raw.cues) ? raw.cues : [],
    captions: Array.isArray(raw.captions) ? raw.captions : [],
    captionStyle: raw.caption_style && typeof raw.caption_style === 'object' ? raw.caption_style : {},
    qa: raw.qa && typeof raw.qa === 'object' ? raw.qa : {},
  };
  if (!(film.dur > 0)) throw new Error('film.json: dur must be > 0');
  film.aspect = aspectOf(film.w, film.h);
  film.safe = raw.safe && typeof raw.safe === 'object'
    ? { l: num(raw.safe.l ?? 0, 'safe.l'), r: num(raw.safe.r ?? 0, 'safe.r'), t: num(raw.safe.t ?? 0, 'safe.t'), b: num(raw.safe.b ?? 0, 'safe.b') }
    : defaultSafe(film.w, film.h);
  if (!Array.isArray(raw.shots) || raw.shots.length === 0) throw new Error('film.json: shots must be a non-empty array');
  film.shots = raw.shots.map((s, i) => normItem(s, i, 'shots', film));
  film.overlays = (Array.isArray(raw.overlays) ? raw.overlays : []).map((s, i) => normItem(s, i, 'overlays', film));
  const ids = new Set();
  for (const s of film.shots) {
    if (ids.has(s.id)) throw new Error(`film.json: duplicate shot id '${s.id}'`);
    ids.add(s.id);
  }
  // default z: by start time (later shots on top), stable by declaration order
  const byStart = [...film.shots].sort((a, b) => a.t0 - b.t0 || a.order - b.order);
  byStart.forEach((s, k) => { if (s.z == null) s.z = k; });
  film.overlays.forEach((o, k) => { if (o.z == null) o.z = k; });
  const byId = new Map(film.shots.map((s) => [s.id, s]));
  film.byId = byId;
  film.transitions = (Array.isArray(raw.transitions) ? raw.transitions : []).map((tr, i) => {
    const where = `transitions[${i}]`;
    const from = byId.get(tr.from), to = byId.get(tr.to);
    if (!from) throw new Error(`film.json: ${where}.from '${tr.from}' is not a shot id`);
    if (!to) throw new Error(`film.json: ${where}.to '${tr.to}' is not a shot id`);
    const type = String(tr.type || 'cut');
    const dur = Math.max(0, num(tr.dur ?? 0, `${where}.dur`));
    const t = tr.t == null ? Math.max(0, to.t0 - dur / 2) : num(tr.t, `${where}.t`);
    return { index: i, from, to, type, t, dur, t1: t + dur, params: tr.params && typeof tr.params === 'object' ? tr.params : {} };
  });
  return film;
}

/** Clamp a seek time into [0, dur) (the last frame of a film is at dur - 1/fps). */
export function clampTime(film, t) {
  const x = Number(t);
  if (!Number.isFinite(x) || x < 0) return 0;
  return x >= film.dur ? Math.max(0, film.dur - 1e-6) : x;
}

/**
 * What is on screen at film time t:
 * {shots: [shot...] (back to front), overlays: [...], transitions: [{tr, u}]}.
 * A transition keeps both its shots live for its whole window; once it has finished the outgoing shot
 * is off, and before it starts the incoming shot is off (so shots may overlap their neighbours freely).
 */
export function liveAt(film, t) {
  const on = new Set(film.shots.filter((s) => t >= s.t0 && t < s.t1));
  const trs = [];
  for (const tr of film.transitions) {
    if (tr.dur > 0 && t >= tr.t && t < tr.t1) {
      on.add(tr.from); on.add(tr.to);
      trs.push({ tr, u: (t - tr.t) / tr.dur });
    }
  }
  for (const tr of film.transitions) {
    if (tr.dur > 0 && t >= tr.t && t < tr.t1) continue;
    if (t >= tr.t1 && on.has(tr.from) && tr.from !== tr.to && !trs.some((x) => x.tr.from === tr.from || x.tr.to === tr.from)) on.delete(tr.from);
    if (t < tr.t && on.has(tr.to) && !trs.some((x) => x.tr.to === tr.to || x.tr.from === tr.to)) on.delete(tr.to);
  }
  const shots = [...on].sort((a, b) => a.z - b.z || a.t0 - b.t0 || a.order - b.order);
  const overlays = film.overlays.filter((o) => t >= o.t0 && t < o.t1).sort((a, b) => a.z - b.z || a.order - b.order);
  return { shots, overlays, transitions: trs };
}
