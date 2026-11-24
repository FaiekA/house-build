// Furniture for the House Plan Build walkthrough: simple, real-sized pieces made from boxes and cylinders, coloured
// from the room's design (housedesign.py places them: x, y = centre on the plan, w along its wall, d deep, h tall,
// rot = the way its front faces, 0 north). Original code; no models to license. Styled like people live there:
// cushions on sofas, books on shelves, a lamp on the bedside, a plant in a pot.
import * as THREE from 'three';

const cache = {};
const mat = (c, o = {}) => cache[c + JSON.stringify(o)] ||= new THREE.MeshStandardMaterial({ color: c, roughness: 0.78, ...o });
const shade = () => cache.shade ||= new THREE.MeshStandardMaterial({ color: '#f6e7cc', emissive: '#ffcf8a', emissiveIntensity: 0.9, roughness: 0.9 });
const glass = () => cache.glass ||= new THREE.MeshPhysicalMaterial({ color: '#cfe3ea', roughness: 0.05, transparent: true, opacity: 0.25 });
const lighter = (hex, k) => '#' + new THREE.Color(hex).lerp(new THREE.Color('#ffffff'), k).getHexString();
const darker = (hex, k) => '#' + new THREE.Color(hex).lerp(new THREE.Color('#1b1a18'), k).getHexString();

// box: centred at (x, z) in the piece's own space, from y0 to y0 + h; +z is the front
function box(g, w, h, d, x, y0, z, c, o) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), typeof c === 'string' ? mat(c, o) : c);
  m.position.set(x, y0 + h / 2, z); m.castShadow = m.receiveShadow = true; g.add(m); return m;
}
function cyl(g, r0, r1, h, x, y0, z, c, seg = 14) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r0, r1, h, seg), typeof c === 'string' ? mat(c) : c);
  m.position.set(x, y0 + h / 2, z); m.castShadow = m.receiveShadow = true; g.add(m); return m;
}
function legs(g, w, d, h, c, r = 0.022, inset = 0.06) {
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) cyl(g, r, r, h, sx * (w / 2 - inset), 0, sz * (d / 2 - inset), c, 8);
}
const BOOKS = ['#7d4b3a', '#2f4a5e', '#c9b48a', '#5b6b4a', '#a8573c', '#e0d6c2', '#3b3a38'];

