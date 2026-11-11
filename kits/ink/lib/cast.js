// Hype kit "ink" — the recurring cast, built only from primitive shapes (fills + seeded rough outlines):
//   robot(key, o)  the agent: a small cream robot with a screen face, antenna bulb and tube arms.
//   person(key, o) the user: round glasses, teal sweater; 'bust' (waist up) or 'stand' (full figure).
// Poses come from a small library (POSES: arm angles + an optional prop in the hand); scenes pick a pose and may
// animate the arm groups (setArm) or switch faces (face) — they never invent new geometry. Local origin = feet
// centre (stand / robot) or the bottom centre of the cut (bust); y grows downwards.

import { C, form, tube, stroke, sparkle } from './ink.js';
import { clamp } from '../../base/motion.js';

/** Arm angles in degrees from hanging down, outward positive (180 = straight up), and the prop in the right hand. */
export const POSES = {
  stand: { l: 18, r: 18 },
  wave: { l: 18, r: 150 },
  cheer: { l: 150, r: 150 },
  point: { l: 18, r: 98, prop: 'pointer' },
  present: { l: 18, r: 120 },
  flag: { l: 24, r: 165, prop: 'flag' },
  think: { l: 18, r: 160, face: 'focus' },
  hold: { l: 120, r: 120 },
  type: { l: 52, r: 52, face: 'focus' },
  shrug: { l: 70, r: 70, face: 'wow' },
};

const ROBOT_SHOULDER = [48, -74];
const PERSON_SHOULDER = [84, 120];

/** Arm transform for a side ('l' | 'r') at angle a (deg, outward), shoulder s = [x, y] (x for the right side). */
export function armTransform(side, a, s) {
  const x = side === 'l' ? -s[0] : s[0];
  return `translate(${x},${s[1]}) rotate(${(side === 'l' ? a : -a).toFixed(2)})`;
}

/** Set a robot/person arm group (data-k `${key}-armL|R`) to angle a. kind: 'robot' | 'person'. */
export function setArm(el, side, a, kind = 'robot', s = null) {
  if (!el) return;
  el.setAttribute('transform', armTransform(side, a, s || (kind === 'robot' ? ROBOT_SHOULDER : PERSON_SHOULDER)));
}

function propMarkup(prop, key, L, len = 170) {
  if (prop === 'flag') {
    return tube(`M0,${L - 4} L0,${L + 128}`, 'woodD', 6) +
      form(['path', `M0,${L + 128} L-74,${L + 112} L-62,${L + 92} L-82,${L + 74} L0,${L + 84} Z`], 'teal', `${key}:flag`, { sw: 2.8 }) +
      `<path d="M-30,${L + 104} L-20,${L + 92} M-26,${L + 98} L-42,${L + 92}" stroke="${C.cream}" stroke-width="0" fill="none"/>` +
      stroke(['path', `M-50,${L + 96} L-38,${L + 106} L-20,${L + 86}`], `${key}:flagtick`, { sw: 5, stroke: 'cream', keep: true });
  }
  if (prop === 'pointer') return tube(`M0,${L - 2} L0,${L + len}`, 'woodD', 7) + tube(`M0,${L + len - 10} L0,${L + len + 2}`, 'ink', 7);
  if (prop === 'sign') return '';
  return '';
}

/**
 * The robot. o: {pose, face ('happy' | 'focus' | 'wow' | 'shut'), shadow (true), lit (antenna lit), reach (arm
 * length, 60)}. Returns {markup, h (height above the feet ~ 264), parts} with data-k handles:
 * `${key}`, `${key}-armL`, `${key}-armR`, `${key}-head`, `${key}-bulb`, `${key}-glow`, `${key}-face-<name>`.
 */
