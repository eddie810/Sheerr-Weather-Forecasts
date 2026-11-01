// Avalon highs fly-over: terrain (TERRAIN) with the shaded map (texture.jpg) draped on it, town cards on pins.
// The camera starts over the whole Avalon, visits each area in D.areas order (cards pop in on arrival and
// fade as it leaves), then pulls back to the whole Avalon with the D.towns[n].final cards.
// window.setT(t) draws the frame at t seconds (render.js steps it). window.ANIM_LEN = length.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

const D = window.TEMPS, T = window.TERRAIN, W = 1080, H = 960, EXAG = 4;
const map = document.getElementById("map");

// renderer
const canvas = document.createElement("canvas");
canvas.width = W; canvas.height = H;
map.insertBefore(canvas, map.firstChild);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1); renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
const SEA = new THREE.Color(D.sea);
scene.background = SEA;
scene.fog = new THREE.Fog(SEA, 1900, 4200);
const camera = new THREE.PerspectiveCamera(38, W / H, 5, 6000);

// terrain mesh, one cell per scene unit (x right, z down the map, y up)
const raw = Uint8Array.from(atob(T.data), c => c.charCodeAt(0));
const hgt = new Int16Array(raw.buffer);
const nx = T.w, nz = T.h, cell = W / nx;
const toY = m => m / 1000 / (T.km_per_px / cell) * EXAG;
const pos = new Float32Array(nx * nz * 3), uv = new Float32Array(nx * nz * 2);
for (let i = 0; i < nz; i++) for (let j = 0; j < nx; j++) {
  const k = i * nx + j;
  pos[k * 3] = (j + 0.5) * cell - W / 2;
  pos[k * 3 + 1] = toY(Math.max(hgt[k], 0));
  pos[k * 3 + 2] = (i + 0.5) * cell - H / 2;
  uv[k * 2] = (j + 0.5) / nx; uv[k * 2 + 1] = 1 - (i + 0.5) / nz;
}
const idx = new Uint32Array((nx - 1) * (nz - 1) * 6);
let q = 0;
for (let i = 0; i < nz - 1; i++) for (let j = 0; j < nx - 1; j++) {
  const a = i * nx + j, b = a + 1, c = a + nx, d = c + 1;
  idx[q++] = a; idx[q++] = c; idx[q++] = b; idx[q++] = b; idx[q++] = c; idx[q++] = d;
}
const geo = new THREE.BufferGeometry();
geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
geo.setIndex(new THREE.BufferAttribute(idx, 1)); geo.computeVertexNormals();
const tex = await new THREE.TextureLoader().loadAsync("texture.jpg");
tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95, metalness: 0 })));
// endless sea in the map's water colour (the texture fades to it at its edges)
const sea = new THREE.Mesh(new THREE.PlaneGeometry(12000, 12000), new THREE.MeshStandardMaterial({ color: SEA, roughness: 1 }));
sea.rotation.x = -Math.PI / 2; sea.position.y = -0.3; scene.add(sea);
// lit so flat ground comes out at about the texture's own colours; slopes facing the sun brighten, the others shade
scene.add(new THREE.HemisphereLight("#ffffff", "#8a989d", 1.8));
const sun = new THREE.DirectionalLight("#fff6e8", 1.9); sun.position.set(-500, 520, -380); scene.add(sun);

function groundY(x, z) {                                     // terrain height under scene x/z
  const j = Math.min(nx - 1, Math.max(0, Math.round((x + W / 2) / cell - 0.5)));
  const i = Math.min(nz - 1, Math.max(0, Math.round((z + H / 2) / cell - 0.5)));
  return toY(Math.max(hgt[i * nx + j], 0));
}
const UP = 24;                                               // card anchor height above the town

