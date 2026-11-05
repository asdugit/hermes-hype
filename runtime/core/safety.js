// Determinism safety net (SDK §6): while scene code runs, Math.random is a PRNG reseeded from
// (film seed, shot id, frame index) and Date / performance.now are frozen to film time.
// The runtime keeps the real clock for its own timing statistics (realNow).
import { mixSeed, mulberry32 } from './rand.js';

const RealDate = Date;
const realPerfNow = performance.now.bind(performance);
const realRandom = Math.random;
/** Fixed wall-clock epoch for film time 0 (2026-01-01T00:00:00Z) so dates in scenes never vary. */
export const FILM_EPOCH_MS = 1767225600000;

let filmMs = 0;
let rand = mulberry32(1);
let installed = false;

/** Real high-resolution clock for runtime statistics (never exposed to scenes). */
export const realNow = () => realPerfNow();

/** Install the patched globals once (idempotent). */
export function installSafetyNet() {
  if (installed) return;
  installed = true;
  Math.random = () => rand();
  class FilmDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(FILM_EPOCH_MS + filmMs);
      else super(...args);
    }
    static now() { return FILM_EPOCH_MS + filmMs; }
  }
  globalThis.Date = FilmDate;
  try {
    Object.defineProperty(performance, 'now', { value: () => filmMs, configurable: true, writable: true });
  } catch (_) { /* some engines lock performance.now; lint still rejects it */ }
}

/** Enter scene code for a given film time and frame: reseed and freeze. */
export function enterScene(filmSeed, shotId, frameIndex, tSeconds) {
  filmMs = tSeconds * 1000;
  rand = mulberry32(mixSeed(filmSeed, shotId, frameIndex));
}

/** Between scene calls Math.random stays seeded (fixed stream) so library code stays deterministic too. */
export function leaveScene() {
  rand = mulberry32(0x5eed);
}

/** The untouched Math.random (diagnostics only). */
export const unsafeRandom = realRandom;
