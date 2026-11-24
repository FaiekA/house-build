// The furniture cut out of each room's designed photo (Faiek, 2026-11-24: "use images instead of the 3D boxes").
// housedesign.cut_photo marks every piece in the photo: a box ([ymin, xmin, ymax, xmax] in 0-1000) and, when Gemini
// sends one, a mask (a PNG the size of the box, white = the piece). Here each piece becomes a picture with a clear
// background; main.js stands it in the room where that piece is placed. Without a mask the edges are feathered.
import * as THREE from 'three';

const MAX_SIDE = 768;
const FREE = new Set(['dining_table', 'island', 'coffee_table', 'dining_chair', 'desk_chair', 'armchair', 'plant', 'floor_lamp']);                       // px: the longest side of one cut-out texture

const load = src => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; });
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

// one cut-out -> { tex, aspect } or null. `rect`: keep the whole box (art on a wall), no mask, no feathering.
function cutOne(photo, cut, mask, rect, anisotropy) {
  const [y0, x0, y1, x1] = cut.box, W = photo.naturalWidth, H = photo.naturalHeight;
  const sx = x0 / 1000 * W, sy = y0 / 1000 * H, sw = (x1 - x0) / 1000 * W, sh = (y1 - y0) / 1000 * H;
  if (sw < 8 || sh < 8) return null;
  const k = Math.min(1, MAX_SIDE / Math.max(sw, sh));
  const w = Math.max(8, Math.round(sw * k)), h = Math.max(8, Math.round(sh * k));
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(photo, sx, sy, sw, sh, 0, 0, w, h);
  if (!rect) {
    const px = g.getImageData(0, 0, w, h), d = px.data;
    let m = null;
    if (mask) {
      const mc = document.createElement('canvas'); mc.width = w; mc.height = h;
      const mg = mc.getContext('2d', { willReadFrequently: true });
      mg.imageSmoothingQuality = 'high';
      mg.drawImage(mask, 0, 0, w, h);
      m = mg.getImageData(0, 0, w, h).data;
    }
    let top = h, left = w, bottom = -1, right = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      let a;
      if (m) a = smooth(70, 170, (m[i] + m[i + 1] + m[i + 2]) / 3);
      else {                                     // a soft-cornered vignette inside the box
        const u = Math.abs(x / (w - 1) * 2 - 1), v = Math.abs(y / (h - 1) * 2 - 1);
        a = 1 - smooth(0.72, 1, Math.pow(u ** 4 + v ** 4, 0.25));
      }
      d[i + 3] = Math.round(a * 255);
      if (a > 0.08) { if (y < top) top = y; if (y > bottom) bottom = y; if (x < left) left = x; if (x > right) right = x; }
    }
    if (bottom < 0 || (bottom - top) * (right - left) < 64) return null;      // the mask held nothing
    g.putImageData(px, 0, 0);
    // trim to what the mask kept, so the picture's size is the piece's size
    if (top > 0 || left > 0 || bottom < h - 1 || right < w - 1) {
      const tw = right - left + 1, th = bottom - top + 1, t = document.createElement('canvas');
      t.width = tw; t.height = th; t.getContext('2d').drawImage(c, left, top, tw, th, 0, 0, tw, th);
      return finish(t, tw / th, anisotropy);
    }
  }
  return finish(c, w / h, anisotropy);
}
function finish(canvas, aspect, anisotropy) {
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = anisotropy;
  tex.generateMipmaps = true; tex.minFilter = THREE.LinearMipmapLinearFilter;
  return { tex, aspect };
}

// design (the house's design data) -> { room name: [{ kind, tex, aspect }] }. Never throws: a room whose photo or
// masks won't load simply keeps its drawn furniture.
export async function makeCuts(design, anisotropy = 8) {
  const out = {};
  if (!design || !design.rooms) return out;
  for (const [name, rd] of Object.entries(design.rooms)) {
    if (!rd || !rd.photo || !Array.isArray(rd.cuts) || !rd.cuts.length) continue;
    try {
      const photo = await load(rd.photo);
      const list = [];
      for (const cut of rd.cuts) {
        let mask = null;
        if (cut.mask) mask = await load(cut.mask).catch(() => null);
        const made = cutOne(photo, cut, mask, cut.kind === 'art', anisotropy);
        if (made) list.push({ kind: cut.kind, ...made });
      }
      out[name] = list;
    } catch (e) { console.warn('cut-outs for', name, e); }
  }
  return out;
}

