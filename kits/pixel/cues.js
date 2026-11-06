// cues.js — sound intents used by the pixel kit -> SFX names that exist in assets/audio/sfx/sfx.json.
// Scenes speak in intents (cue(t, 'menu_move')); this table is the only place that knows file names, so
// when the SFX kit gains dedicated sounds (see MISSING) only the right-hand side changes.

/** intent -> [sfx name, gain_db] */
export const SFX = {
  blip: ['blip', -6],            // typewriter text (every 4th char)
  emote: ['blip', 0],
  footstep: ['footstep', 0],
  menu_open: ['pop', -2],
  menu_move: ['menu_move', 0],
  menu_select: ['menu_confirm', 0],
  buy: ['buy', 0],               // chiptune ka-ching
  slash: ['sword_slash', 0],
  throw: ['blade_spin', 0],
  charge: ['power_up', -4],      // boss winds up (engine rev + glow)
  hit: ['hit', 0],
  damage: ['damage', 0],         // 8-bit damage buzz
  door_rumble: ['door_rumble', 0],
  chains: ['chain_break', 0],
  door_open: ['whoosh_long', -2],
  encounter: ['glitch', -4],      // battle-swirl flash (MISSING a dedicated encounter sting)
  petal_burst: ['petal_burst', 0],
  bloom_whoosh: ['switch_whoosh', -2],
  boss_appear: ['impact', -3],
  coin: ['coin', 0],
  item_get: ['level_up', 0],
  level_up: ['level_up', 0],
  power_up: ['power_up', 0],
  press_start: ['power_up', 0],
  tick: ['blip', -8],
  whoosh: ['whoosh_short', -2],
  error: ['error', 0],
  stamp: ['stamp', -2],
};
/** Intents still mapped to stand-ins (names requested from the SFX kit). */
export const MISSING = ['encounter'];

/** Transition cue {u (0..1 of the window), sfx, gain_db} from an intent (SDK transition cues()). */
export function txCue(u, intent, extraDb = 0) {
  const [sfx, db] = SFX[intent] || [intent, 0];
  return { u, sfx, gain_db: db + extraDb };
}

/** Build an SDK cue {t, sfx, gain_db} from an intent. */
export function cue(t, intent, extraDb = 0) {
  const [sfx, db] = SFX[intent] || [intent, 0];
  return { t: Math.max(0, Math.round(t * 1000) / 1000), sfx, gain_db: db + extraDb };
}
