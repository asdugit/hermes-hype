// Showreel kits/base — base stylesheet as text (CSS module script, so the CSS stays a plain .css file).
import sheet from './base.css' with { type: 'css' };

export const BASE_CSS = Array.from(sheet.cssRules, (r) => r.cssText).join('\n');