const MAKE = {
  sofa(g, w, d, h, c, a) {
    box(g, w, 0.2, d, 0, 0.1, 0, darker(c, 0.15));                  // base
    box(g, w - 0.36, 0.16, d - 0.26, 0, 0.3, 0.08, c);             // seat cushions
    box(g, w, 0.5, 0.22, 0, 0.3, -d / 2 + 0.11, c);                // back
    for (const s of [-1, 1]) box(g, 0.18, 0.32, d, s * (w / 2 - 0.09), 0.3, 0, c);
    const n = w > 1.8 ? 3 : 2;
    for (let i = 0; i < n; i++) { const m = box(g, 0.42, 0.38, 0.12, (i - (n - 1) / 2) * (w - 0.6) / Math.max(1, n - 1) * 0.9, 0.44, -d / 2 + 0.3, i % 2 ? lighter(a, 0.3) : a); m.rotation.x = -0.25; }
  },
  armchair(g, w, d, h, c, a) {
    box(g, w, 0.22, d, 0, 0.12, 0, darker(c, 0.15)); box(g, w - 0.3, 0.14, d - 0.25, 0, 0.34, 0.06, c);
    box(g, w, 0.52, 0.18, 0, 0.34, -d / 2 + 0.09, c); for (const s of [-1, 1]) box(g, 0.15, 0.3, d, s * (w / 2 - 0.075), 0.34, 0, c);
    const m = box(g, 0.38, 0.34, 0.11, 0, 0.48, -d / 2 + 0.26, lighter(a, 0.2)); m.rotation.x = -0.25;
  },
  coffee_table(g, w, d, h, c, a) {
    box(g, w, 0.04, d, 0, h - 0.04, 0, c); legs(g, w, d, h - 0.04, darker(c, 0.4));
    for (let i = 0; i < 3; i++) box(g, 0.26, 0.035, 0.19, -w / 4, h + i * 0.035, 0, BOOKS[i + 2]);
    cyl(g, 0.05, 0.07, 0.2, w / 4, h, 0, lighter(a, 0.1));
  },
  rug(g, w, d, h, c, a) { box(g, w, 0.012, d, 0, 0.004, 0, c, { roughness: 1 }); box(g, w - 0.24, 0.013, d - 0.24, 0, 0.004, 0, lighter(c, 0.18), { roughness: 1 }); },
  tv_unit(g, w, d, h, c) {
    box(g, w, h - 0.08, d, 0, 0.08, 0, c); legs(g, w, d, 0.08, '#2a2a2a', 0.015);
    box(g, Math.min(1.4, w - 0.2), 0.8, 0.05, 0, h + 0.06, -d / 2 + 0.1, '#151515', { roughness: 0.3 });
    cyl(g, 0.12, 0.12, 0.02, 0, h, -d / 2 + 0.1, '#222');
  },
  sideboard(g, w, d, h, c, a) {
    box(g, w, h - 0.15, d, 0, 0.15, 0, c); legs(g, w, d, 0.15, darker(c, 0.5), 0.018);
    cyl(g, 0.07, 0.09, 0.32, -w / 3, h, 0, a); box(g, 0.3, 0.05, 0.22, w / 4, h, 0, BOOKS[1]); box(g, 0.28, 0.05, 0.2, w / 4, h + 0.05, 0, BOOKS[3]);
  },
  bookshelf(g, w, d, h, c) {
    for (const s of [-1, 1]) box(g, 0.03, h, d, s * (w / 2 - 0.015), 0, 0, c);
    box(g, w, 0.03, d, 0, h - 0.03, 0, c);
    const rows = Math.max(3, Math.round(h / 0.38));
    for (let r = 0; r < rows; r++) {
      const y = r * (h - 0.03) / rows; box(g, w - 0.06, 0.025, d, 0, y, 0, c);
      let x = -w / 2 + 0.06, k = r * 3;
      while (x < w / 2 - 0.15 && (r + k) % 7 !== 6) { const bw = 0.03 + ((k * 37) % 5) * 0.008, bh = 0.2 + ((k * 13) % 4) * 0.025; box(g, bw, bh, d * 0.75, x + bw / 2, y + 0.025, 0, BOOKS[k % BOOKS.length]); x += bw + 0.004; k++; if ((k * 7) % 11 === 0) x += 0.12; }
    }
  },
  dining_table(g, w, d, h, c) { box(g, w, 0.045, d, 0, h - 0.045, 0, c); legs(g, w, d, h - 0.045, darker(c, 0.25), 0.03, 0.1); cyl(g, 0.06, 0.08, 0.26, 0, h, 0, '#e8e2d6'); },
  dining_chair(g, w, d, h, c, a) { box(g, w, 0.05, d, 0, 0.44, 0, c); legs(g, w, d, 0.44, darker(c, 0.2), 0.016, 0.04); box(g, w, 0.42, 0.04, 0, 0.49, -d / 2 + 0.02, c); box(g, w - 0.06, 0.03, d - 0.08, 0, 0.49, 0.02, lighter(a, 0.25)); },
  bed_double(g, w, d, h, c, a) { MAKE.bed(g, w, d, h, c, a, 2); },
  bed_single(g, w, d, h, c, a) { MAKE.bed(g, w, d, h, c, a, 1); },
  bed(g, w, d, h, c, a, pillows) {
    box(g, w, 0.28, d, 0, 0.04, 0, darker(c, 0.25)); box(g, w + 0.06, 1.05, 0.08, 0, 0, -d / 2 - 0.02, darker(c, 0.1));
    box(g, w - 0.06, 0.2, d - 0.1, 0, 0.32, 0.02, '#f4f1ea');
    box(g, w - 0.02, 0.08, d * 0.62, 0, 0.5, d * 0.17, c);
    box(g, w - 0.02, 0.06, 0.3, 0, 0.56, d * 0.42 - 0.15, a);
    for (let i = 0; i < pillows; i++) box(g, pillows === 2 ? w / 2 - 0.12 : w - 0.2, 0.13, 0.36, pillows === 2 ? (i ? 1 : -1) * w / 4 : 0, 0.52, -d / 2 + 0.26, '#fbfaf6');
  },
  bedside(g, w, d, h, c) { box(g, w, h - 0.1, d, 0, 0.1, 0, c); legs(g, w, d, 0.1, darker(c, 0.4), 0.014); cyl(g, 0.06, 0.08, 0.2, 0, h, 0, '#d9d2c4'); cyl(g, 0.09, 0.14, 0.17, 0, h + 0.2, 0, shade()); },
  wardrobe(g, w, d, h, c) {
    box(g, w, h, d, 0, 0, 0, c); const n = w > 1.2 ? 3 : 2;
    for (let i = 1; i < n; i++) box(g, 0.008, h - 0.1, 0.01, -w / 2 + i * w / n, 0.05, d / 2 + 0.004, darker(c, 0.45));
    for (let i = 0; i < n; i++) box(g, 0.02, 0.3, 0.025, -w / 2 + (i + 0.5) * w / n + (i % 2 ? -0.08 : 0.08), h * 0.45, d / 2 + 0.012, '#2a2826');
  },
  desk(g, w, d, h, c) { box(g, w, 0.035, d, 0, h - 0.035, 0, c); legs(g, w, d, h - 0.035, '#2a2a2a', 0.018); box(g, 0.34, 0.015, 0.24, 0.1, h, 0.05, '#bfc3c7'); cyl(g, 0.012, 0.06, 0.45, -w / 2 + 0.2, h, -d / 2 + 0.15, '#2a2a2a', 8); cyl(g, 0.05, 0.09, 0.12, -w / 2 + 0.2, h + 0.4, -d / 2 + 0.15, shade()); },
  desk_chair(g, w, d, h, c) { cyl(g, 0.25, 0.25, 0.04, 0, 0.02, 0, '#2a2a2a', 5); cyl(g, 0.025, 0.025, 0.4, 0, 0.04, 0, '#555'); box(g, w, 0.07, d, 0, 0.44, 0, c); box(g, w, 0.45, 0.05, 0, 0.5, -d / 2 + 0.03, c); },
  counter(g, w, d, h, c, a, top) {
    box(g, w, 0.1, d - 0.06, 0, 0, -0.03, '#2b2a28'); box(g, w, h - 0.14, d - 0.02, 0, 0.1, -0.01, c);
    for (let i = 1; i < Math.round(w / 0.6); i++) box(g, 0.006, h - 0.2, 0.01, -w / 2 + i * w / Math.round(w / 0.6), 0.12, d / 2, darker(c, 0.4));
    box(g, w, 0.04, d, 0, h - 0.04, 0, top);
    box(g, w, 0.6, 0.02, 0, h, -d / 2 + 0.01, lighter(top, 0.25));                // splashback
  },
  sink_unit(g, w, d, h, c, a, top) { MAKE.counter(g, w, d, h, c, a, top); box(g, 0.55, 0.012, 0.4, 0, h, 0.02, '#9aa0a4', { metalness: 0.6, roughness: 0.3 }); cyl(g, 0.015, 0.015, 0.3, 0, h, -d / 2 + 0.1, '#b9bdc0'); },
  hob_unit(g, w, d, h, c, a, top) { MAKE.counter(g, w, d, h, c, a, top); box(g, 0.6, 0.01, 0.52, 0, h, 0, '#121212', { roughness: 0.15 }); box(g, w, 0.35, 0.5, 0, 1.55, -d / 2 + 0.25, darker(c, 0.1)); },
  island(g, w, d, h, c, a, top) { box(g, w - 0.2, h - 0.04, d - 0.2, 0, 0, 0, c); box(g, w, 0.04, d, 0, h - 0.04, 0, top); for (const s of [-1, 0, 1]) { cyl(g, 0.17, 0.17, 0.04, s * w / 3, 0.62, d / 2 + 0.22, a); cyl(g, 0.02, 0.02, 0.62, s * w / 3, 0, d / 2 + 0.22, '#2a2a2a', 6); } },
  fridge(g, w, d, h, c) { box(g, w, h, d, 0, 0, 0, c, { metalness: 0.4, roughness: 0.35 }); box(g, w, 0.008, 0.01, 0, h * 0.62, d / 2 + 0.003, '#777'); box(g, 0.025, 0.5, 0.03, w / 2 - 0.07, h * 0.66, d / 2 + 0.02, '#888'); },
  toilet(g, w, d, h, c) { box(g, w, 0.4, 0.18, 0, 0.4, -d / 2 + 0.09, c); cyl(g, 0.19, 0.16, 0.4, 0, 0, 0.08, c); cyl(g, 0.2, 0.2, 0.03, 0, 0.4, 0.08, c); },
  basin(g, w, d, h, c) { box(g, w, h - 0.15, d, 0, 0.15, 0, c); box(g, w * 0.8, 0.12, d * 0.75, 0, h - 0.02, 0, '#f7f7f5'); box(g, w * 0.9, 0.7, 0.03, 0, 1.2, -d / 2 + 0.015, '#c9d7dc', { metalness: 0.7, roughness: 0.08 }); cyl(g, 0.012, 0.012, 0.18, 0, h + 0.1, -d / 2 + 0.07, '#b9bdc0'); },
  shower(g, w, d, h, c) { box(g, w, 0.05, d, 0, 0, 0, c); box(g, w, h, 0.01, 0, 0.05, d / 2, glass()); box(g, 0.01, h, d, w / 2, 0.05, 0, glass()); cyl(g, 0.1, 0.1, 0.02, -w / 4, 1.95, -d / 4, '#b9bdc0'); },
  bath(g, w, d, h, c) { box(g, w, h, d, 0, 0, 0, c); box(g, w - 0.14, 0.02, d - 0.14, 0, h - 0.015, 0, '#cfe0e6', { roughness: 0.1 }); },
  washer(g, w, d, h, c) { box(g, w, h, d, 0, 0, 0, c); const m = cyl(g, 0.19, 0.19, 0.02, 0, h * 0.42, d / 2, '#3a4045'); m.rotation.x = Math.PI / 2; m.position.y = h * 0.45; },
  plant(g, w, d, h, c) {
    cyl(g, w * 0.32, w * 0.24, 0.34, 0, 0, 0, '#c9b9a0'); const leaf = mat(c, { flatShading: true });
    for (const [x, y, z, r] of [[0, 0.7, 0, 0.26], [0.1, 0.95, 0.05, 0.2], [-0.1, 0.85, -0.05, 0.19], [0.02, 1.08, -0.02, 0.15]]) {
      const m = new THREE.Mesh(new THREE.IcosahedronGeometry(r * Math.max(1, h / 1.2), 0), leaf); m.position.set(x, y * h / 1.2, z); m.castShadow = true; g.add(m);
    }
    cyl(g, 0.015, 0.015, 0.4 * h / 1.2, 0, 0.34, 0, '#5a4330', 5);
  },
  floor_lamp(g, w, d, h, c) { cyl(g, 0.14, 0.15, 0.03, 0, 0, 0, c); cyl(g, 0.012, 0.012, h - 0.3, 0, 0.03, 0, c, 6); cyl(g, 0.13, 0.2, 0.28, 0, h - 0.3, 0, shade()); },
  car(g, w, d, h, c) {                                              // parked in the garage, nose to the door (+z)
    const paint = mat(c && new THREE.Color(c).getHSL({}).l > 0.12 ? c : '#5d6873', { metalness: 0.55, roughness: 0.32 });
    const glassy = mat('#26303a', { metalness: 0.3, roughness: 0.08 });
    box(g, w, 0.42, d, 0, 0.26, 0, paint);                                         // body
    box(g, w * 0.98, 0.14, d * 0.26, 0, 0.68, d * 0.33, paint).rotation.x = 0.08; // bonnet
    box(g, w * 0.98, 0.14, d * 0.2, 0, 0.68, -d * 0.38, paint);                   // boot
    const cab = box(g, w * 0.86, 0.46, d * 0.44, 0, 0.66, -d * 0.04, glassy);    // windows
    box(g, w * 0.8, 0.05, d * 0.36, 0, 1.12, -d * 0.05, paint);                   // roof
    cab.scale.z = 1;
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) { const m = cyl(g, 0.32, 0.32, 0.22, sx * (w / 2 - 0.1), 0, sz * (d / 2 - 0.72), '#1d1d1d', 18); m.rotation.z = Math.PI / 2; m.position.y = 0.32; }
    for (const sx of [-1, 1]) { box(g, 0.22, 0.08, 0.03, sx * (w / 2 - 0.25), 0.5, d / 2 + 0.005, '#f4f1e6'); box(g, 0.22, 0.07, 0.03, sx * (w / 2 - 0.25), 0.55, -d / 2 - 0.005, '#a3302a'); }
  },
  art(g, w, d, h, c, a) { box(g, w, h, 0.03, 0, -h / 2, 0, darker(a, 0.3)); box(g, w - 0.08, h - 0.08, 0.035, 0, -h / 2 + 0.04, 0.002, c); box(g, (w - 0.08) * 0.4, (h - 0.08) * 0.5, 0.037, -(w - 0.08) * 0.15, -h / 2 + 0.12, 0.003, lighter(c, 0.4)); },
};

