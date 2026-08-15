/**
 * Generates the PWA icons (a poker chip on felt) as PNGs, with no image
 * dependencies — the raster is drawn by hand and deflated into a PNG.
 *
 *   node scripts/make-icons.mjs
 */
import { deflateSync } from 'node:zlib';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'icons');

const FELT = [10, 28, 20];
const FELT_EDGE = [22, 60, 43];
const CHIP = [193, 42, 47];
const CHIP_DARK = [138, 26, 30];
const SPOT = [242, 246, 243];
const BRASS = [212, 168, 60];

const lerp = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

/**
 * @param size pixel size
 * @param inset fraction of the canvas the chip occupies (maskable icons need padding)
 */
function drawIcon(size, inset) {
  const px = new Uint8Array(size * size * 4);
  const c = size / 2;
  const R = (size / 2) * inset;
  const SS = 3; // supersample factor, for smooth edges

  const spotCount = 6;
  const spotAngle = Math.PI / 11;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let acc = [0, 0, 0];
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const fx = x + (sx + 0.5) / SS;
          const fy = y + (sy + 0.5) / SS;
          acc = acc.map((v, i) => v + sample(fx, fy)[i]);
        }
      }
      const n = SS * SS;
      const i = (y * size + x) * 4;
      px[i] = acc[0] / n;
      px[i + 1] = acc[1] / n;
      px[i + 2] = acc[2] / n;
      px[i + 3] = 255;
    }
  }

  function sample(x, y) {
    const dx = x - c;
    const dy = y - c;
    const d = Math.hypot(dx, dy);

    // Felt background with a soft top-light.
    const bg = lerp(FELT_EDGE, FELT, Math.min(1, (y / size) * 1.15));
    if (d > R) return bg;

    // Chip body, with edge spots.
    if (d > R * 0.74) {
      const a = Math.atan2(dy, dx);
      const step = (Math.PI * 2) / spotCount;
      // `nearest` is the centre of the closest spot, so the gap is just the difference.
      const nearest = Math.round(a / step) * step;
      return Math.abs(a - nearest) < spotAngle ? SPOT : CHIP;
    }
    if (d > R * 0.68) return CHIP_DARK;
    if (d > R * 0.62) return BRASS;
    if (d > R * 0.58) return CHIP_DARK;

    // Inner face: a felt disc with a brass ring, so it reads at 40px too.
    if (d > R * 0.3 && d < R * 0.36) return BRASS;
    return lerp(FELT, FELT_EDGE, 0.35);
  }

  return px;
}

function toPng(size, rgba) {
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0; // filter: none
    Buffer.from(rgba.buffer, y * size * 4, size * 4).copy(raw, y * (size * 4 + 1) + 1);
  }

  const chunks = [
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr(size)),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ];
  return Buffer.concat(chunks);
}

function ihdr(size) {
  const b = Buffer.alloc(13);
  b.writeUInt32BE(size, 0);
  b.writeUInt32BE(size, 4);
  b[8] = 8; // bit depth
  b[9] = 6; // colour type: RGBA
  return b;
}

function chunk(type, data) {
  const out = Buffer.alloc(data.length + 12);
  out.writeUInt32BE(data.length, 0);
  out.write(type, 4, 'ascii');
  data.copy(out, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
  return out;
}

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

mkdirSync(OUT, { recursive: true });
const targets = [
  ['icon-192.png', 192, 0.86],
  ['icon-512.png', 512, 0.86],
  ['apple-touch-icon.png', 180, 0.82],
  ['maskable-512.png', 512, 0.62], // content inside the 80% safe zone
  ['favicon.png', 64, 0.9],
];
for (const [name, size, inset] of targets) {
  writeFileSync(resolve(OUT, name), toPng(size, drawIcon(size, inset)));
  console.log(`wrote ${name} (${size}px)`);
}
