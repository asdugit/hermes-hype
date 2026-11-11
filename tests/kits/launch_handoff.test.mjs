// kits/launch handoff helpers under Node (no DOM). Prints one JSON object {name: true | "failure"}.
import { handoff, blendCam, featureCopy } from '../../kits/launch/handoff.js';

const out = {};
function check(name, fn) {
  try { const r = fn(); out[name] = r === true ? true : `returned ${JSON.stringify(r)}`; } catch (e) { out[name] = String(e && e.message || e); }
}
const land = { portrait: false }, port = { portrait: true };

check('landscape feature hands off to the product after the headline reads', () => {
  const h = handoff(land, 5);
  return h.t0 >= 1.1 && h.t0 <= 1.9 && h.u(0) === 0 && h.u(h.t0) === 0 && h.u(h.t0 + 0.85) === 1 && h.u(4.9) === 1;
});
check('hook hands off early', () => { const h = handoff(land, 2.4, true); return h.t0 >= 0.7 && h.t0 <= 1.1 && h.u(2.4) === 1; });
check('portrait and very short shots keep their layout', () => !Number.isFinite(handoff(port, 6).t0) && handoff(port, 6).u(5) === 0
  && !Number.isFinite(handoff(land, 1.5).t0) && handoff(land, 1.5).u(1.4) === 0);
check('blendCam ends', () => {
  const a = { target: [0, 0, 0], dist: 100, yaw: 0, pitch: 10, roll: 0, shift: [300, 0] };
  const b = { target: [10, 0, 0], dist: 400, yaw: 2, pitch: 6, roll: 0, shift: [0, 0] };
  const m = blendCam(a, b, 0.5);
  return blendCam(a, b, 0) === a && blendCam(a, b, 1) === b && Math.abs(m.dist - 200) < 1e-9 && m.shift[0] === 150
    && m.target[0] === 5 && blendCam(a, null, 0.5) === a;
});
check('feature copy: benefit label leads, feature name is the eyebrow', () => {
  const a = featureCopy('Timer', 'Pomodoro countdown ring');
  const b = featureCopy('Hand-built suspects', 'Hand-built suspects');
  const c = featureCopy('Tasks', '');
  return a.head === 'Pomodoro countdown ring' && a.eyebrow === 'Timer' && b.head === 'Hand-built suspects'
    && b.eyebrow === 'Feature' && c.head === 'Tasks' && c.eyebrow === 'Feature';
});
console.log(JSON.stringify(out));
