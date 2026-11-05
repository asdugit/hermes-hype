// fakectx.mjs — minimal SDK ctx for Node dev renders of pixel-kit scenes (no canvas, no browser).
// Assets: 'car' is a synthetic moving red car (RGBA frames generated here) so product helpers can be
// exercised without media files.

function fakeG(w, h) {
  return {
    canvas: { width: w, height: h },
    last: null,
    createImageData(W, H) { return { width: W, height: H, data: new Uint8ClampedArray(W * H * 4) }; },
    putImageData(img) { this.last = img; },
  };
}

/** Procedural 160x90 RGBA frame of a red car driving on a road at time t (for dev renders only). */
export function carFrame(t, W = 160, H = 90) {
  const d = new Uint8ClampedArray(W * H * 4);
  const set = (x, y, r, g, b) => { if (x < 0 || y < 0 || x >= W || y >= H) return; const p = (y * W + x) * 4; d[p] = r; d[p + 1] = g; d[p + 2] = b; d[p + 3] = 255; };
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    if (y < 52) { const k = y / 52; set(x, y, 90 + 120 * k, 120 + 90 * k, 200 - 20 * k); }        // sky
    else { const s = ((x + Math.floor(t * 240)) % 40) < 20 && y > 70 && y < 73; set(x, y, s ? 230 : 70, s ? 220 : 72, s ? 200 : 80); } // road
  }
  const cx = 80 + Math.round(Math.sin(t * 2) * 6), cy = 62;
  for (let y = -14; y <= 8; y++) for (let x = -44; x <= 44; x++) {
    const body = (y > -4 && Math.abs(x) < 44) || (y > -14 && y <= -4 && Math.abs(x + 4) < 24 - (y + 14) * -0.4);
    if (!body) continue;
    const glass = y > -12 && y < -5 && Math.abs(x + 4) < 18;
    const shade = 1 - (y + 14) / 30;
    if (glass) set(cx + x, cy + y, 120, 170, 220); else set(cx + x, cy + y, 200 * shade + 55, 30, 40);
  }
  for (const wx of [-26, 26]) for (let y = -7; y <= 7; y++) for (let x = -7; x <= 7; x++) if (x * x + y * y <= 49) set(cx + wx + x, cy + 8 + y, x * x + y * y < 9 ? 180 : 25, x * x + y * y < 9 ? 180 : 25, x * x + y * y < 9 ? 190 : 30);
  set(cx + 43, cy - 2, 255, 240, 180); set(cx + 42, cy - 2, 255, 240, 180);
  return { width: W, height: H, data: d };
}

export function makeCtx(w, h, dur, params = {}) {
  const qaBoxes = [], errors = [];
  const assets = {
    car: { type: 'frames', w: 160, h: 90, fps: 30, dur: 4, count: 120, image: carFrame(0), frame: (t) => carFrame(t % 4) },
  };
  return {
    w, h, dur, id: 'dev', seed: 7, params,
    film: { w: w * 4, h: h * 4, fps: 30, dur, aspect: w >= h ? '16:9' : '9:16' },
    safe: w >= h ? { l: 24, r: 24, t: 16, b: 30 } : { l: 30, r: 30, t: 55, b: 105 },
    g: fakeG(w, h), canvas: { width: w, height: h },
    asset: (n) => assets[n] || null,
    qaText: (b) => qaBoxes.push(b),
    cue: () => {},
    qaBoxes, errors,
  };
}
