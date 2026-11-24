// Designed Living walkthrough engine. One house's data is read from <script id="house-data">; the same
// page then plays: the plan on paper -> pencil walls rise -> eye-level walk room by room -> aerial -> plan vs built.
// Original code for the Home 3D project, made generic for any house. Libraries: three.js (MIT), GSAP (free licence),
// Lenis (MIT). Textures: Poly Haven (CC0).
import * as THREE from 'three';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { MTLLoader } from 'three/examples/jsm/loaders/MTLLoader.js';
import { EXRLoader } from 'three/examples/jsm/loaders/EXRLoader.js';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';
import { TEX, HDRI } from './ph.js';
import { makeItem } from './furniture.js';

gsap.registerPlugin(ScrollTrigger);
const MAXR = 16;                         // rooms the reveal shader knows (more are shown, but wake up with the outdoors)

function fail(msg) { const l = document.getElementById('loading'); l.textContent = msg; console.error(msg); }
let HOUSE;
try { HOUSE = JSON.parse(document.getElementById('house-data').textContent); } catch (e) { HOUSE = null; }
if (!HOUSE || !HOUSE.size) fail('No house in this page yet');
else loadAssets().then(a => run(HOUSE, a)).catch(e => { console.error(e); fail('Could not load the house'); });

async function loadAssets() {
  const PT = {};
  const tl = new THREE.TextureLoader();
  await Promise.all(Object.entries(TEX).map(async ([k, v]) => { const t = await tl.loadAsync(v); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; if (!k.endsWith('N')) t.colorSpace = THREE.SRGBColorSpace; PT[k] = t; }));
  const env = await new EXRLoader().loadAsync(HDRI);
  let model = null;
  if (HOUSE.model && HOUSE.model.obj) model = await loadModel(HOUSE.model);
  return { PT, env, model };
}

// The OBJ arrives already in plan metres: vertex = (x, height, -y). Textures named in the MTL come from model.files.
async function loadModel(m) {
  const files = m.files || {};
  const manager = new THREE.LoadingManager();
  manager.setURLModifier(url => { const base = decodeURIComponent(url.split(/[\\/]/).pop()); return files[base] || files[base.toLowerCase()] || url; });
  let mats = null;
  if (m.mtl) { mats = new MTLLoader(manager).parse(m.mtl, ''); mats.preload(); }
  const loader = new OBJLoader(manager);
  if (mats) loader.setMaterials(mats);
  const obj = loader.parse(m.obj);
  await new Promise(res => { if (manager.itemsTotal === manager.itemsLoaded) res(); else { manager.onLoad = res; setTimeout(res, 8000); } });
  obj.traverse(n => {
    if (!n.isMesh) return;
    const conv = src => {
      const op = src.opacity ?? 1;
      return new THREE.MeshStandardMaterial({ color: src.color || '#dddddd', map: src.map || null, roughness: 0.8, metalness: 0,
        transparent: op < 0.99, opacity: op, side: THREE.DoubleSide, depthWrite: op >= 0.99 });
    };
    n.material = Array.isArray(n.material) ? n.material.map(conv) : conv(n.material);
    if (n.material.map) n.material.map.colorSpace = THREE.SRGBColorSpace;
    n.castShadow = n.receiveShadow = true;
    if (!n.geometry.attributes.normal) n.geometry.computeVertexNormals();
  });
  return obj;
}