export function robot(key, o = {}) {
  const pose = { ...(POSES[o.pose || 'stand'] || POSES.stand), ...(o.arms || {}) };
  const L = 60, LR = o.reach ?? 60;
  const face = o.face || pose.face || 'happy';
  const arm = (side, a, prop, L) => `<g data-k="${key}-arm${side.toUpperCase()}" transform="${armTransform(side, a, ROBOT_SHOULDER)}">` +
    tube(`M0,0 C-7,${L * 0.4} -7,${L * 0.75} 0,${L}`, 'ink', 21) + tube(`M0,0 C-7,${L * 0.4} -7,${L * 0.75} 0,${L}`, 'creamD', 14.5) +
    (L > 90 ? tube(`M-8,${L * 0.33} L8,${L * 0.33} M-8,${L * 0.62} L8,${L * 0.62}`, 'ink', 3) : '') +
    (prop ? propMarkup(prop, key, L, o.pointer) : '') + form(['circle', 0, L + 6, 10], 'mustard', `${key}:hand${side}`, { sw: 2.6 }) + '</g>';
  const faces = {
    happy: tube('M-30,-156 Q-20,-172 -10,-156 M10,-156 Q20,-172 30,-156', 'mustard', 6) + tube('M-11,-143 Q0,-135 11,-143', 'mustard', 4),
    focus: `<circle cx="-20" cy="-160" r="6" fill="${C.mustard}"/><circle cx="20" cy="-160" r="6" fill="${C.mustard}"/>` + tube('M-9,-141 L9,-141', 'mustard', 4),
    wow: `<circle cx="-20" cy="-160" r="8" fill="none" stroke="${C.mustard}" stroke-width="4.5"/><circle cx="20" cy="-160" r="8" fill="none" stroke="${C.mustard}" stroke-width="4.5"/><ellipse cx="0" cy="-139" rx="6" ry="7" fill="${C.mustard}"/>`,
    shut: tube('M-29,-159 L-11,-159 M11,-159 L29,-159', 'mustard', 5) + tube('M-11,-143 Q0,-135 11,-143', 'mustard', 4),
  };
  const faceG = Object.entries(faces).map(([n, m]) => `<g data-k="${key}-face-${n}" opacity="${n === face ? 1 : 0}">${m}</g>`).join('');
  const markup = `<g data-k="${key}">` +
    (o.shadow === false ? '' : `<ellipse cx="0" cy="2" rx="62" ry="7" fill="${C.shadow}"/>`) +
    arm('l', pose.l, null, L) +
    `<rect x="-34" y="-18" width="28" height="18" rx="7" fill="${C.ink}"/><rect x="8" y="-18" width="28" height="18" rx="7" fill="${C.ink}"/>` +
    form(['rect', -52, -104, 104, 94, 26], 'cream', `${key}:body`) +
    `<path d="M28,-102 Q52,-102 52,-78 L52,-36 Q52,-10 26,-10 L18,-10 Q34,-42 28,-102 Z" fill="${C.creamD}"/>` +
    form(['rect', -28, -82, 56, 44, 12], 'peach', `${key}:panel`, { sw: 2.4 }) +
    `<circle cx="0" cy="-60" r="11" fill="${C.terra}"/><circle cx="-4" cy="-64" r="3.5" fill="${C.cream}"/>` +
    `<rect x="-10" y="-118" width="20" height="16" fill="${C.inkS}"/>` +
    `<g data-k="${key}-head">` +
    `<line x1="0" y1="-212" x2="0" y2="-244" stroke="${C.ink}" stroke-width="4" stroke-linecap="round"/>` +
    `<circle data-k="${key}-glow" cx="0" cy="-252" r="24" fill="${C.mustard}" opacity="${o.lit ? 0.35 : 0}"/>` +
    form(['circle', 0, -252, 11], o.lit ? 'mustard' : 'terra', `${key}:ant`, { sw: 2.6, k: `${key}-bulb` }) +
    form(['circle', -68, -162, 10], 'mustard', `${key}:boltL`, { sw: 2.6 }) +
    form(['circle', 68, -162, 10], 'mustard', `${key}:boltR`, { sw: 2.6 }) +
    form(['rect', -68, -214, 136, 104, 32], 'cream', `${key}:head`) +
    `<rect x="-54" y="-199" width="108" height="74" rx="22" fill="${C.screen}"/>` + faceG +
    `<circle cx="-35" cy="-142" r="5" fill="${C.terra}" opacity=".8"/><circle cx="35" cy="-142" r="5" fill="${C.terra}" opacity=".8"/>` +
    '</g>' + arm('r', pose.r, pose.prop || o.prop, LR) + '</g>';
  return { markup, h: 264, w: 150 };
}

/** Switch the robot face (handles from ink.handles). */
export function face(K, key, name) {
  for (const n of ['happy', 'focus', 'wow', 'shut']) for (const e of K[`${key}-face-${n}`] || []) e.setAttribute('opacity', n === name ? '1' : '0');
}

/** Blink the robot every ~3 s (deterministic in t). */
export function blink(K, key, t, base = 'happy', phase = 0) {
  const c = ((t + phase) % 3.1 + 3.1) % 3.1;
  face(K, key, c > 2.95 ? 'shut' : base);
}

/** Antenna glow 0..1. */
export function antenna(K, key, v) {
  for (const e of K[`${key}-glow`] || []) e.setAttribute('opacity', (clamp(v) * 0.45).toFixed(3));
}

/**
 * The user. o: {variant: 'bust' | 'stand', pose, look (pupil x offset -1..1)}. Returns {markup, h} with handles
 * `${key}`, `${key}-armL`, `${key}-armR`, `${key}-head`. Head radius 64; stand height ~650, bust height ~380.
 */
