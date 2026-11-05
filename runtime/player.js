// Interactive player for stage.html?player (dev / Desktop preview pane): play-pause, scrubber, frame stepping.
// Never used by the renderer; playback follows the real clock and simply seeks the pure-function film.
import { realNow } from './core/safety.js';

/** Attach a small control bar to the page and drive `api.seek(t)` from the real clock. */
export function attachPlayer(api) {
  const bar = document.createElement('div');
  bar.id = 'sr-player';
  bar.innerHTML = `<button data-k="play" title="space">▶</button><input data-k="scrub" type="range" min="0" step="0.001">
    <span data-k="time">0.00</span>`;
  Object.assign(bar.style, {
    position: 'fixed', left: '0', right: '0', bottom: '0', zIndex: '99999', display: 'flex', gap: '10px',
    alignItems: 'center', padding: '6px 12px', background: 'rgba(12,12,16,.82)', color: '#eee', font: '13px monospace',
  });
  document.body.appendChild(bar);
  const $ = (k) => bar.querySelector(`[data-k="${k}"]`);
  const scrub = $('scrub');
  scrub.max = String(api.dur);
  scrub.style.flex = '1';
  let playing = false, t = 0, startReal = 0, startT = 0, busy = false;
  const show = (x) => { scrub.value = String(x); $('time').textContent = `${x.toFixed(2)} / ${api.dur.toFixed(2)}`; };
  const go = async (x) => {
    if (busy) return;
    busy = true;
    try { await api.seek(x); } finally { busy = false; }
    show(x);
  };
  const tick = () => {
    if (!playing) return;
    t = startT + (realNow() - startReal) / 1000;
    if (t >= api.dur) t = 0, startT = 0, startReal = realNow();
    go(t);
    requestAnimationFrame(tick);
  };
  const toggle = () => {
    playing = !playing;
    $('play').textContent = playing ? '❚❚' : '▶';
    if (playing) { startT = t; startReal = realNow(); requestAnimationFrame(tick); }
  };
  $('play').addEventListener('click', toggle);
  scrub.addEventListener('input', () => { t = Number(scrub.value); startT = t; startReal = realNow(); go(t); });
  window.addEventListener('keydown', (e) => {
    if (e.code === 'Space') { e.preventDefault(); toggle(); }
    if (e.code === 'ArrowRight' || e.code === 'ArrowLeft') {
      t = Math.max(0, Math.min(api.dur, t + (e.code === 'ArrowRight' ? 1 : -1) / api.fps));
      go(t);
    }
  });
  const q = new URLSearchParams(location.search);
  t = Number(q.get('t') || 0);
  go(t);
}
