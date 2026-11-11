// Auteur kit "ink" (style "ink"): a warm hand-drawn illustrated explainer. Every Quick-mode scene type is a
// page of warm paper where seeded Rough.js strokes draw on, the user and the little robot helper act out the beat
// from a small pose library, sticky notes, arrows and handwritten notes annotate it, and real product captures are
// taped onto the page; ink-bleed and paper-slide transitions; a gentle hand-held camera. Registers the "ink" theme
// (replaces the kits/base starter), the kit:ink/* scenes and the kit:ink/* transitions.

import { sr, registerTheme } from '../base/kit.js';
import { INK_CSS } from './css.js';
import * as ink from './lib/ink.js';
import * as cast from './lib/cast.js';
import * as props from './lib/props.js';
import * as page from './lib/page.js';
import { TRANSITIONS } from './lib/transitions.js';
import './scenes-story.js';
import './scenes-code.js';
import './scenes-media.js';

registerTheme('ink', INK_CSS);

export const OVERRIDES = ['HOOK', 'TITLE', 'PROBLEM', 'PLAN', 'CODE', 'DIFF', 'TERMINAL', 'MONTAGE', 'SCREEN', 'STATS',
  'BEFORE_AFTER', 'CALLOUT', 'END', 'FEATURE', 'SCROLL'];

for (const [id, def] of Object.entries(TRANSITIONS)) sr.defineTransition(id, def);

export { ink, cast, props, page };

if (sr && typeof sr.defineKit === 'function') sr.defineKit('ink', { ink, cast, props, page, OVERRIDES, css: INK_CSS });
