// cues.js — sound intents used by the pixel kit -> SFX names that exist in assets/audio/sfx/sfx.json.
// Scenes speak in intents (cue(t, 'menu_move')); this table is the only place that knows file names, so
// when the SFX kit gains dedicated sounds (see MISSING) only the right-hand side changes.

/** intent -> [sfx name, gain_db] */
export const SFX = {
  blip: ['blip', -6],            // typewriter text (every 4th char)
  emote: ['blip', 0],
  footstep: ['click', -12],      // MISSING dedicated 'footstep'
  menu_open: ['pop', -2],
  menu_move: ['blip', 0],
  menu_select: ['coin', 0],      // two-note up confirm
  buy: ['level_up', -2],         // MISSING dedicated 'buy' (ka-ching chiptune)
  slash: ['whoosh_short', -2],   // MISSING dedicated 'sword_slash'
  throw: ['whoosh_short', 0],    // MISSING 'blade_spin'
  hit: ['hit', 0],
  damage: ['error', -6],         // MISSING 8-bit 'damage' buzz
  door_rumble: ['sub_drop', -2], // MISSING 'door_rumble' (stone grind)
  chains: ['glitch', -4],        // MISSING 'chain_break'
  door_open: ['whoosh_long', -2],
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
export const MISSING = ['footstep', 'sword_slash', 'blade_spin', 'damage', 'door_rumble', 'chain_break', 'buy', 'menu_confirm', 'petal_burst'];

/** Build an SDK cue {t, sfx, gain_db} from an intent. */
export function cue(t, intent, extraDb = 0) {
  const [sfx, db] = SFX[intent] || [intent, 0];
  return { t: Math.max(0, Math.round(t * 1000) / 1000), sfx, gain_db: db + extraDb };
}
