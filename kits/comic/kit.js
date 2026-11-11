// Auteur kit "comic" (style "comic"): the session as an issue of a motion comic. Every Quick-mode scene type is a
// page of ink-bordered panels with true halftone, sunbursts, speech balloons, captions and onomatopoeia; the camera
// moves panel to panel. Registers the "comic" theme (replaces the kits/base starter), the kit:comic/* scenes and
// the kit:comic/* transitions (page-turn, splat-iris, panel-glide).

import { sr, registerTheme } from '../base/kit.js';
import { COMIC_CSS } from './css.js';
import * as art from './lib/art.js';
import * as letter from './lib/letter.js';
import * as page from './lib/page.js';
import * as print from './lib/print.js';
import { TRANSITIONS } from './lib/transitions.js';
import './scenes-story.js';
import './scenes-code.js';
import './scenes-media.js';

registerTheme('comic', COMIC_CSS);

export const OVERRIDES = ['HOOK', 'TITLE', 'PROBLEM', 'PLAN', 'CODE', 'DIFF', 'TERMINAL', 'MONTAGE', 'SCREEN', 'STATS',
  'BEFORE_AFTER', 'CALLOUT', 'END', 'FEATURE', 'SCROLL'];

for (const [id, def] of Object.entries(TRANSITIONS)) sr.defineTransition(id, def);

export { art, letter, page, print };

if (sr && typeof sr.defineKit === 'function') sr.defineKit('comic', { art, letter, page, print, OVERRIDES, css: COMIC_CSS });
