// nature kit · time-of-day presets and palettes (sRGB hex; converted to linear in the shaders' uniforms).
// Colours sampled from the user's references (research/ref-flowerfield.md): AoT "paths" sunset, the Sotiya
// pastel meadow, and the magenta→cyan "aesthetic" edit. Sun az/el in degrees (az 0 = straight ahead, + = right).

const FLOWERS = {
  pink: '#F4A6C0', rose: '#E98AA6', yellow: '#F2D35A', butter: '#F7E08A', white: '#F6F1E2', cream: '#F3EFD9',
  lilac: '#B7A2E0', lupine: '#7A5BC2', peach: '#F6B48F', coral: '#F08F7E', blue: '#8EA2E8',
};

export const PRESETS = {
  sunset: {
    sky: [[0, '#FFF0D2'], [2.5, '#FCDDB2'], [6, '#F7C08F'], [11, '#EEA9AE'], [17, '#C99BC4'], [25, '#9C8CC2'], [45, '#6A68A6']],
    sun: { az: -6, el: 5.2, color: '#FFE9BE', glow: '#FFC487', size: 0.9, power: 7.0, halo: 1.0 },
    clouds: { lit: '#FFD7A8', mid: '#EBA6B4', shadow: '#7E70AC', rim: '#FFF3DA', cover: 0.55, band: [4, 42], lowBand: [1.0, 5.0] },
    mountains: [{ col: '#B89BC8', el: [2.2, 6.4] }, { col: '#9A7DB6', el: [1.2, 4.2] }, { col: '#7C65A0', el: [0.5, 2.4] }, { col: '#7F6E8E', el: [0.25, 1.2] }],
    haze: '#F4CDBE', fogDensity: 0.0040,
    grass: { shadow: '#43583A', base: '#6A8746', lit: '#B9BE66', tip: '#E6D892' },
    light: '#FFD9B0', ambient: '#AE9CC8', exposure: 1.0, backlight: 1.0, petalTint: 0.35,
    flowers: { white: 5, pink: 4, lilac: 3, yellow: 3, lupine: 2, rose: 1 },
    petals: ['pink', 'yellow', 'peach', 'white', 'pink'],
    bloom: 0.85, rays: 0.55, mist: 0.07, flare: 0.6, fireflies: 0, stars: 0,
  },
  golden: {
    sky: [[0, '#FFF0CC'], [4, '#FFDFA6'], [10, '#F7D7AE'], [20, '#D6D8DE'], [34, '#A9C4E2'], [55, '#86AEDC'], [80, '#6A97D0']],
    sun: { az: -14, el: 8.5, color: '#FFEFC4', glow: '#FFD48E', size: 1.0, power: 7.5, halo: 0.9 },
    clouds: { lit: '#FFF0D0', mid: '#F2D5B4', shadow: '#94A0C4', rim: '#FFF8E6', cover: 0.44, band: [8, 34], lowBand: [1.5, 6] },
    mountains: [{ col: '#A9B3CF', el: [2.0, 5.6] }, { col: '#8F9AC0', el: [1.2, 3.4] }, { col: '#6F7E9C', el: [0.4, 1.7] }, { col: '#7E8A84', el: [0.1, 0.9] }],
    haze: '#F4E0BC', fogDensity: 0.0036,
    grass: { shadow: '#3F5634', base: '#6F8C3F', lit: '#C3C25A', tip: '#EFD883' },
    light: '#FFE2AE', ambient: '#9FB2D3', exposure: 1.0, backlight: 0.7,
    flowers: { white: 4, yellow: 4, butter: 2, pink: 2, peach: 2, lilac: 1, lupine: 1 },
    petals: ['yellow', 'white', 'peach', 'pink'],
    bloom: 0.75, rays: 0.5, mist: 0.12, fireflies: 0, stars: 0,
  },
  dawn: {
    sky: [[0, '#FCE6D9'], [4, '#F8D4D8'], [12, '#E8C6E2'], [24, '#C6C3EA'], [42, '#A2B1E2'], [70, '#7F96D4']],
    sun: { az: -24, el: 2.4, color: '#FFE9DC', glow: '#FFC9C0', size: 0.85, power: 6.0, halo: 0.9 },
    clouds: { lit: '#FFDDE2', mid: '#E9BCD6', shadow: '#8D92C8', rim: '#FFF2F0', cover: 0.42, band: [6, 28], lowBand: [1.2, 5] },
    mountains: [{ col: '#BDB6DA', el: [2.0, 5.8] }, { col: '#A19CCB', el: [1.2, 3.6] }, { col: '#827FB0', el: [0.4, 1.8] }, { col: '#8A88A6', el: [0.1, 0.9] }],
    haze: '#F2D9E4', fogDensity: 0.0045,
    grass: { shadow: '#3C4E4A', base: '#5F8466', lit: '#A9C08A', tip: '#DCD9A8' },
    light: '#FFE1DA', ambient: '#A9AEDB', exposure: 1.02, backlight: 0.8,
    flowers: { white: 4, cream: 2, pink: 3, lilac: 3, lupine: 2, yellow: 1, blue: 1 },
    petals: ['pink', 'white', 'lilac', 'pink'],
    bloom: 0.8, rays: 0.45, mist: 0.18, fireflies: 0, stars: 0,
  },
  pastel: {
    sky: [[0, '#F7ECF2'], [5, '#F2D6E4'], [14, '#E4BCD8'], [28, '#CDB8E6'], [46, '#AEB0E0'], [75, '#959DD6']],
    sun: { az: -32, el: 26, color: '#FFF6EE', glow: '#FFE4EE', size: 1.2, power: 4.0, halo: 1.2 },
    clouds: { lit: '#FFF6FA', mid: '#EBCBE2', shadow: '#B5A2D8', rim: '#FFFFFF', cover: 0.56, band: [5, 40], lowBand: [1.0, 6] },
    mountains: [{ col: '#A994CF', el: [2.4, 6.6] }, { col: '#8B74BC', el: [1.4, 4.2] }, { col: '#6E5A9E', el: [0.5, 2.1] }, { col: '#7C7FA6', el: [0.1, 0.9] }],
    haze: '#EBD6EC', fogDensity: 0.004,
    grass: { shadow: '#46604A', base: '#76A06A', lit: '#B9D08C', tip: '#E8E6B0' },
    light: '#FFF1EC', ambient: '#C2B3E2', exposure: 1.0, backlight: 0.45,
    flowers: { white: 5, cream: 3, yellow: 3, lilac: 3, lupine: 2, pink: 2 },
    petals: ['pink', 'yellow', 'peach', 'pink', 'white'],
    bloom: 0.7, rays: 0.25, mist: 0.2, fireflies: 0, stars: 0,
  },
  dream: {
    sky: [[0, '#FBD3EA'], [5, '#F3B6E0'], [14, '#D6A2EA'], [26, '#B693E8'], [44, '#7FA6E2'], [72, '#3DB8D6']],
    sun: { az: -30, el: 22, color: '#FFF8F2', glow: '#FFD0EE', size: 1.3, power: 6.0, halo: 1.5 },
    clouds: { lit: '#FFF1FA', mid: '#E9B9E6', shadow: '#8E86D0', rim: '#FFFFFF', cover: 0.46, band: [6, 36], lowBand: [1.2, 6] },
    mountains: [{ col: '#B69BDB', el: [2.2, 6.0] }, { col: '#957ACB', el: [1.3, 3.8] }, { col: '#5E4E8E', el: [0.4, 2.0] }, { col: '#6A5E8C', el: [0.1, 0.9] }],
    haze: '#F2C8EA', fogDensity: 0.0045,
    grass: { shadow: '#26363A', base: '#4D6F5A', lit: '#9CC39A', tip: '#EAF1C8' },
    light: '#FFE9F6', ambient: '#B0A0E6', exposure: 1.0, backlight: 0.9,
    flowers: { white: 5, cream: 2, yellow: 3, pink: 3, lilac: 2 },
    petals: ['pink', 'white', 'pink', 'lilac', 'yellow'],
    bloom: 1.0, rays: 0.4, mist: 0.22, ca: 1.6, fireflies: 0, stars: 0,
  },
  night: {
    sky: [[0, '#3A3B72'], [4, '#2D3166'], [12, '#22275A'], [26, '#181C46'], [45, '#10132F'], [75, '#090B20']],
    sun: { az: 18, el: 24, color: '#E2E9FF', glow: '#8E9BE0', size: 0.7, power: 3.5, halo: 0.6, moon: true },
    clouds: { lit: '#A8B0E0', mid: '#4A4F86', shadow: '#22264E', rim: '#DCE2FF', cover: 0.34, band: [8, 34], lowBand: [1.5, 6] },
    mountains: [{ col: '#2B2E5E', el: [2.0, 5.6] }, { col: '#22254E', el: [1.2, 3.4] }, { col: '#191B3C', el: [0.4, 1.8] }, { col: '#161A30', el: [0.1, 0.9] }],
    haze: '#3A3D74', fogDensity: 0.0048,
    grass: { shadow: '#10181E', base: '#1E3236', lit: '#3D5C5C', tip: '#6B8A80' },
    light: '#AFC0FF', ambient: '#3A4282', exposure: 1.0, backlight: 0.5,
    flowers: { white: 4, lilac: 3, blue: 2, cream: 1 },
    petals: ['white', 'lilac'],
    bloom: 1.0, rays: 0.0, mist: 0.14, fireflies: 140, stars: 1, productExposure: 0.5,
  },
};
PRESETS['golden-hour'] = PRESETS.golden;

export { FLOWERS };

/** Resolve a preset by name (or a preset object with overrides). Unknown names fall back to sunset. */
export function resolvePreset(time, overrides = null) {
  const base = typeof time === 'object' && time ? time : (PRESETS[time] || PRESETS.sunset);
  if (!overrides) return base;
  return { ...base, ...overrides };
}

/** '#RRGGBB' → [r,g,b] in 0..1, sRGB (no conversion). */
export function hex3(h) {
  const n = parseInt(String(h).replace('#', ''), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}
/** sRGB → linear for one channel. */
export const toLin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
/** '#RRGGBB' → linear [r,g,b]. */
export const lin3 = (h) => hex3(h).map(toLin);
