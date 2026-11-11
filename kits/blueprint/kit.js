// Hype kit "blueprint" (signature style): the session as an engineering drawing. Cyanotype sheet, zoned border,
// title block that stamps its REV, white object lines plotted on by a pen at plotter cadence, cyan dimensions and
// leaders, redline reserved for revisions (clouds, deltas, strikes). Registers the 'blueprint' theme (replaces the
// kits/base starter), kit:blueprint/<TYPE> for all 15 storyboard types and the sheet-slide / plot-wipe transitions.

import { sr, registerTheme } from '../base/kit.js';
import { BLUEPRINT_CSS } from './css.js';
import * as draw from './draw.js';
import * as plot from './plot.js';
import * as sheet from './sheet.js';
import * as media from './media.js';
import * as parts from './parts.js';
import './scenes-type.js';
import './scenes-list.js';
import './scenes-media.js';
import { TRANSITIONS } from './transitions.js';

registerTheme('blueprint', BLUEPRINT_CSS);

export const OVERRIDES = ['HOOK', 'TITLE', 'PROBLEM', 'PLAN', 'CODE', 'DIFF', 'TERMINAL', 'MONTAGE', 'SCREEN', 'STATS',
  'BEFORE_AFTER', 'CALLOUT', 'END', 'FEATURE', 'SCROLL'];
export { draw, plot, sheet, media, parts, TRANSITIONS };

if (sr && typeof sr.defineKit === 'function') {
  sr.defineKit('blueprint', { draw, plot, sheet, media, parts, OVERRIDES, TRANSITIONS, css: BLUEPRINT_CSS });
}
