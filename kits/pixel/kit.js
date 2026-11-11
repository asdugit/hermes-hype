// kit.js — the Hype PIXEL kit: original 16-bit art, RPG UI, product-as-boss helpers, scenes, transitions.
// Registers kit:pixel/* scenes + transitions and exposes building blocks as ctx.kit('pixel') (see KIT.md).
import { sr } from '../../runtime/showreel.js';
import { PALETTE, NAMES, IDX, RGB, RAMPS, REMAP, quantize, bayer, ci } from './core/palette.js';
import { Screen, Sprite } from './core/gfx.js';
import { drawText, measure, wrap, fit, typed, typedBlips, fontInfo } from './core/text.js';
import * as motion from './core/motion.js';
import { heroFrames, walkCel, idleCel, HERO_IDS, HERO_ANCHOR } from './art/heroes.js';
import { MONSTERS, monster, MONSTER_IDS } from './art/monsters.js';
import { ITEMS, item, ITEM_IDS } from './art/items.js';
import * as fx from './art/fx.js';
import { productSprite, bossFrame } from './art/product.js';
import * as dungeon from './bg/dungeon.js';
import { chamber, brazier } from './bg/chamber.js';
import * as worlds from './bg/worlds.js';
import * as ui from './ui/ui.js';
import * as panels from './ui/panels.js';
import { SFX, MISSING, cue, txCue } from './cues.js';
import { screenOf, uiOf, present, say, withDefaults, isVertical, gameCtx, pixelScale } from './scenes/base.js';
import * as camera from './core/camera.js';
import { pickOrigin } from './scenes/boss-battle.js';
import { SCENES } from './scenes/index.js';
import { petalBloom } from './transitions/petal-bloom.js';
import { iris, screenSlide, battleSwirl } from './transitions/simple.js';

for (const s of SCENES) sr.defineScene(s.id, s.def);
for (const t of [petalBloom, iris, screenSlide, battleSwirl]) sr.defineTransition(t.id, t.def);

/** Building blocks for Director-written scenes: `const px = ctx.kit('pixel'); const S = px.begin(ctx); ...; px.end(ctx, S)`. */
export const blocks = {
  // frame plumbing
  game: gameCtx, pixelScale,
  begin: (ctx) => screenOf(ctx).fill('ink'),
  uiScreen: (ctx) => uiOf(ctx),
  end: (ctx, S, o) => present(ctx, S, o),
  camera,
  say, withDefaults, isVertical,
  // palette & drawing
  PALETTE, NAMES, IDX, RGB, RAMPS, REMAP, quantize, bayer, ci, Screen, Sprite,
  // text
  drawText, measure, wrap, fit, typed, typedBlips, fontInfo,
  // motion
  motion,
  // art
  heroFrames, walkCel, idleCel, HERO_IDS, HERO_ANCHOR, MONSTERS, monster, MONSTER_IDS, ITEMS, item, ITEM_IDS, fx,
  // product
  productSprite, bossFrame, pickOrigin,
  // backgrounds
  dungeon, chamber, brazier, worlds,
  // UI
  ui, panels,
  // sound
  SFX, MISSING_SFX: MISSING, cue, txCue,
};
sr.defineKit('pixel', blocks);
export default blocks;
