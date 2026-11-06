// Showreel kit "terminal" (signature style): the session replayed on a single-phosphor CRT. Box-drawn panes,
// the real commands typed at a human cadence, verbatim output at line rate, odometer stats, block-letter logo
// builds, product captures that resolve from phosphor dither to the real image, channel-switch cuts.
// Registers the 'terminal' theme (amber P3 tokens; replaces the kits/base starter) and kit:terminal/<TYPE> for all
// 15 storyboard types, plus kit:terminal/channel-switch and kit:terminal/persist transitions.

import { sr, registerTheme } from '../base/kit.js';
import { TERMINAL_CSS } from './css.js';
import * as crt from './crt.js';
import * as pane from './pane.js';
import * as phosphor from './phosphor.js';
import * as tube from './tube.js';
import './scenes-panes.js';
import './scenes-type.js';
import './scenes-media.js';
import { TRANSITIONS } from './transitions.js';

registerTheme('terminal', TERMINAL_CSS);

export const OVERRIDES = ['HOOK', 'TITLE', 'PROBLEM', 'PLAN', 'CODE', 'DIFF', 'TERMINAL', 'MONTAGE', 'SCREEN', 'STATS',
  'BEFORE_AFTER', 'CALLOUT', 'END', 'FEATURE', 'SCROLL'];
export { crt, pane, phosphor, tube, TRANSITIONS };

if (sr && typeof sr.defineKit === 'function') {
  sr.defineKit('terminal', { crt, pane, phosphor, tube, OVERRIDES, TRANSITIONS, css: TERMINAL_CSS });
}