// pins + cards
const NS = "http://www.w3.org/2000/svg", pins = document.getElementById("pins");
const cardEls = Array.from(document.getElementById("cards").children), names = Object.keys(D.towns);
const towns = names.map((n, i) => {
  const t = D.towns[n], x = t.xy[0] - W / 2, z = t.xy[1] - H / 2, y = groundY(x, z);
  const line = document.createElementNS(NS, "line"); line.setAttribute("stroke", "#10222B"); line.setAttribute("stroke-width", "1.8");
  const dot = document.createElementNS(NS, "circle"); dot.setAttribute("r", "6"); dot.setAttribute("fill", "#10222B");
  dot.setAttribute("stroke", "#fff"); dot.setAttribute("stroke-width", "2.5");
  pins.appendChild(line); pins.appendChild(dot);
  return { n, t, el: cardEls[i], line, dot, g: new THREE.Vector3(x, y, z), top: new THREE.Vector3(x, y + UP, z) };
});
function proj(v) { const p = v.clone().project(camera); return [(p.x + 1) / 2 * W, (1 - p.y) / 2 * H, p.z]; }

// camera: orbit state {tgt, az (deg, compass bearing from the target to the camera), el (deg), dist}
function centroid(list) {
  const s = list.reduce((a, o) => [a[0] + o.g.x, a[1] + o.g.z], [0, 0]);
  return [s[0] / list.length, 0, s[1] / list.length];
}
const AREA_VIEW = [                     // per area: bearing, elevation, distance, target nudge [x, z] from the towns' centre
  { az: 105, el: 40, dist: 580, nudge: [-95, 0] }, { az: 122, el: 46, dist: 880, nudge: [-80, -95] },
  { az: 140, el: 40, dist: 640, nudge: [0, 0] }, { az: 195, el: 42, dist: 600, nudge: [0, 0] },
];
const all = centroid(towns);
const OVER = { tgt: [all[0] + 10, 0, all[2] + 10], az: 172, el: 54, dist: 1300 };
const MOVE = 2.8, HOLD = 4.2, FIRST = 1.4, LAST = 4.6;
const KEYS = [{ t: 0, s: { ...OVER, az: 180, dist: 1380 } }, { t: FIRST, s: OVER }];
const STOPS = [];                                            // [arrive, leave] per area
D.areas.forEach((a, i) => {
  const { nudge, ...v } = AREA_VIEW[i], c = centroid(towns.filter(o => o.t.area === i)), tgt = [c[0] + nudge[0], 0, c[2] + nudge[1]], t0 = KEYS[KEYS.length - 1].t + MOVE + (i === 2 ? 0.6 : 0);
  KEYS.push({ t: t0, s: { tgt, ...v } });
  KEYS.push({ t: t0 + HOLD, s: { tgt, az: v.az + 5, el: v.el + 1, dist: v.dist * 0.93 } });       // slow drift while holding
  STOPS.push([t0, t0 + HOLD]);
});
const FINAL = KEYS[KEYS.length - 1].t + MOVE + 0.4;
KEYS.push({ t: FINAL, s: OVER });
KEYS.push({ t: FINAL + LAST, s: { ...OVER, az: OVER.az - 3, dist: OVER.dist * 0.97 } });
window.ANIM_LEN = FINAL + LAST;

