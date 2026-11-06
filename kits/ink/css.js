// Showreel kit "ink" — theme stylesheet as text (CSS module script keeps theme.css plain CSS).
import sheet from './theme.css' with { type: 'css' };

export const INK_CSS = Array.from(sheet.cssRules, (r) => r.cssText).join('\n');
