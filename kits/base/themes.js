// Hype kits/base — starter themes (CSS only) proving every kit:base scene re-skins from tokens.
// Style kits may register a theme with the same name later to replace one (last registration wins).
import terminal from './themes/terminal.css' with { type: 'css' };
import blueprint from './themes/blueprint.css' with { type: 'css' };
import comic from './themes/comic.css' with { type: 'css' };
import ink from './themes/ink.css' with { type: 'css' };
import noir from './themes/noir.css' with { type: 'css' };
import anime from './themes/anime.css' with { type: 'css' };
import { registerTheme } from './dom.js';

const text = (sheet) => Array.from(sheet.cssRules, (r) => r.cssText).join('\n');
export const STARTER_THEMES = { terminal: text(terminal), blueprint: text(blueprint), comic: text(comic), ink: text(ink),
  noir: text(noir), anime: text(anime) };
for (const [name, css] of Object.entries(STARTER_THEMES)) registerTheme(name, css);
