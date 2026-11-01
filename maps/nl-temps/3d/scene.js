// 3D highs scene: terrain (TERRAIN) with the 2D map draped as a texture, cards on pins, scripted camera.
// window.setT(t) draws the frame at t seconds (render.js steps it at 30 fps). window.ANIM_LEN = length.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

const D = window.TEMPS, T = window.TERRAIN, REGION = window.REGION || "", sfx = REGION ? "-" + REGION : "";
const W = 1080, H = 960, LAB = REGION === "labrador", EXAG = LAB ? 18 : 13;
const map = document.querySelector(".map");
map.style.background = "none";
document.getElementById("ov").style.display = "none";

// renderer
const canvas = document.createElement("canvas");
canvas.width = W; canvas.height = H;
canvas.style.cssText = "position:absolute;inset:0;width:1080px;height:960px";
map.insertBefore(canvas, map.firstChild);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1); renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
const sky = new THREE.Color("#E6ECEE"), SEA = new THREE.Color("#DCDCDD");
scene.background = sky;
scene.fog = new THREE.Fog(sky, 900, 2600);
const camera = new THREE.PerspectiveCamera(38, W / H, 5, 5000);

// terrain mesh in 2D-map pixel units (x right, z down the map, y up)
const raw = Uint8Array.from(atob(T.data), c => c.charCodeAt(0));
const hgt = new Int16Array(raw.buffer);
const nx = T.w, nz = T.h, cell = W / nx;                      // 2 css px per cell
const kmPerCss = T.km_per_px / cell, toPx = m => m / 1000 / kmPerCss * EXAG;
const pos = new Float32Array(nx * nz * 3), uv = new Float32Array(nx * nz * 2);
for (let i = 0; i < nz; i++) for (let j = 0; j < nx; j++) {
  const k = i * nx + j, e = hgt[k];
  pos[k * 3] = (j + 0.5) * cell - W / 2;
  pos[k * 3 + 1] = toPx(Math.max(e, 0));
  pos[k * 3 + 2] = (i + 0.5) * cell - H / 2;
  uv[k * 2] = (j + 0.5) / nx; uv[k * 2 + 1] = 1 - (i + 0.5) / nz;
}
const idx = [];
for (let i = 0; i < nz - 1; i++) for (let j = 0; j < nx - 1; j++) {
  const a = i * nx + j, b = a + 1, c = a + nx, d = c + 1;
  idx.push(a, c, b, b, c, d);
}
const geo = new THREE.BufferGeometry();
geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
geo.setIndex(idx); geo.computeVertexNormals();
const tex = await new THREE.TextureLoader().loadAsync("3d/texture" + sfx + ".png");
tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
const ground = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95, metalness: 0 }));
scene.add(ground);
// endless sea in the basemap's water colour, so the map's edges disappear into the haze
const sea = new THREE.Mesh(new THREE.PlaneGeometry(9000, 9000), new THREE.MeshStandardMaterial({ color: SEA, roughness: 1 }));
sea.rotation.x = -Math.PI / 2; sea.position.y = -0.4; scene.add(sea);
scene.add(new THREE.HemisphereLight("#ffffff", "#7a8a90", 1.15));
const sun = new THREE.DirectionalLight("#fff6e8", 1.6); sun.position.set(-500, 420, -380); scene.add(sun);

function groundY(px, py) {                                   // terrain height under a 2D map pixel
  const j = Math.min(nx - 1, Math.max(0, Math.round(px / cell - 0.5))), i = Math.min(nz - 1, Math.max(0, Math.round(py / cell - 0.5)));
  return toPx(Math.max(hgt[i * nx + j], 0));
}
const v3 = (px, py, up) => new THREE.Vector3(px - W / 2, groundY(px, py) + up, py - H / 2);

