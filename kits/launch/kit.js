// Showreel kit "launch" (flagship style): paper UI panels on a lit graphite table shot by a look-at camera,
// lime accent, Geist + one serif-italic emphasis word. Registers the 'launch' theme for kit:base scenes and
// overrides scene types with table-world versions (kit:launch/<TYPE>).

import { sr, registerTheme } from '../base/kit.js';
import { LAUNCH_CSS } from './css.js';
import * as world from './world.js';
import './scenes-panels.js';
import './scenes-media.js';
import './scenes-type.js';

registerTheme('launch', LAUNCH_CSS);

export const OVERRIDES = ['HOOK', 'TITLE', 'PROBLEM', 'PLAN', 'CODE', 'DIFF', 'TERMINAL', 'MONTAGE', 'SCREEN', 'STATS',
  'BEFORE_AFTER', 'CALLOUT', 'END', 'FEATURE', 'SCROLL'];
export { world };

if (sr && typeof sr.defineKit === 'function') sr.defineKit('launch', { world, OVERRIDES, css: LAUNCH_CSS });
