// Showreel kit "base": style-neutral DOM implementations of all 15 storyboard scene types
// (kit:base/<TYPE>), driven only by theme tokens. Style kits re-skin it with a theme stylesheet
// (registerTheme) and may override individual scene types. Building blocks are exported for other kits.

import { sr } from './scene.js';
import './scenes-panels.js';
import './scenes-media.js';
import './scenes-titles.js';
import * as motion from './motion.js';
import * as dom from './dom.js';
import * as scene from './scene.js';
import * as code from './code.js';
import * as term from './term.js';
import * as media from './media.js';
import * as cards from './cards.js';
import * as type from './type.js';
import { contentBlock } from './scenes-media.js';
import { panelIn, COMMON } from './scenes-panels.js';
import { titleSize } from './scenes-titles.js';
import { BASE_CSS } from './css.js';
import { STARTER_THEMES } from './themes.js';

export const SCENE_TYPES = ['HOOK', 'TITLE', 'PROBLEM', 'PLAN', 'CODE', 'DIFF', 'TERMINAL', 'MONTAGE', 'SCREEN',
  'STATS', 'BEFORE_AFTER', 'CALLOUT', 'END', 'FEATURE', 'SCROLL'];

export const blocks = { ...code, ...term, ...media, ...cards, ...type, contentBlock, panelIn, titleSize };
export { motion, dom, scene, BASE_CSS, COMMON, sr, STARTER_THEMES };
export const registerTheme = dom.registerTheme;

// Expose the building blocks through ctx.kit('base') when the runtime supports kit registration.
if (sr && typeof sr.defineKit === 'function') sr.defineKit('base', { blocks, motion, dom, scene, registerTheme, SCENE_TYPES });
