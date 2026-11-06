// index.js — every kit:pixel scene, registered by kit.js.
import { dungeonWalk } from './dungeon-walk.js';
import { bossBattle } from './boss-battle.js';
import { titleScreen, itemGet, questLogScene, scoreTally, shop } from './rpg.js';
import { QUICK } from './quick.js';
import { gameScene } from './base.js';

// every scene sees a game-resolution ctx (hi-res surfaces get the kit's own camera + upscale, see base.js)
export const SCENES = [dungeonWalk, bossBattle, titleScreen, itemGet, questLogScene, scoreTally, shop, ...QUICK].map(gameScene);
