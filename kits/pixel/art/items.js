// items.js — original item icons (12-16 px) and the big treasure chest (closed / open) used by item-get & shop.
import { Sprite } from './../core/gfx.js';

const K = { k: 'ink', w: 'white', i: 'ice', s: 'silver', g: 'grey', d: 'greydk', y: 'gold', a: 'amber', c: 'cream', b: 'brown', B: 'browndk', t: 'tan',
  r: 'red', R: 'maroon', o: 'coral', p: 'peach', T: 'teal', D: 'tealdk', l: 'lime', G: 'green', u: 'blue', U: 'royal', v: 'violet', V: 'plum', L: 'lilac', n: 'navy' };

const I = {
  potion: ['....kk....', '...kcck...', '...kbbk...', '..kkkkkk..', '.kwoorrrk.', 'kwoorrrrRk', 'kooorrrrRk', 'korrrrrrRk', '.krrrrRRk.', '..kkkkkk..'],
  ether: ['....kk....', '...kcck...', '...kbbk...', '..kkkkkk..', '.kwiTTTTk.', 'kwiiTTTTDk', 'kiTTTTTTDk', 'kTTTTTTTDk', '.kTTTTDDk.', '..kkkkkk..'],
  key: ['.kkk.......', 'kyyyk......', 'kykykkkkkkk', 'kyyykyyyyyk', '.kkkkkkykyk', '......kk.k.'],
  gem: ['..kkkkk..', '.kwiTTTk.', 'kwiTTTTDk', 'kkkkkkkkk', '.kTTTTDk.', '..kTTDk..', '...kDk...', '....k....'],
  sword: ['.........kk', '........kwk', '.......kwsk', '......kwsk.', '.....kwsk..', '.kk.kwsk...', '.kykwsk....', '..kysk.....', '.kbkyk.....', 'kbk.kk.....', 'kk.........'],
  shield: ['.kkkkkkkk.', 'kssssssssk', 'ksUUUUUUsk', 'ksUUyyUUsk', 'ksUyyyyUsk', 'ksUUyyUUsk', '.ksUUUUsk.', '..ksUUsk..', '...kssk...', '....kk....'],
  scroll: ['.kkkkkkkkk.', 'kcckccccckk', 'kbckcbbbckk', '.kckcccccck', '.kckcbbbbck', '.kckcccccck', '.kckcbbbcck', 'kkkkkkkkkck', 'kcccccccckk', '.kkkkkkkkk.'],
  star: ['....k....', '...kyk...', '...kyk...', 'kkkkykkkk', 'kcyyyyyak', '.kayyyak.', '..kyyyk..', '.kyakayk.', 'kak...kak', 'kk.....kk'],
  crown: ['k...k...k', 'kk.kyk.kk', 'kykyyykyk', 'kyyyryyyk', 'kyyyyyyyk', 'kaaaaaaak', 'kkkkkkkkk'],
  heart: ['.kk.kk.', 'kwrkrrk', 'krrrrrk', 'krrrrrk', '.krrrk.', '..krk..', '...k...'],
  bomb: ['......kk.', '.....kyak', '....k..k.', '..kkkk...', '.kgwddk..', 'kgwddddk.', 'kddddddk.', 'kddddddk.', '.kddddk..', '..kkkk...'],
  ring: ['...kkk...', '..kwTDk..', '.kkkkkkk.', 'kyk...kyk', 'ky.....ak', 'kyk...kak', '.kyyyyak.', '..kkkkk..'],
  coin: ['.kkkk.', 'kcyyak', 'kcycak', 'kcycak', 'kcyyak', '.kkkk.'],
};
// big chest 24x18 closed / open (lid swung back, inner glow handled by the scene)
const CHEST_CLOSED = [
  '...kkkkkkkkkkkkkkkkkk...',
  '..kttttttttttttttttttk..',
  '.ktbbbbbbbbbbbbbbbbbbtk.',
  '.kbbbbbbbbbbbbbbbbbbbbk.',
  'kbbbbbbbbbbkkbbbbbbbbbbk',
  'kyyyyyyyyykyykyyyyyyyyyk',
  'kaaaaaaaaakaakaaaaaaaaak',
  'kkkkkkkkkkkkkkkkkkkkkkkk',
  'kbbbbbbbbbkyykbbbbbbbbbk',
  'kbtbbbbbbbkakkbbbbbbbtbk',
  'kbtbbbbbbbbkkbbbbbbbbtbk',
  'kbbbbbbbbbbbbbbbbbbbbbbk',
  'kyyyyyyyyyyyyyyyyyyyyyyk',
  'kaaaaaaaaaaaaaaaaaaaaaak',
  'kbbbbbbbbbbbbbbbbbbbbbbk',
  'kBBBBBBBBBBBBBBBBBBBBBBk',
  'kkkkkkkkkkkkkkkkkkkkkkkk',
];
const CHEST_OPEN = [
  '..kkkkkkkkkkkkkkkkkkkk..',
  '.kbbbbbbbbbbbbbbbbbbbbk.',
  '.kbyyyyyyyyyyyyyyyyyybk.',
  '.kbBBBBBBBBBBBBBBBBBBbk.',
  '.kkkkkkkkkkkkkkkkkkkkkk.',
  'kRRRRRRRRRRRRRRRRRRRRRRk',
  'kRVVVVVVVVVVVVVVVVVVVVRk',
  'kkkkkkkkkkkkkkkkkkkkkkkk',
  'kbbbbbbbbbkyykbbbbbbbbbk',
  'kbtbbbbbbbkakkbbbbbbbtbk',
  'kbtbbbbbbbbkkbbbbbbbbtbk',
  'kbbbbbbbbbbbbbbbbbbbbbbk',
  'kyyyyyyyyyyyyyyyyyyyyyyk',
  'kaaaaaaaaaaaaaaaaaaaaaak',
  'kbbbbbbbbbbbbbbbbbbbbbbk',
  'kBBBBBBBBBBBBBBBBBBBBBBk',
  'kkkkkkkkkkkkkkkkkkkkkkkk',
];

export const ITEMS = I;
export const ITEM_IDS = Object.keys(I);
const CACHE = new Map();
/** Item icon sprite by id (unknown -> star). */
export function item(id) {
  if (CACHE.has(id)) return CACHE.get(id);
  const s = Sprite.rows(I[id] || I.star, K); CACHE.set(id, s); return s;
}
export const CHEST = { closed: Sprite.rows(CHEST_CLOSED, K), open: Sprite.rows(CHEST_OPEN, K) };