const ease = x => (x = Math.min(1, Math.max(0, x)), x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const smooth = x => (x = Math.min(1, Math.max(0, x)), x * x * (3 - 2 * x));
const back = x => { x = Math.min(1, Math.max(0, x)); const c = 1.70158; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
const mix = (a, b, f) => a + (b - a) * f;
function camAt(t) {
  let k = 0; while (k < KEYS.length - 2 && t > KEYS[k + 1].t) k++;
  const A = KEYS[k].s, B = KEYS[k + 1].s, moving = A.tgt !== B.tgt;
  const f = (moving ? ease : smooth)((t - KEYS[k].t) / (KEYS[k + 1].t - KEYS[k].t));
  // moves rise a little in the middle so the camera arcs over the land between areas
  const lift = moving ? Math.sin(Math.PI * f) * 0.18 : 0;
  const s = { tgt: A.tgt.map((v, i) => mix(v, B.tgt[i], f)), az: mix(A.az, B.az, f), el: mix(A.el, B.el, f) + lift * 20,
    dist: mix(A.dist, B.dist, f) * (1 + lift) };
  const az = s.az * Math.PI / 180, el = s.el * Math.PI / 180;
  return { tgt: s.tgt, pos: [s.tgt[0] + s.dist * Math.sin(az) * Math.cos(el), s.dist * Math.sin(el), s.tgt[2] - s.dist * Math.cos(az) * Math.cos(el)] };
}

// card schedule: area cards pop in as the camera arrives and fade as it leaves; the final set at the end
const STEP = 0.3, POP = 0.45;
towns.forEach(o => {
  const mates = towns.filter(p => p.t.area === o.t.area).sort((a, b) => a.g.x - b.g.x);
  const [arr, leave] = STOPS[o.t.area];
  o.windows = [[arr - 0.5 + mates.indexOf(o) * STEP, leave + 0.15]];
  const fin = towns.filter(p => p.t.final).sort((a, b) => a.g.x - b.g.x);
  if (o.t.final) o.windows.push([FINAL - 0.3 + fin.indexOf(o) * 0.18, Infinity]);
});
const tag = document.getElementById("tag"), stepEls = Array.from(document.getElementById("steps").children);
const top = document.querySelector(".top");

window.setT = function (t) {
  const c = camAt(t);
  camera.position.set(...c.pos); camera.lookAt(...c.tgt); camera.updateMatrixWorld();
  renderer.render(scene, camera);
  const h = ease((t - 0.2) / 0.7);
  top.style.opacity = h; top.style.transform = `translateY(${(1 - h) * -24}px)`;

  towns.forEach(o => {
    let vis = 0, k = 0, t0 = 0;
    for (const [a, b] of o.windows) {
      if (t < a - 0.01 || t > b + 0.5) continue;
      t0 = a; k = (t - a) / POP;
      vis = Math.min(1, Math.max(0, k * 2)) * (1 - smooth((t - b) / 0.5));
    }
    const g = proj(o.g), p = proj(o.top), on = vis > 0.001 && g[2] < 1;
    o.dot.setAttribute("cx", g[0]); o.dot.setAttribute("cy", g[1]);
    o.line.setAttribute("x1", g[0]); o.line.setAttribute("y1", g[1]); o.line.setAttribute("x2", p[0]); o.line.setAttribute("y2", p[1]);
    o.dot.style.opacity = on ? vis : 0; o.line.style.opacity = on ? vis * .75 : 0;
    o.el.style.display = on ? "" : "none";
    if (!on) return;
    o.el.style.left = p[0] + "px"; o.el.style.top = p[1] + "px";
    o.el.style.transform = `translate(-50%,-100%) scale(${Math.max(0.001, back(k))})`;
    o.el.style.opacity = vis;
    const cnt = ease((t - t0) / 0.8), lo = Math.min(0, o.t.high - 6);
    o.el.querySelector(".t").textContent = Math.round(lo + (o.t.high - lo) * cnt) + "°";
  });

  // area tag: in while the camera is over an area, swapping text between areas while hidden
  let ti = -1, tv = 0;
  STOPS.forEach(([a, b], i) => {
    const v = smooth((t - (a - 0.6)) / 0.5) * (1 - smooth((t - b) / 0.45));
    if (v > tv) { tv = v; ti = i; }
  });
  tag.style.opacity = tv; tag.style.transform = `translateX(${(1 - tv) * -18}px)`;
  if (ti >= 0) {
    const a = D.areas[ti], hs = a.towns.map(n => D.towns[n].high), lo = Math.min(...hs), hi = Math.max(...hs);
    document.getElementById("tagk").textContent = `Stop ${ti + 1} of ${D.areas.length}`;
    document.getElementById("taga").textContent = a.name;
    document.getElementById("tagr").textContent = lo === hi ? `Highs near ${lo}°` : `Highs ${lo} to ${hi}°`;
    stepEls.forEach((e, i) => e.classList.toggle("on", i <= ti));
  }
};
await document.fonts.ready;
window.setT(0);
window.READY = true;