// pins + cards: dot on the town, leader up to the card's own (decluttered) 2D spot, raised
const NS = "http://www.w3.org/2000/svg";
const pins = document.createElementNS(NS, "svg");
pins.setAttribute("viewBox", "0 0 1080 960"); pins.style.cssText = "position:absolute;inset:0;width:1080px;height:960px";
map.insertBefore(pins, document.getElementById("cards"));
const cardsBox = document.getElementById("cards"), cardEls = Array.from(cardsBox.children), names = Object.keys(D.towns);
const towns = names.map((n, i) => {
  const t = D.towns[n];
  const line = document.createElementNS(NS, "line"); line.setAttribute("stroke", "#10222B"); line.setAttribute("stroke-width", "1.8");
  const dot = document.createElementNS(NS, "circle"); dot.setAttribute("r", "6"); dot.setAttribute("fill", "#10222B");
  dot.setAttribute("stroke", "#fff"); dot.setAttribute("stroke-width", "2.5");
  pins.appendChild(line); pins.appendChild(dot);
  return { n, hi: t.high, el: cardEls[i], line, dot, g: v3(t.xy[0], t.xy[1], 0), top: v3(t.card[0], t.card[1], 46) };
}).sort((a, b) => a.g.x - b.g.x);
function proj(v) { const p = v.clone().project(camera); return [(p.x + 1) / 2 * W, (1 - p.y) / 2 * H, p.z]; }

// camera path. Island: low over the Gulf -> along the west coast past the Long Range -> settle over the whole Island.
// Labrador: low off the southeast coast -> north up the coast toward the Torngats -> settle over the whole region.
const KEYS = LAB ? [
  { t: 0.0, pos: [600, 300, 620], tgt: [160, 0, 180] },
  { t: 3.6, pos: [640, 380, -60], tgt: [40, 0, -110] },
  { t: 7.0, pos: [0, 1180, 520], tgt: [0, 0, 130] },
] : [
  { t: 0.0, pos: [-560, 300, 560], tgt: [-190, 0, 110] },
  { t: 3.6, pos: [-700, 330, -60], tgt: [-150, 0, -110] },
  { t: 7.0, pos: [30, 1230, 780], tgt: [30, 0, 10] },
];
const ease = x => (x = Math.min(1, Math.max(0, x)), x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const back = x => { x = Math.min(1, Math.max(0, x)); const c = 1.70158; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
const lerp3 = (a, b, f) => a.map((v, i) => v + (b[i] - v) * f);
function camAt(t) {
  let k = 0; while (k < KEYS.length - 2 && t > KEYS[k + 1].t) k++;
  const A = KEYS[k], B = KEYS[k + 1], f = ease((t - A.t) / (B.t - A.t));
  return { pos: lerp3(A.pos, B.pos, f), tgt: lerp3(A.tgt, B.tgt, f) };
}
const top = document.querySelector(".top"), scaleEl = document.querySelector(".scale");
const CARD0 = 6.6, STEP = 0.3, POP = 0.45;
window.ANIM_LEN = CARD0 + STEP * towns.length + 3.6;

window.setT = function (t) {
  const c = camAt(t);
  camera.position.set(...c.pos); camera.lookAt(...c.tgt); camera.updateMatrixWorld();
  renderer.render(scene, camera);
  const h = ease((t - 0.2) / 0.7);
  top.style.opacity = h; top.style.transform = `translateY(${(1 - h) * -24}px)`;
  towns.forEach((o, i) => {
    const t0 = CARD0 + i * STEP, k = (t - t0) / POP, op = Math.min(1, Math.max(0, k * 2));
    const g = proj(o.g), p = proj(o.top);
    o.dot.setAttribute("cx", g[0]); o.dot.setAttribute("cy", g[1]);
    o.line.setAttribute("x1", g[0]); o.line.setAttribute("y1", g[1]); o.line.setAttribute("x2", p[0]); o.line.setAttribute("y2", p[1]);
    o.dot.style.opacity = Math.min(1, Math.max(0, (t - (CARD0 - 1.2 + i * 0.08)) / 0.4));
    o.line.style.opacity = op * .7;
    o.el.style.left = p[0] + "px"; o.el.style.top = p[1] + "px";
    o.el.style.transform = `translate(-50%,-100%) scale(${Math.max(0.001, k <= 0 ? 0 : back(k))})`;
    o.el.style.transformOrigin = "50% 100%";
    o.el.style.opacity = op;
    const cnt = ease((t - t0) / 0.8), lo = Math.min(0, o.hi - 6);
    o.el.querySelector(".t").textContent = Math.round(lo + (o.hi - lo) * cnt) + "°";
  });
  scaleEl.style.opacity = ease((t - (CARD0 + STEP * towns.length)) / 0.7);
};
window.setT(0);
window.READY = true;