function run(D, { PT, env: ENV, model }) {
const SW = D.size[0], SD = D.size[1], S = Math.max(SW, SD), CX = SW / 2, CY = SD / 2;
const W = (x, y, h = 0) => new THREE.Vector3(x - CX, h, CY - y);
const EYE = 1.6;
const PLAN = D.plan || null;
const H = (PLAN && PLAN.wall_height) || D.wall_height || 2.6;
const ROOMS = (D.rooms || []).filter(r => r && r.x && r.y && r.x[1] > r.x[0] && r.y[1] > r.y[0]);
const rc = r => [(r.x[0] + r.x[1]) / 2, (r.y[0] + r.y[1]) / 2];
// the designer's work (housedesign.py): the house palette, and per room a photo, colours and furniture
const DES = D.design || null;
const RD = r => (DES && DES.rooms && DES.rooms[r.name]) || null;
const PAL = {};
((DES && DES.palette) || []).forEach(p => { if (!PAL[p.use]) PAL[p.use] = p.hex; });

// front door: the point given, and which way is "out" (the nearest side of the house)
const ent = D.entrance || { x: CX, y: 0 };
const OUT = (() => {
  const d = [[ent.y, 0, -1], [SD - ent.y, 0, 1], [ent.x, -1, 0], [SW - ent.x, 1, 0]].sort((a, b) => a[0] - b[0])[0];
  return { x: d[1], y: d[2] };
})();
const along = (k, h = EYE) => W(ent.x + OUT.x * k, ent.y + OUT.y * k, h);

// ---------- renderer / scene ----------
const canvas = document.getElementById('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.82;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 400);

// ---------- the "sketch to real" effect ----------
// Outside each room's growing circle everything is pencil on paper; inside it is fully rendered, with an orange edge
// while the circle grows. uCut hides everything above the walls while the camera is above them (a cutaway).
const U = {
  uRect: { value: [] }, uZone: { value: [] }, uCount: { value: Math.min(ROOMS.length, MAXR) },
  uWipe: { value: -1000 }, uInk: { value: 0 }, uSky: { value: 0 }, uCut: { value: 1000 },
};
for (let i = 0; i <= MAXR; i++) U.uZone.value.push(new THREE.Vector4(0, 0, -1, 0));
for (let i = 0; i < MAXR; i++) {
  const r = ROOMS[i];
  U.uRect.value.push(r ? new THREE.Vector4(r.x[0] - CX, r.x[1] - CX, CY - r.y[1], CY - r.y[0]) : new THREE.Vector4(0, 0, 0, 0));
}
const SK_GLSL = /* glsl */`
uniform vec4 uRect[${MAXR}]; uniform vec4 uZone[${MAXR + 1}]; uniform int uCount; uniform float uWipe; uniform float uInk; uniform float uSky; uniform float uCut;
void skAmount(vec3 p, out float s, out float band) {
  vec4 z = uZone[${MAXR}];
  for (int i = 0; i < ${MAXR}; i++) { if (i >= uCount) break; vec4 r = uRect[i]; if (p.x > r.x && p.x < r.y && p.z > r.z && p.z < r.w) z = uZone[i]; }
  float d = distance(p.xz, z.xy);
  float r = smoothstep(z.z - 0.3, z.z + 0.3, d);
  float on = step(-500.0, uWipe);
  float w = on * (1.0 - smoothstep(uWipe - 0.03, uWipe + 0.03, p.x));
  s = max(r, w);
  float b1 = (1.0 - smoothstep(0.0, 0.14, abs(d - z.z))) * step(0.0, z.z) * z.w * (1.0 - w);
  float b2 = on * (1.0 - smoothstep(0.0, 0.07, abs(p.x - uWipe)));
  band = max(b1, b2);
}
`;
const ORANGE = 'vec3(1.0, 0.42, 0.12)';
function sketchify(mat, mode = 'surface') {
  if (mat.userData.sk) return;
  mat.userData.sk = true;
  mat.onBeforeCompile = sh => {
    Object.assign(sh.uniforms, U);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vWP;')
      .replace('#include <project_vertex>', '#include <project_vertex>\nvWP = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    const body = mode === 'plan'
      ? `float s, band; skAmount(vWP, s, band); gl_FragColor.a *= s;`
      : `if (vWP.y > uCut) discard;
         float s, band; skAmount(vWP, s, band);
         float lum = dot(gl_FragColor.rgb, vec3(0.299, 0.587, 0.114));
         vec3 paper = vec3(0.955, 0.945, 0.918) * (0.84 + 0.18 * clamp(lum * 1.5, 0.0, 1.0));
         gl_FragColor.rgb = mix(gl_FragColor.rgb, paper, s);
         gl_FragColor.rgb = mix(gl_FragColor.rgb, ${ORANGE}, band * 0.55);`;
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vWP;\n' + SK_GLSL)
      .replace('#include <dithering_fragment>', '#include <dithering_fragment>\n' + body);
  };
  mat.customProgramCacheKey = () => 'sk-' + mode;
  mat.polygonOffset = true; mat.polygonOffsetFactor = 1; mat.polygonOffsetUnits = 1;
}
const inkMat = new THREE.ShaderMaterial({
  uniforms: U, transparent: true, depthWrite: false,
  vertexShader: `varying vec3 vWP; void main(){ vec4 wp = modelMatrix * vec4(position, 1.0); vWP = wp.xyz; gl_Position = projectionMatrix * viewMatrix * wp; }`,
  fragmentShader: `varying vec3 vWP;\n${SK_GLSL}\nvoid main(){ if (vWP.y > uCut) discard; float s, band; skAmount(vWP, s, band);
    vec3 c = mix(vec3(0.13, 0.12, 0.11), ${ORANGE}, band);
    float a = max(s * uInk * 0.85, band * 0.95 * uInk);
    if (a < 0.01) discard; gl_FragColor = vec4(c, a); }`,
});
function ink(root, angle = 30) {
  root.traverse(n => {
    if (!n.isMesh || n.userData.noInk) return;
    const tris = (n.geometry.index ? n.geometry.index.count : n.geometry.attributes.position.count) / 3;
    if (tris > 250000) return;                              // very heavy pieces stay without pencil lines
    const l = new THREE.LineSegments(new THREE.EdgesGeometry(n.geometry, angle), inkMat);
    l.raycast = () => {};
    n.add(l);
  });
}

// ---------- sky, fog, light ----------
const sky = new THREE.Mesh(new THREE.SphereGeometry(200, 32, 16), new THREE.ShaderMaterial({
  side: THREE.BackSide, depthWrite: false, uniforms: U,
  vertexShader: `varying vec3 vD; void main(){ vD = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `uniform float uSky; varying vec3 vD; void main(){
    float h = clamp(vD.y, 0.0, 1.0);
    vec3 real = mix(vec3(0.93, 0.86, 0.76), vec3(0.47, 0.66, 0.86), pow(h, 0.55));
    gl_FragColor = vec4(mix(vec3(0.955, 0.945, 0.918), real, uSky), 1.0); }`,
}));
scene.add(sky);
const FOG_PAPER = new THREE.Color(0.955, 0.945, 0.918), FOG_REAL = new THREE.Color(0.86, 0.85, 0.80);
scene.fog = new THREE.Fog(FOG_PAPER.clone(), 3.5 * S + 10, 12 * S + 40);
scene.add(new THREE.HemisphereLight('#fff8ee', '#a99f8a', 0.9));
{ const pm = new THREE.PMREMGenerator(renderer); ENV.mapping = THREE.EquirectangularReflectionMapping; scene.environment = pm.fromEquirectangular(ENV).texture; scene.environmentIntensity = 0.45; pm.dispose(); }
const sun = new THREE.DirectionalLight('#ffeacc', 2.6);
sun.position.set(-0.8 * S, 1.4 * S, S);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
const R = S * 0.9 + 4;
Object.assign(sun.shadow.camera, { left: -R, right: R, top: R, bottom: -R, near: 1, far: 6 * S + 20 });
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03;
scene.add(sun);

// ---------- site: lawn, path to the door, a few trees ----------
function flat(w, d, mat, x, y, h = 0, rot = 0) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat);
  m.rotation.x = -Math.PI / 2; m.rotation.z = rot; m.position.copy(W(x, y, h)); m.receiveShadow = true; m.userData.noInk = true;
  scene.add(m); return m;
}
const pt = (k, rx, ry, rot = 0) => { const t = PT[k].clone(); t.needsUpdate = true; t.repeat.set(rx, ry); t.rotation = rot; return t; };
const ground = new THREE.Mesh(new THREE.CircleGeometry(12 * S + 40, 64), new THREE.MeshStandardMaterial({ map: pt('grass', 7 * S, 7 * S), color: '#c9dcae', roughness: 1 }));
ground.rotation.x = -Math.PI / 2; ground.position.y = -0.03; ground.receiveShadow = true; ground.userData.noInk = true;
scene.add(ground);
{ const len = 7, pc = [ent.x + OUT.x * len / 2, ent.y + OUT.y * len / 2];
  flat(1.2, len, new THREE.MeshStandardMaterial({ map: pt('paving', 0.6, 3.5), roughness: 0.95 }), pc[0], pc[1], 0.0, OUT.x ? Math.PI / 2 : 0); }
const matCache = {};
const std = (c, extra) => matCache[c + JSON.stringify(extra || {})] ||= new THREE.MeshStandardMaterial({ color: c, roughness: 0.75, ...extra });
function cyl(g, rt, rb, h, x, y, z, c, seg = 16) { const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), std(c)); m.position.set(x, y + h / 2, z); m.castShadow = m.receiveShadow = true; g.add(m); return m; }
function tree(sc) {
  const g = new THREE.Group(); cyl(g, 0.12 * sc, 0.2 * sc, 2.2 * sc, 0, 0, 0, '#6b5038', 8);
  const leaf = std('#5d7a3e', { flatShading: true });
  for (const [x, y, z, r] of [[0, 2.6, 0, 1.3], [0.7, 2.3, 0.3, 0.9], [-0.6, 2.4, -0.4, 1.0], [0.1, 3.3, -0.2, 0.9]]) {
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(r * sc, 0), leaf); m.position.set(x * sc, y * sc, z * sc); m.castShadow = m.receiveShadow = true; g.add(m);
  }
  return g;
}
function cypress(sc) { const g = new THREE.Group(); const m = new THREE.Mesh(new THREE.ConeGeometry(0.55 * sc, 4.5 * sc, 7), std('#3f5a33', { flatShading: true })); m.position.y = 2.4 * sc; m.castShadow = true; g.add(m); cyl(g, 0.08, 0.1, 0.3, 0, 0, 0, '#5a4330', 6); return g; }
const garden = [];
{ // trees at the corners and along the back, kept clear of the path to the front door
  const m = 3.2, spots = [[-m, -m, 1.1, 0], [SW + m, -m, 0.9, 1], [-m, SD + m, 1.2, 0], [SW + m, SD + m, 1.3, 0], [SW / 2, -m - 1, 1, 1], [SW / 2, SD + m + 0.5, 1.1, 1], [-m - 0.5, SD / 2, 0.9, 1], [SW + m + 0.5, SD / 2, 1, 1]];
  for (const [x, y, sc, kind] of spots) {
    if (Math.hypot(x - (ent.x + OUT.x * 4), y - (ent.y + OUT.y * 4)) < 4.5) continue;
    const t = kind ? cypress(sc) : tree(sc); t.position.copy(W(x, y)); scene.add(t); garden.push(t);
  }
}

// ---------- the house itself: a model (OBJ) or walls raised from plan data ----------
const walls = [];          // groups that rise
const ceilings = [];       // ceiling planes and room lights (shown only once you are inside)
const glassMat = new THREE.MeshPhysicalMaterial({ color: '#b7d7ea', roughness: 0.04, transparent: true, opacity: 0.22 });
if (model) {
  model.position.set(-CX, 0, CY);
  if (DES && DES.recolour) paintModel(model);
  const g = new THREE.Group(); g.add(model); g.scale.y = 0.001; scene.add(g); walls.push(g);
} else if (PLAN) {
  const DH = PLAN.door_height || 2.1, WS = PLAN.window_sill || 0.9, WH = PLAN.window_head || 2.1;
  const slab = new THREE.Mesh(new THREE.BoxGeometry(SW + 0.5, 0.16, SD + 0.5), new THREE.MeshStandardMaterial({ color: '#cfc7b8', roughness: 1 }));
  slab.position.set(0, -0.07, 0); slab.receiveShadow = true; scene.add(slab);
  const ceilMat = new THREE.MeshStandardMaterial({ color: '#f6f3ee', roughness: 1 });
  // the tour's rooms, the other rectangles of an L-shaped room (part_of), and the outside spaces (paving)
  const extra = (PLAN.rooms || []).filter(r => r.part_of || r.outside);
  for (const r of [...ROOMS, ...extra]) {
    const w = r.x[1] - r.x[0], d = r.y[1] - r.y[0], [cx, cy] = rc(r);
    if (r.outside) { flat(w, d, new THREE.MeshStandardMaterial({ map: pt('stone', w / 1.2, d / 1.2), color: '#e4ddd0', roughness: 0.8 }), cx, cy, 0.012); continue; }
    const main = r.part_of ? (ROOMS.find(m => m.name === r.part_of) || r) : r;
    const tile = /bath|shower|toilet|wc|laundry|scullery/i.test(r.name) || r.floor === 'tile';
    const fl = RD(main) && RD(main).floor, kind = fl ? fl.material : (tile ? 'tile' : 'wood');
    const tint = fl ? new THREE.Color(fl.hex).lerp(new THREE.Color('#ffffff'), 0.3) : new THREE.Color('#ffffff');
    const fm = kind === 'carpet' || kind === 'concrete' ? new THREE.MeshStandardMaterial({ color: fl.hex, roughness: kind === 'carpet' ? 1 : 0.7 })
      : kind === 'stone' || kind === 'tile' ? new THREE.MeshStandardMaterial({ map: pt('stone', w / 1.6, d / 1.6), color: tint, roughness: 0.5 })
      : new THREE.MeshStandardMaterial({ map: pt('laminate', w / 2.2, d / 2.2, Math.PI / 2), normalMap: pt('laminateN', w / 2.2, d / 2.2, Math.PI / 2), color: tint, roughness: 0.55 });
    flat(w, d, fm, cx, cy, 0.022);
    const c = new THREE.Mesh(new THREE.PlaneGeometry(w, d), ceilMat);
    c.rotation.x = Math.PI / 2; c.position.copy(W(cx, cy, H)); c.userData.noInk = true; c.visible = false;
    scene.add(c); ceilings.push(c);
  }
  const wallMat = new THREE.MeshStandardMaterial({ color: (DES && DES.walls) || '#f1ede5', roughness: 0.92 });
  const capMat = new THREE.MeshStandardMaterial({ color: '#3a3836', roughness: 0.8 });
  const frameMat = new THREE.MeshStandardMaterial({ color: '#2f2f33', roughness: 0.5 });
  const wallMats = [wallMat, wallMat, capMat, wallMat, wallMat, wallMat];
  for (const wall of PLAN.walls) {
    const [ax, ay] = wall.a, [bx, by] = wall.b, L = Math.hypot(bx - ax, by - ay), t0 = wall.t || 0.15;
    const grp = new THREE.Group(), a = W(ax, ay), b = W(bx, by);
    grp.position.copy(a); grp.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
    const box = (s0, s1, y0, y1, mat = wallMats, t = t0, noInk = false) => {
      if (s1 - s0 < 1e-3 || y1 - y0 < 1e-3) return;
      const m = new THREE.Mesh(new THREE.BoxGeometry(s1 - s0, y1 - y0, t), mat);
      m.position.set((s0 + s1) / 2, (y0 + y1) / 2, 0); m.castShadow = m.receiveShadow = mat !== glassMat; m.userData.noInk = noInk; grp.add(m);
    };
    const ops = (PLAN.openings || []).filter(o => o.wall === wall.id).sort((p, q) => p.from - q.from);
    let s = -t0 / 2;
    for (const o of ops) {
      box(s, o.from, 0, H);
      if (o.kind === 'window') { box(o.from, o.to, 0, WS); box(o.from, o.to, WH, H); box(o.from, o.to, WS, WH, glassMat, 0.02, true); box(o.from, o.to, WS - 0.03, WS, frameMat, t0 + 0.02); }
      else if (o.kind === 'garage') { const top = Math.min(H - 0.1, 2.3); box(o.from, o.to, top, H); box(o.from, o.to, top - 0.28, top, frameMat, t0 * 0.7); }   // rolled up under its lintel
      else if (o.kind === 'sliding') { box(o.from, o.to, DH, H); box(o.from, (o.from + o.to) / 2, 0, DH, glassMat, 0.02, true); box(o.from, o.from + 0.04, 0, DH, frameMat, t0 * 0.5); }
      else if (o.kind !== 'opening') box(o.from, o.to, DH, H);   // a door (or an opening: nothing over it)
      s = o.to;
    }
    box(s, L + t0 / 2, 0, H);
    grp.scale.y = 0.001; scene.add(grp); walls.push(grp);
  }
}
ROOMS.forEach((r, i) => {
  const [cx, cy] = rc(r);
  const pl = new THREE.PointLight('#ffe2bd', 0, 7, 1.6);
  pl.position.copy(W(cx, cy, Math.min(H - 0.25, 2.35))); pl.userData.full = 3.0; pl.userData.room = Math.min(i, MAXR); scene.add(pl); ceilings.push(pl);
});

// ---------- furniture from the designer (the plan's items: one source of truth) ----------
const furn = [];
if (DES && DES.furnish) {
  let lamps = 0;
  ROOMS.forEach((r, i) => {
    const rd = RD(r); if (!rd || !rd.items) return;
    const pal = { ...PAL }; (rd.palette || []).forEach(p => { pal[p.use] = pal[p.use] || p.hex; });
    for (const it of rd.items) {
      const { group, light } = makeItem(it, H, pal);
      group.position.copy(W(it.x, it.y)); group.scale.y = 0.001; scene.add(group); furn.push(group);
      if (light && lamps < 6) {           // layered light: a few warm lamps, lit when you are in their room
        const pl = new THREE.PointLight('#ffd49a', 0, 3.2, 1.8); pl.position.copy(W(it.x, it.y, light.y));
        pl.userData.full = light.full; pl.userData.room = Math.min(i, MAXR); scene.add(pl); ceilings.push(pl); lamps++;
      }
    }
  });
}
// A Sweet Home 3D model painted in the house palette: walls in the wall colour, floors in each room's floor colour.
function paintModel(root) {
  const box3 = new THREE.Box3(), mid = new THREE.Vector3();
  root.updateMatrixWorld(true);
  root.traverse(n => {
    if (!n.isMesh) return;
    box3.setFromObject(n); box3.getCenter(mid);
    const px = mid.x + CX, py = CY - mid.z;           // back to plan metres (the model sits at -CX, CY)
    const room = ROOMS.find(r => px > r.x[0] && px < r.x[1] && py > r.y[0] && py < r.y[1]);
    const paint = (m) => {
      const name = `${n.name} ${m.name || ''}`.toLowerCase();
      let hex = null;
      if (/wall/.test(name)) hex = (room && RD(room) && RD(room).walls) || DES.walls;
      else if (/floor|room|ground/.test(name) && box3.max.y < 0.2 && room && RD(room) && RD(room).floor) hex = RD(room).floor.hex;
      if (!hex) return m;
      const c = m.clone(); c.color = new THREE.Color(hex); if (c.map) c.color.lerp(new THREE.Color('#ffffff'), 0.35); return c;
    };
    n.material = Array.isArray(n.material) ? n.material.map(paint) : paint(n.material);
  });
}

// ---------- the flat plan, drawn as an architect's sheet ----------
const PM = Math.max(2.4, S * 0.24), PX = Math.min(140, 4000 / (S + 2 * PM));
function planCanvas() {
  const w = Math.round((SW + PM * 2) * PX), h = Math.round((SD + PM * 2) * PX);
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const g = c.getContext('2d');
  const P = (x, y) => [(x + PM) * PX, h - (y + PM) * PX];
  const f = PX / 140;                                       // type scales with the sheet
  g.fillStyle = '#f4f1ea'; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 4000; i++) { g.fillStyle = `rgba(80,70,50,${Math.random() * 0.05})`; g.fillRect(Math.random() * w, Math.random() * h, 2, 2); }
  g.strokeStyle = 'rgba(60,60,60,0.07)'; g.lineWidth = 1;
  for (let x = 0; x <= w; x += PX / 2) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
  for (let y = 0; y <= h; y += PX / 2) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
  // walls: the plan's own walls and openings, or the model cut through at window height
  if (PLAN) {
    for (const wall of PLAN.walls) {
      const [ax0, ay0] = wall.a, [bx, by] = wall.b, t0 = wall.t || 0.15;
      const L = Math.hypot(bx - ax0, by - ay0), ux = (bx - ax0) / L, uy = (by - ay0) / L;
      const ops = (PLAN.openings || []).filter(o => o.wall === wall.id).sort((a, b) => a.from - b.from);
      const at = s => [ax0 + ux * s, ay0 + uy * s];
      const seg = (s0, s1) => { const [p0x, p0y] = P(...at(s0)), [p1x, p1y] = P(...at(s1)); g.strokeStyle = '#1c1b1a'; g.lineWidth = t0 * PX; g.lineCap = 'butt'; g.beginPath(); g.moveTo(p0x, p0y); g.lineTo(p1x, p1y); g.stroke(); };
      let s = -t0 / 2;
      for (const o of ops) { seg(s, o.from); s = o.to; }
      seg(s, L + t0 / 2);
      for (const o of ops) {
        if (o.kind !== 'window') continue;
        const nx = -uy, ny = ux, off = t0 / 3;
        for (const k of [-1, 0, 1]) {
          const [q0x, q0y] = P(...at(o.from).map((v, i) => v + (i ? ny : nx) * off * k)), [q1x, q1y] = P(...at(o.to).map((v, i) => v + (i ? ny : nx) * off * k));
          g.strokeStyle = '#222'; g.lineWidth = 2; g.beginPath(); g.moveTo(q0x, q0y); g.lineTo(q1x, q1y); g.stroke();
        }
      }
    }
  }
  if (D.lines) {
    g.strokeStyle = '#1c1b1a'; g.lineWidth = Math.max(2, 2.6 * f); g.lineCap = 'round';
    g.beginPath();
    for (const [x0, y0, x1, y1] of D.lines) { const [a, b] = P(x0, y0), [c2, d2] = P(x1, y1); g.moveTo(a, b); g.lineTo(c2, d2); }
    g.stroke();
  }
  // outside spaces: a dashed edge and their name, smaller
  g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const r of (PLAN && PLAN.rooms || []).filter(r => r.outside)) {
    const [a, b] = P(r.x[0], r.y[1]), [c2, d2] = P(r.x[1], r.y[0]);
    g.save(); g.setLineDash([8 * f, 6 * f]); g.strokeStyle = '#9a9286'; g.lineWidth = 1.5; g.strokeRect(a, b, c2 - a, d2 - b); g.restore();
    g.fillStyle = '#8a8378'; g.font = `italic ${Math.max(11, 18 * f)}px "Courier New", monospace`; g.fillText(r.name, (a + c2) / 2, (b + d2) / 2);
  }
  // rooms: big spaced names, written like on a drawing
  for (const r of ROOMS) {
    const [cx, cy] = P(...rc(r)), wd = r.x[1] - r.x[0], dp = r.y[1] - r.y[0];
    const size = Math.max(14, Math.min(34 * f, (wd * PX) / Math.max(6, r.name.length) * 1.1));
    g.fillStyle = '#2a2826'; g.font = `700 ${size}px "Courier New", monospace`;
    if ('letterSpacing' in g) g.letterSpacing = `${Math.round(size / 6)}px`;
    g.fillText(r.name.toUpperCase(), cx, cy - size * 0.3);
    if ('letterSpacing' in g) g.letterSpacing = '1px';
    g.fillStyle = '#6b655c'; g.font = `${Math.max(11, 20 * f)}px "Courier New", monospace`;
    g.fillText(`${(wd * dp).toFixed(1)} m²  ·  ${wd.toFixed(2)} × ${dp.toFixed(2)}`, cx, cy + size * 0.75);
  }
  if ('letterSpacing' in g) g.letterSpacing = '0px';
  // overall dimensions
  g.strokeStyle = '#333'; g.fillStyle = '#333'; g.lineWidth = 1.5; g.font = `${Math.max(12, 20 * f)}px "Courier New", monospace`;
  const tick = (px, py) => { g.beginPath(); g.moveTo(px - 8, py + 8); g.lineTo(px + 8, py - 8); g.stroke(); };
  { const [x0, py] = P(0, -PM * 0.4), [x1] = P(SW, 0); g.beginPath(); g.moveTo(x0, py); g.lineTo(x1, py); g.stroke(); tick(x0, py); tick(x1, py); g.fillText(SW.toFixed(2), (x0 + x1) / 2, py - 16 * f - 4); }
  { const [px, y0] = P(SW + PM * 0.4, 0), [, y1] = P(0, SD); g.beginPath(); g.moveTo(px, y0); g.lineTo(px, y1); g.stroke(); tick(px, y0); tick(px, y1); g.save(); g.translate(px - 16 * f - 4, (y0 + y1) / 2); g.rotate(-Math.PI / 2); g.fillText(SD.toFixed(2), 0, 0); g.restore(); }
  // north arrow and title
  const [nx, ny] = P(SW + PM * 0.55, SD + PM * 0.55), nr = 30 * f;
  g.strokeStyle = '#222'; g.lineWidth = 2; g.beginPath(); g.arc(nx, ny, nr, 0, Math.PI * 2); g.stroke();
  g.fillStyle = '#222'; g.beginPath(); g.moveTo(nx, ny - nr * 0.86); g.lineTo(nx + nr / 3, ny + nr * 0.4); g.lineTo(nx, ny + nr / 6); g.lineTo(nx - nr / 3, ny + nr * 0.4); g.fill();
  g.font = `700 ${Math.max(12, 22 * f)}px "Courier New", monospace`; g.fillText('N', nx, ny - nr * 1.45);
  g.textAlign = 'left'; g.fillText('GROUND FLOOR PLAN', P(0, SD + PM * 0.62)[0], P(0, SD + PM * 0.62)[1]);
  g.font = `${Math.max(11, 18 * f)}px "Courier New", monospace`; g.fillStyle = '#6b655c'; g.fillText('ALL DIMENSIONS IN METRES', P(0, SD + PM * 0.45)[0], P(0, SD + PM * 0.45)[1]);
  return c;
}
const planTex = new THREE.CanvasTexture(planCanvas());
planTex.colorSpace = THREE.SRGBColorSpace;
planTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
const plan = new THREE.Mesh(new THREE.PlaneGeometry(SW + PM * 2, SD + PM * 2), new THREE.MeshBasicMaterial({ map: planTex, transparent: true, toneMapped: false, depthWrite: false }));
plan.rotation.x = -Math.PI / 2; plan.position.y = 0.032; plan.renderOrder = 2; plan.userData.noInk = true; plan.userData.planMode = true;
scene.add(plan);

// ---------- pencil lines + sketch shading everywhere ----------
walls.forEach(w => ink(w));
furn.forEach(f => ink(f, 35));
garden.forEach(f => ink(f, 35));
scene.traverse(n => {
  if (!n.isMesh || n === sky) return;
  (Array.isArray(n.material) ? n.material : [n.material]).forEach(m => sketchify(m, n.userData.planMode ? 'plan' : 'surface'));
});

// ---------- camera path, worked out from the rooms ----------
const V = (x, y, h = EYE) => W(x, y, h);
const KF = [], STEPS = [], CARDS = [], VEILS = [];   // VEILS: [from, to, photo] the room's photo fades in at its stop
function key(t, p, l, o = {}) { KF.push({ t, p: p.clone(), l: l.clone(), fov: o.fov ?? 60, k: o.k ?? 0, sx: o.sx ?? 0, hold: !!o.hold }); }
const holdAt = (t0, t1, p0, p1, l0, l1, card, o = {}) => { key(t0, p0, l0, { ...o, hold: true }); key(t1, p1, l1, { ...o, hold: true }); STEPS.push([t0, t1]); CARDS.push(card); };
const heroH = 1.3 * Math.max(SW + PM * 2, (SD + PM * 2) * 1.25);
const HERO_P = new THREE.Vector3(0, heroH, 0.01), HERO_L = new THREE.Vector3(0, 0, 0), MID = W(CX, CY, 0);
const tlReveal = [];       // [zone, x, y, from, to, at, dur]
holdAt(0, 0.8, HERO_P, HERO_P, HERO_L, HERO_L, { kind: 'hero' }, { fov: 40, k: 1, sx: 1 });
const riseP0 = along(S * 0.85, S * 0.8), riseP1 = along(S * 0.9, S * 0.72);
holdAt(2.0, 2.7, riseP0, riseP1, MID, W(CX, CY, 0.2), { kind: 'walls' }, { fov: 46, k: 0.6 });
const inn = (k, h) => W(ent.x - OUT.x * k, ent.y - OUT.y * k, h);
holdAt(3.8, 4.6, along(6.2), along(5.4), inn(2.0, 1.5), inn(2.0, 1.5), { kind: 'door' }, { fov: 58 });
key(5.6, along(0.6), inn(3.0, 1.4));
tlReveal.push([MAXR, ent.x + OUT.x * 0.3, ent.y + OUT.y * 0.3, -1, 5.5, 3.5, 0.9]);
const inside = (r, x, y) => x > r.x[0] && x < r.x[1] && y > r.y[0] && y < r.y[1];
let prev = [ent.x - OUT.x * 0.6, ent.y - OUT.y * 0.6], T = 6.4;
// the outdoors' circle (and with it the hall, garage and any room you don't name) grows with each room you reach
let outR = 5.5;
const farFromDoor = r => Math.max(...[[r.x[0], r.y[0]], [r.x[1], r.y[0]], [r.x[0], r.y[1]], [r.x[1], r.y[1]]].map(([x, y]) => Math.hypot(x - ent.x - OUT.x * 0.3, y - ent.y - OUT.y * 0.3)));
ROOMS.forEach((r, i) => {
  const w = r.x[1] - r.x[0], d = r.y[1] - r.y[0], [cx, cy] = rc(r);
  const ins = Math.max(0.35, Math.min(0.6, 0.25 * Math.min(w, d)));
  const corners = [[r.x[0] + ins, r.y[0] + ins], [r.x[1] - ins, r.y[0] + ins], [r.x[0] + ins, r.y[1] - ins], [r.x[1] - ins, r.y[1] - ins]];
  // stand in the corner nearest to where you came from (the doorway, as the designer's photo is taken) and look at
  // the room's furniture (Faiek, 2026-11-24: the camera looked into an empty corner while the units stood behind it)
  const rdi = DES && DES.furnish && RD(r);
  const things = ((rdi && rdi.items) || []).filter(it => !['pendant', 'art'].includes(it.kind));
  const aim = things.length ? [things.reduce((s, it) => s + it.x, 0) / things.length, things.reduce((s, it) => s + it.y, 0) / things.length] : null;
  corners.sort((a, b) => Math.hypot(a[0] - prev[0], a[1] - prev[1]) - Math.hypot(b[0] - prev[0], b[1] - prev[1]));
  const diag = Math.hypot(w, d), gap = c => aim ? Math.hypot(c[0] - aim[0], c[1] - aim[1]) : diag;
  let stand = corners.find(c => gap(c) >= 0.42 * diag) || corners.slice().sort((a, b) => gap(b) - gap(a))[0];
  if (i === 0 && inside(r, prev[0], prev[1]) && gap(prev) >= 0.42 * diag) stand = prev;
  let far = [cx + (cx - stand[0]) * 0.6, cy + (cy - stand[1]) * 0.6];
  if (aim) { const k = Math.max(1, 1.2 / Math.max(0.3, gap(stand))); far = [stand[0] + (aim[0] - stand[0]) * k, stand[1] + (aim[1] - stand[1]) * k]; }
  const drift = [stand[0] + (far[0] - stand[0]) * 0.04, stand[1] + (far[1] - stand[1]) * 0.04];
  if (i > 0) {
    // calm: the same speed for the same distance, one movement at a time (rise, glide, settle), no quick turns
    const hop = Math.hypot(stand[0] - prev[0], stand[1] - prev[1]);
    T += Math.min(2.2, hop * 0.18);
    key(T - 1.5, V(prev[0], prev[1], H + 1.6), V(cx, cy, 0));
    key(T - 0.8, V((prev[0] + stand[0]) / 2, (prev[1] + stand[1]) / 2, H + 2.2), V(cx, cy, 0));
    key(T - 0.3, V(stand[0], stand[1], H + 0.8), V(far[0], far[1], 0.6));
    tlReveal.push([Math.min(i, MAXR), stand[0], stand[1], -1, Math.hypot(w, d) + 1, T - 0.6, 1.0]);
  } else {
    tlReveal.push([0, stand[0], stand[1], -1, Math.hypot(w, d) + 1, 5.3, 1.1]);
  }
  holdAt(T, T + 0.8, V(stand[0], stand[1]), V(drift[0], drift[1]), V(far[0], far[1], aim ? 0.7 : 0.9), V(far[0], far[1], aim ? 0.7 : 0.9), { kind: 'room', room: r, n: i });
  const rdp = RD(r);
  if (rdp && rdp.photo && D.photo_walk !== false) VEILS.push([T, T + 0.8, rdp.photo]);
  const reach = farFromDoor(r) + 0.5;
  if (reach > outR) { tlReveal.push([MAXR, ent.x + OUT.x * 0.3, ent.y + OUT.y * 0.3, outR, reach, T - 0.6, 1.0]); outR = reach; }
  prev = stand; T += 3.0;
});
if (!ROOMS.length) T = 7.0;
const lift = T - 1.6;                     // after the last room's hold ends (T - 3.0 + 0.8), never on it
key(lift, V(prev[0], prev[1], H + 2.5), MID);
key(lift + 1.1, along(S * 0.9, S * 0.9), MID, { fov: 42, k: 1 });
const aerialH = 1.45 * Math.max(SW + PM * 2, (SD + PM * 2) * 1.25);
const AER = new THREE.Vector3(0, aerialH, 0.02), AERL = new THREE.Vector3(0, 0, 0);
const tA = lift + 2.3;
holdAt(tA, tA + 0.7, AER, AER, AERL, AERL, { kind: 'aerial' }, { fov: 40, k: 1 });
holdAt(tA + 1.8, tA + 2.6, AER, AER, AERL, AERL, { kind: 'end' }, { fov: 40, k: 1 });
tlReveal.push([MAXR, ent.x + OUT.x * 0.3, ent.y + OUT.y * 0.3, outR, 8 * S + 30, lift, 1.6]);
KF.sort((a, b) => a.t - b.t);
const END = tA + 2.6;

const FIELDS = ['p', 'l'], SCAL = ['fov', 'k', 'sx'];
KF.forEach((f, i) => {
  const a = KF[i - 1], b = KF[i + 1];
  f.m = {};
  for (const n of FIELDS) f.m[n] = (f.hold || !a || !b) ? new THREE.Vector3() : b[n].clone().sub(a[n]).divideScalar(b.t - a.t);
  for (const n of SCAL) f.m[n] = (f.hold || !a || !b) ? 0 : (b[n] - a[n]) / (b.t - a.t);
});
const hermite = u => [2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2];
const camState = { p: new THREE.Vector3(), l: new THREE.Vector3(), fov: 40, k: 1, sx: 1 };
function camAt(t) {
  let i = 0;
  while (i < KF.length - 2 && t > KF[i + 1].t) i++;
  const a = KF[i], b = KF[i + 1], h = b.t - a.t;
  const u = THREE.MathUtils.clamp((t - a.t) / h, 0, 1);
  const [h00, h10, h01, h11] = hermite(u);
  for (const n of FIELDS) camState[n].copy(a[n]).multiplyScalar(h00).addScaledVector(a.m[n], h10 * h).addScaledVector(b[n], h01).addScaledVector(b.m[n], h11 * h);
  for (const n of SCAL) camState[n] = a[n] * h00 + a.m[n] * h10 * h + b[n] * h01 + b.m[n] * h11 * h;
  return camState;
}

// ---------- captions and progress dots, written from the house data ----------
const area = ROOMS.reduce((s, r) => s + (r.x[1] - r.x[0]) * (r.y[1] - r.y[0]), 0);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const title = D.title || 'The house';
document.title = title;
document.getElementById('pill').textContent = area ? `${title} · ${Math.round(area)} m²` : title;
const caps = document.getElementById('caps'), dotsNav = document.getElementById('dots');
const two = n => String(n).padStart(2, '0');
CARDS.forEach((c, k) => {
  let card, label;
  if (c.kind === 'hero') {
    card = el('div', 'cap hero');
    const h1 = el('h1'); h1.append('Every home starts on ', el('em', null, 'paper.')); card.append(h1);
    card.append(el('p', null, D.subtitle || `${ROOMS.length} room${ROOMS.length === 1 ? '' : 's'}, ${SW.toFixed(1)} by ${SD.toFixed(1)} metres. Scroll and the drawing stands up, then walk in through the front door.`));
    const tb = el('div', 'titleblock');
    for (const [a, b] of [['PROJECT', title], ['SHEET', 'Ground floor'], ['SIZE', `${SW.toFixed(2)} × ${SD.toFixed(2)} m`], ['ROOMS', String(ROOMS.length)]]) { const d = el('div'); d.append(el('b', null, a), b); tb.append(d); }
    card.append(tb); label = 'Plan';
  } else if (c.kind === 'end') {
    card = el('div', 'cap end'); card.append(el('h2', null, 'Plan → home'), el('p', null, 'Left: the drawing. Right: the house. Drag across the picture to compare.'));
    const b = el('button', null, '↑ Walk it again'); b.id = 'restart'; card.append(b); label = 'Compare';
  } else {
    card = el('div', 'cap room');
    let small, h2, p;
    if (c.kind === 'walls') { small = '01 · The drawing stands up'; h2 = 'Walls from lines'; p = `Every line on the plan becomes a wall, ${H.toFixed(1)} m tall.`; label = 'Walls'; }
    else if (c.kind === 'door') { small = '02 · Arrive'; h2 = 'The front door'; p = 'The outside comes to life first. Step through and each room wakes up as you enter it.'; label = 'Front door'; }
    else if (c.kind === 'aerial') { small = `${two(k - 1)} · From above`; h2 = 'The whole home'; p = D.aerial_note || 'The house and garden, seen from the sky.'; label = 'Aerial'; }
    else { const r = c.room, wd = r.x[1] - r.x[0], dp = r.y[1] - r.y[0]; small = `${two(k - 1)} · ${(wd * dp).toFixed(1)} m² · ${wd.toFixed(2)} × ${dp.toFixed(2)}`; h2 = r.name; p = r.note || ''; label = r.name; }
    card.append(el('small', null, small), el('h2', null, h2)); if (p) card.append(el('p', null, p));
    const rd = c.kind === 'room' && RD(c.room);
    if (rd && (rd.photo || (rd.palette || []).length)) {          // the mood board: the designer's photo and its palette
      const mb = el('div', 'mood');
      if (rd.photo) { const img = el('img'); img.src = rd.photo; img.alt = `${c.room.name}, as designed`; mb.append(img); }
      const sw = el('div', 'swatches');
      for (const s of (rd.palette || []).slice(0, 5)) { const d = el('div'); const i = el('i'); i.style.background = s.hex; d.append(i, el('span', null, s.name)); sw.append(d); }
      mb.append(sw); card.append(mb); card.classList.add('has-mood');
    }
  }
  caps.append(card);
  const b = el('button'); b.append(el('span', null, label), el('i')); dotsNav.append(b);
});

// ---------- scroll timeline ----------
const state = { wipe: -1000, ceil: 0 };
const clock = { t: 0 };
const tl = gsap.timeline({ paused: true, defaults: { ease: 'power1.inOut' } });
tl.to(clock, { t: END, duration: END, ease: 'none' }, 0);
tl.to(U.uInk, { value: 1, duration: 0.6 }, 0.9);
walls.forEach((w, i) => tl.to(w.scale, { y: 1, duration: 1.0, ease: 'power3.out' }, 1.0 + Math.min(i, 30) * 0.03));
furn.forEach((f, i) => { f.visible = false; tl.to(f.scale, { y: 1, duration: 0.5, ease: 'power2.out', onStart: () => { f.visible = true; }, onReverseComplete: () => { f.visible = false; } }, 1.9 + Math.min(i, 40) * 0.012); });
garden.forEach((f, i) => { f.scale.setScalar(0.001); f.visible = false; tl.to(f.scale, { x: 1, y: 1, z: 1, duration: 0.35, ease: 'back.out(2)', onStart: () => { f.visible = true; }, onReverseComplete: () => { f.visible = false; } }, 1.7 + i * 0.03); });
for (const [zone, x, y, from, to, at, dur] of tlReveal) {
  const c = W(x, y), z = U.uZone.value[zone];
  tl.fromTo(z, { x: c.x, y: c.z, z: from }, { x: c.x, y: c.z, z: to, duration: dur, ease: 'power1.inOut', immediateRender: false }, at);
  tl.fromTo(z, { w: 0 }, { w: 1, duration: 0.15, immediateRender: false }, at);
  tl.fromTo(z, { w: 1 }, { w: 0, duration: 0.3, immediateRender: false }, at + dur - 0.3);
}
tl.to(U.uSky, { value: 1, duration: 1.0 }, 3.9);
tl.to(state, { ceil: 1, duration: 0.01 }, 5.0);
tl.to(state, { ceil: 0, duration: 0.01 }, lift + 0.3);
const WIPE = SW / 2 + PM;
tl.fromTo(state, { wipe: -WIPE }, { wipe: 0, duration: 1.0, ease: 'power2.inOut', immediateRender: false }, tA + 1.0);
tl.set({}, {}, END);
const TOTAL = tl.duration();
const stepTimes = STEPS.map(([a, b]) => (a + b) / 2);
document.getElementById('track').style.height = `${Math.round(TOTAL * 100)}vh`;

const captions = [...document.querySelectorAll('.cap')];
const dots = [...document.querySelectorAll('#dots button')];
const LAST = stepTimes.length - 1;
let active = -1;
function setActive(i) {
  if (i === active) return;
  active = i;
  dots.forEach((d, k) => d.classList.toggle('on', k === i));
  document.body.dataset.step = i;
  document.body.classList.toggle('compare', i === LAST);
  if (!playing) playBtn.querySelector('span').textContent = i === LAST ? 'Play again' : 'Play tour';
}
const stepFor = time => { let i = 0; for (let k = 0; k < STEPS.length; k++) if (time >= STEPS[k][0] - 0.3) i = k; return i; };
const cardFor = time => { for (let k = 0; k < STEPS.length; k++) if (time >= STEPS[k][0] - 0.25 && time <= STEPS[k][1] + 0.25) return k; return -1; };
let activeCard = -2;
function setCard(i) { if (i === activeCard) return; activeCard = i; captions.forEach((c, k) => c.classList.toggle('on', k === i)); }

// ---------- smooth scrolling + ScrollTrigger ----------
const lenis = new Lenis({ lerp: 0.085, smoothWheel: true });
lenis.on('scroll', ScrollTrigger.update);
gsap.ticker.add(time => lenis.raf(time * 1000));
gsap.ticker.lagSmoothing(0);
const st = ScrollTrigger.create({ trigger: '#track', start: 'top top', end: 'bottom bottom', scrub: 1, animation: tl });
const posFor = k => st.start + (st.end - st.start) * Math.min(1, (k === LAST ? TOTAL : stepTimes[k]) / TOTAL);
dots.forEach((d, k) => d.addEventListener('click', () => { setPlaying(false); lenis.scrollTo(posFor(k), { duration: 2.5 }); }));
document.getElementById('restart').addEventListener('click', () => { setPlaying(false); lenis.scrollTo(0, { duration: 2.5 }); });

// ---------- Play button: walks the whole tour at a steady pace, pausing at each room ----------
const playBtn = document.getElementById('play');
const SEC_PER_UNIT = 2.6, HOLD = 2.4;
let playing = false, holdTimer = null, programmatic = false;
function setPlaying(on) {
  playing = on;
  playBtn.classList.toggle('playing', on);
  playBtn.querySelector('span').textContent = on ? 'Pause' : (active === LAST ? 'Play again' : 'Play tour');
  if (!on) { clearTimeout(holdTimer); if (programmatic) { programmatic = false; lenis.stop(); lenis.start(); } }
}
function playFrom(k) {
  if (!playing) return;
  if (k > LAST) { setPlaying(false); return; }
  const there = k === LAST ? TOTAL : stepTimes[k];
  const dur = Math.max(0.6, Math.abs(there - tl.time()) * SEC_PER_UNIT);
  programmatic = true;
  lenis.scrollTo(posFor(k), { duration: dur, easing: x => x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2, lock: false, force: true,
    onComplete: () => { programmatic = false; if (!playing) return; holdTimer = setTimeout(() => playFrom(k + 1), k === LAST ? 0 : HOLD * 1000); } });
}
playBtn.addEventListener('click', () => {
  if (playing) { setPlaying(false); return; }
  setPlaying(true);
  if (active === LAST) { lenis.scrollTo(0, { immediate: true }); setTimeout(() => playFrom(1), 400); }
  else { const cur = stepFor(tl.time()); playFrom(tl.time() < stepTimes[cur] - 0.05 ? cur : cur + 1); }
});
['wheel', 'touchstart', 'keydown'].forEach(ev => addEventListener(ev, e => { if (playing && !(e.target.closest && e.target.closest('#play'))) setPlaying(false); }, { passive: true }));

// ---------- drag the plan/built divider at the end ----------
let manualWipe = null, dragging = false;
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit = new THREE.Vector3();
const wipeAt = e => { ndc.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(ndc, camera); if (ray.ray.intersectPlane(groundPlane, hit)) manualWipe = THREE.MathUtils.clamp(hit.x, -WIPE, WIPE); };
addEventListener('pointerdown', e => { if (active === LAST && !e.target.closest('button')) { dragging = true; wipeAt(e); } });
addEventListener('pointermove', e => { if (dragging) wipeAt(e); });
addEventListener('pointerup', () => { dragging = false; });
lenis.on('scroll', () => { if (!dragging) manualWipe = null; });

// ---------- each room arrives looking like its photo: the designer's photo fades in over the 3D at the stop ----------
const veil = document.getElementById('veil');
let veilSrc = '';
const ramp = (x, a, b) => THREE.MathUtils.clamp((x - a) / (b - a), 0, 1);
function showVeil(t) {
  let o = 0, src = '';
  for (const [a, b, photo] of VEILS) {
    const v = Math.min(ramp(t, a + 0.08, a + 0.32), 1 - ramp(t, b - 0.12, b + 0.12));
    if (v > o) { o = v; src = photo; }
  }
  if (src && src !== veilSrc) { veil.src = src; veilSrc = src; }
  veil.style.opacity = (o * o * (3 - 2 * o)).toFixed(3);
  veil.style.transform = `scale(${(1.04 - 0.04 * o).toFixed(4)})`;
  document.body.classList.toggle('veiled', o > 0.6);
}

// ---------- render loop ----------
let camDist = 1, portrait = false;
function resize() { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); camera.aspect = w / h; portrait = w / h < 1; camDist = portrait ? 0.95 / (w / h) : 1; }
addEventListener('resize', resize);
resize();
const look = new THREE.Vector3();
const cutOn = !!model;                       // a model's ceilings and roof are cut away whenever you are above them
renderer.setAnimationLoop(() => {
  const cam = camAt(clock.t);
  look.copy(cam.l);
  camera.position.copy(cam.p).sub(look).multiplyScalar(1 + (camDist - 1) * cam.k).add(look);
  camera.lookAt(look);
  camera.fov = cam.fov + (portrait ? 12 : 0);
  const w = innerWidth, h = innerHeight;
  if (portrait) camera.setViewOffset(w, h, 0, h * 0.12 * cam.k, w, h);
  else camera.setViewOffset(w, h, -w * 0.19 * cam.sx, 0, w, h);
  camera.updateProjectionMatrix();
  U.uCut.value = cutOn && camera.position.y > H - 0.15 ? H - 0.05 : 1000;
  U.uWipe.value = manualWipe ?? state.wipe;
  scene.fog.color.copy(FOG_PAPER).lerp(FOG_REAL, U.uSky.value);
  const ceilOn = state.ceil > 0.5;
  ceilings.forEach(c => { if (c.isLight) c.intensity = ceilOn ? c.userData.full * THREE.MathUtils.clamp(U.uZone.value[c.userData.room].z / 3, 0, 1) : 0; else c.visible = ceilOn; });
  walls.forEach(wl => { wl.visible = wl.scale.y > 0.002; });
  plan.visible = U.uZone.value[MAXR].z < 6 * S || U.uWipe.value > -500;
  setActive(stepFor(clock.t));
  setCard(cardFor(clock.t));
  showVeil(clock.t);
  document.getElementById('bar').style.transform = `scaleX(${tl.time() / TOTAL})`;
  renderer.render(scene, camera);
});
document.body.classList.add('ready');
window.__home3d = { setT: t => { tl.time(t); }, STEPS, stepTimes, TOTAL, isPlaying: () => playing, jump: p => lenis.scrollTo(st.start + (st.end - st.start) * p, { immediate: true }) };
}