// One piece -> { group, light } (light: a warm lamp for the floor lamp, bedside or pendant, or null)
export function makeItem(it, H, palette) {
  const g = new THREE.Group();
  const c = it.c || '#bfb6a6', a = it.a || '#8fa3a0';
  const top = palette.stone || palette.wood || '#d9d2c4';
  let light = null;
  if (it.kind === 'pendant') {
    const drop = Math.min(0.9, H - 1.6);
    cyl(g, 0.006, 0.006, drop, 0, H - drop, 0, '#2a2a2a', 4);
    const s = cyl(g, 0.04, 0.24, 0.24, 0, H - drop - 0.24, 0, c); s.material = mat(c, { side: THREE.DoubleSide });
    cyl(g, 0.07, 0.07, 0.06, 0, H - drop - 0.22, 0, shade());
    light = { y: H - drop - 0.3, full: 1.6 };
  } else if (it.kind === 'art') {
    MAKE.art(g, it.w, it.d, it.h, c, a);
    g.children.forEach(m => { m.position.y += it.z || 1.45; m.position.z += 0.02; });
  } else if (MAKE[it.kind]) {
    MAKE[it.kind](g, it.w, it.d, it.h, c, a, top);
    if (it.kind === 'floor_lamp') light = { y: it.h - 0.2, full: 1.1 };
  }
  // its back sits at -d/2 in its own space; turn it to face `rot` (0 = north = -z in the scene)
  g.rotation.y = Math.PI - (it.rot || 0) * Math.PI / 180;
  if (it.kind === 'art') g.children.forEach(m => { m.position.z -= it.d / 2; });
  return { group: g, light };
}
