// png.mjs — dev harness helper: write a pixel-kit Screen (index buffer) to a PNG, nearest-upscaled.
// Node-only (uses zlib); never imported by the kit.
import { deflateSync } from 'node:zlib';
import { writeFileSync } from 'node:fs';
import { RGB } from '../../../../kits/pixel/core/palette.js';

const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(buf) { let c = 0xffffffff; for (const b of buf) c = CRC[(c ^ b) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
/** Encode RGBA rows into a PNG buffer. */
export function encodePNG(w, h, rgba) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) { raw[y * (w * 4 + 1)] = 0; Buffer.from(rgba.buffer, rgba.byteOffset + y * w * 4, w * 4).copy(raw, y * (w * 4 + 1) + 1); }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
/** Write a Screen (or Sprite) with palette indices to PNG at integer `scale` (255 -> magenta-checker). */
export function writeScreen(path, S, scale = 4) {
  const W = S.w * scale, H = S.h * scale, out = new Uint8Array(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const c = S.d[((y / scale) | 0) * S.w + ((x / scale) | 0)], p = (y * W + x) * 4;
    if (c === 255) { const k = ((x >> 3) + (y >> 3)) & 1 ? 60 : 40; out[p] = k; out[p + 1] = k; out[p + 2] = k; out[p + 3] = 255; continue; }
    const [r, g, b] = RGB[c]; out[p] = r; out[p + 1] = g; out[p + 2] = b; out[p + 3] = 255;
  }
  writeFileSync(path, encodePNG(W, H, out));
}