export function person(key, o = {}) {
  const pose = { ...(POSES[o.pose || 'stand'] || POSES.stand), ...(o.arms || {}) };
  const stand = o.variant === 'stand';
  const oy = stand ? -582 : -312;     // head centre relative to the local origin
  const lk = (o.look || 0) * 3;
  const L = 150;
  const arm = (side, a, prop) => `<g data-k="${key}-arm${side.toUpperCase()}" transform="${armTransform(side, a, PERSON_SHOULDER)}">` +
    tube(`M0,0 C-8,${L * 0.4} -8,${L * 0.75} 0,${L}`, 'ink', 37) + tube(`M0,0 C-8,${L * 0.4} -8,${L * 0.75} 0,${L}`, 'teal', 30) +
    tube(`M0,${L - 10} L0,${L - 2}`, 'tealD', 30, { cap: 'butt' }) +
    (prop ? propMarkup(prop, key, L + 6, o.pointer) : '') + form(['circle', 0, L + 14, 15], 'skin', `${key}:hand${side}`, { sw: 2.8 }) + '</g>';
  const legs = stand ? (form(['path', 'M-80,296 L-6,296 L-14,566 L-60,566 Z'], 'hair', `${key}:legL`) +
    form(['path', 'M6,296 L80,296 L60,566 L14,566 Z'], 'hair', `${key}:legR`) +
    form(['rect', -78, 556, 64, 24, 11], 'terraD', `${key}:shoeL`, { sw: 2.6 }) + form(['rect', 14, 556, 64, 24, 11], 'terraD', `${key}:shoeR`, { sw: 2.6 })) : '';
  const torsoBottom = stand ? 304 : 312;
  const markup = `<g data-k="${key}"><g transform="translate(0,${oy})">` +
    (stand ? `<ellipse cx="0" cy="${582}" rx="110" ry="10" fill="${C.shadow}"/>` : '') + legs +
    arm('l', pose.l, null) +
    form(['path', `M-100,${torsoBottom} L-100,166 C-100,110 -62,90 0,88 C62,90 100,110 100,166 L100,${torsoBottom} Z`], 'teal', `${key}:torso`) +
    `<path d="M57,92 C87,98 100,120 100,166 L100,${torsoBottom - 2} L69,${torsoBottom - 2} C75,240 73,160 57,92 Z" fill="${C.tealD}"/>` +
    `<rect x="-17" y="48" width="34" height="48" fill="${C.skinD}"/>` +
    `<path d="M-29,90 L0,126 L29,90 Z" fill="${C.cream}"/><path d="M-29,90 L0,126 L29,90" fill="none" stroke="${C.ink}" stroke-width="3" stroke-linejoin="round"/>` +
    `<g data-k="${key}-head">` +
    form(['circle', -63, 10, 14], 'skinD', `${key}:earL`) + form(['circle', 63, 10, 14], 'skinD', `${key}:earR`) +
    form(['circle', 0, 0, 64], 'skin', `${key}:head`) +
    `<path d="M43,-50 C71,-28 75,32 47,56 C59,20 59,-16 43,-50 Z" fill="${C.skinD}" opacity=".55"/>` +
    form(['path', 'M-66,14 C-79,-48 -45,-76 3,-76 C53,-76 81,-48 67,14 C61,-8 53,-22 41,-30 C21,-16 -21,-12 -51,-22 C-58,-10 -63,2 -66,14 Z'], 'hair', `${key}:hair`) +
    tube('M-37,-12 Q-24,-19 -11,-14 M11,-14 Q24,-19 37,-12', 'hair', 4.5) +
    `<circle cx="-22" cy="11" r="17" fill="none" stroke="${C.ink}" stroke-width="3.2"/><circle cx="23" cy="11" r="17" fill="none" stroke="${C.ink}" stroke-width="3.2"/>` +
    tube('M-5,9 Q0.5,4 6,9', 'ink', 3) +
    `<ellipse cx="${-20 + lk}" cy="15" rx="4.5" ry="5.5" fill="${C.ink}"/><ellipse cx="${25 + lk}" cy="15" rx="4.5" ry="5.5" fill="${C.ink}"/>` +
    `<circle cx="-43" cy="36" r="9" fill="${C.terra}" opacity=".28"/><circle cx="45" cy="36" r="9" fill="${C.terra}" opacity=".28"/>` +
    tube('M-12,42 Q1,53 14,42', 'ink', 3.2) + '</g>' +
    arm('r', pose.r, pose.prop || o.prop) + '</g></g>';
  return { markup, h: stand ? 646 : 376, w: 260 };
}

/** A few sparkles around a point (decor). */
export function sparkles(list) {
  return list.map(([x, y, r, c]) => sparkle(x, y, r, c || 'mustard')).join('');
}