const shadowTex = (() => {
  let t = null;
  return () => {
    if (t) return t;
    const c = document.createElement('canvas'); c.width = c.height = 128;
    const g = c.getContext('2d'), r = g.createRadialGradient(64, 64, 4, 64, 64, 64);
    r.addColorStop(0, 'rgba(0,0,0,0.55)'); r.addColorStop(0.6, 'rgba(0,0,0,0.22)'); r.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = r; g.fillRect(0, 0, 128, 128);
    return (t = new THREE.CanvasTexture(c));
  };
})();

// One placed piece shown as its photo cut-out. Standing pieces turn to face you (faceCamera, every frame); art hangs flat on its wall like the drawn frame did. -> THREE.Group, origin on the floor.
export function cutItem(it, cut) {
  const g = new THREE.Group();
  const mat = new THREE.MeshBasicMaterial({ map: cut.tex, transparent: true, alphaTest: 0.35, side: THREE.DoubleSide, toneMapped: false });
  if (it.kind === 'art') {
    const w = Math.min(it.w, (it.h || 0.7) * cut.aspect), h = w / cut.aspect;
    const frame = new THREE.Mesh(new THREE.BoxGeometry(w + 0.06, h + 0.06, 0.03), new THREE.MeshStandardMaterial({ color: '#2b2622', roughness: 0.6 }));
    const pic = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
    const z = it.z || 1.45;
    frame.position.set(0, z - h / 2, 0.015 - it.d / 2); pic.position.set(0, z - h / 2, 0.032 - it.d / 2);
    frame.castShadow = true; pic.userData.noInk = true;
    g.add(frame, pic);
    g.rotation.y = Math.PI - (it.rot || 0) * Math.PI / 180;
    return g;
  }
  // its size: as wide as the piece across, kept between 0.7 and 1.6 times its real height
  let w = Math.max(it.w, it.d) * 0.98, h = w / cut.aspect;
  const tall = it.h || 0.8;
  if (h > tall * 1.6) { h = tall * 1.6; w = h * cut.aspect; }
  if (h < tall * 0.7) { h = tall * 0.7; w = h * cut.aspect; }
  const geo = new THREE.PlaneGeometry(1, 1); geo.translate(0, 0.5, 0);
  const pic = new THREE.Mesh(geo, mat);
  pic.scale.set(w, h, 1); pic.castShadow = true; pic.userData.noInk = true;
  const face = new THREE.Group(); face.add(pic); face.userData.face = true;
  // a piece that stands free turns right round to you; one backed onto a wall stands at its front edge and turns at
  // most 40 degrees, so its picture never sinks into the wall behind it
  if (!FREE.has(it.kind)) {
    const front = (it.rot || 0) * Math.PI / 180;            // 0 = north = -z in the scene
    face.userData.front = Math.atan2(Math.sin(front), -Math.cos(front));
    face.userData.span = 40 * Math.PI / 180;
    face.position.set(Math.sin(front) * (it.d / 2 - 0.05), 0, -Math.cos(front) * (it.d / 2 - 0.05));
  }
  const sh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: shadowTex(), transparent: true, depthWrite: false, toneMapped: false }));
  sh.rotation.x = -Math.PI / 2; sh.rotation.z = -(it.rot || 0) * Math.PI / 180; sh.position.y = 0.03;
  sh.scale.set(it.w * 1.25, it.d * 1.25, 1); sh.userData.noInk = true; sh.renderOrder = 1;
  g.add(sh, face);
  return g;
}

// Turn a placed cut-out's picture towards the camera (cylindrical: it stays upright).
const wrap = a => Math.atan2(Math.sin(a), Math.cos(a));
const tmp = new THREE.Vector3();
export function faceCamera(group, camera) {
  for (const f of group.children) {
    if (!f.userData.face) continue;
    f.getWorldPosition(tmp);
    let a = Math.atan2(camera.position.x - tmp.x, camera.position.z - tmp.z);
    if (f.userData.span) { const d = wrap(a - f.userData.front); a = f.userData.front + Math.max(-f.userData.span, Math.min(f.userData.span, d)); }
    f.rotation.y = a;
  }
}
