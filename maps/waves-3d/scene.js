// 3D wave heights: the ocean surface is raised and coloured by significant wave height, MSLP isobars are drawn
// on it, H/L centres ride on top and white crest marks move the way the waves travel.
// Smooth in time (Catmull-Rom through the 3-hourly steps, on the CPU) and in space (cubic B-spline in the shader).
// window.setT(t) draws the frame at t seconds; window.ANIM_LEN is the loop length; window.READY when loaded.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

const M = window.WAVES, NX = M.nx, NY = M.ny, NS = M.times.length;
const LON0 = M.lon0, LAT0 = M.lat0, LON1 = LON0 + M.dlon * (NX - 1), LAT1 = LAT0 + M.dlat * (NY - 1);
const merc = la => Math.log(Math.tan(Math.PI / 4 + la * Math.PI / 360));
const Y0 = merc(LAT0), Y1 = merc(LAT1);
const WD = 1000, DD = WD * (Y1 - Y0) / ((LON1 - LON0) * Math.PI / 180);
const W = 1080, H = 960, K = 7.5;                         // world units per metre of wave height
const STOPS = [[0, "#EAF5FA"], [1, "#BFE0F2"], [2, "#7FC1E6"], [3, "#3E9AD6"], [4, "#2BAE9A"], [5, "#8CCB5E"],
  [6, "#F3D54E"], [7, "#F7A23B"], [8, "#EE7136"], [9, "#DC4A33"], [10, "#B8303F"], [12, "#8C2452"], [14, "#5E1F5E"]];
const HMAX = 14, P0 = 1012;

// ---- data ------------------------------------------------------------------------------------------
const raw = new Float32Array(await (await fetch("waves.bin")).arrayBuffer());   // [step][lat][lon][hs,p,u,v]
const PER = NX * NY * 4;
const seaBits = Uint8Array.from(atob(M.sea), c => c.charCodeAt(0));
const isSea = (i, j) => (seaBits[(j * NX + i) >> 3] >> (7 - ((j * NX + i) & 7))) & 1;
const cur = new Float32Array(PER);                        // fields at the current (fractional) step
function interpStep(s) {                                  // Catmull-Rom in time through steps k-1..k+2
  const k = Math.min(NS - 2, Math.floor(s)), f = s - k;
  const a = raw.subarray(Math.max(0, k - 1) * PER), b = raw.subarray(k * PER), c = raw.subarray((k + 1) * PER),
        d = raw.subarray(Math.min(NS - 1, k + 2) * PER);
  const f2 = f * f, f3 = f2 * f;
  const wa = -0.5 * f3 + f2 - 0.5 * f, wb = 1.5 * f3 - 2.5 * f2 + 1, wc = -1.5 * f3 + 2 * f2 + 0.5 * f, wd = 0.5 * f3 - 0.5 * f2;
  for (let n = 0; n < PER; n++) cur[n] = wa * a[n] + wb * b[n] + wc * c[n] + wd * d[n];
  for (let n = 0; n < PER; n += 4) { if (cur[n] < 0) cur[n] = 0; }
}
function sample(lon, lat) {                               // bilinear from cur: [hs, p, u, v] or null off-grid
  const x = (lon - LON0) / M.dlon, y = (lat - LAT0) / M.dlat;
  if (x < 0 || y < 0 || x > NX - 1.001 || y > NY - 1.001) return null;
  const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j, o = [0, 0, 0, 0];
  for (let q = 0; q < 4; q++) {
    const n00 = ((j * NX + i) << 2) + q, n10 = n00 + 4, n01 = n00 + NX * 4, n11 = n01 + 4;
    o[q] = (cur[n00] * (1 - fx) + cur[n10] * fx) * (1 - fy) + (cur[n01] * (1 - fx) + cur[n11] * fx) * fy;
  }
  o.sea = isSea(Math.round(x), Math.round(y));
  return o;
}

// ---- scene -----------------------------------------------------------------------------------------
const map = document.getElementById("map");
const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById("gl"), antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1); renderer.setSize(W, H, false);
const scene = new THREE.Scene();
const sky = new THREE.Color("#E6ECEE");
scene.background = sky;
const camera = new THREE.PerspectiveCamera(36, W / H, 5, 6000);

const texData = new THREE.DataTexture(new Uint16Array(PER), NX, NY, THREE.RGBAFormat, THREE.HalfFloatType);
texData.minFilter = texData.magFilter = THREE.LinearFilter;
const half = texData.image.data;
function upload() {
  for (let n = 0; n < PER; n += 4) {
    half[n] = THREE.DataUtils.toHalfFloat(cur[n]);
    half[n + 1] = THREE.DataUtils.toHalfFloat(cur[n + 1] - P0);
  }
  texData.needsUpdate = true;
}
const base = await new THREE.TextureLoader().loadAsync("basemap.png");
base.colorSpace = THREE.SRGBColorSpace; base.anisotropy = 8;
base.generateMipmaps = true; base.minFilter = THREE.LinearMipmapLinearFilter;

const rampCanvas = document.createElement("canvas"); rampCanvas.width = 512; rampCanvas.height = 1;
{ const c = rampCanvas.getContext("2d"), g = c.createLinearGradient(0, 0, 512, 0);
  STOPS.forEach(s => g.addColorStop(s[0] / HMAX, s[1])); c.fillStyle = g; c.fillRect(0, 0, 512, 1); }
const ramp = new THREE.CanvasTexture(rampCanvas); ramp.colorSpace = THREE.SRGBColorSpace;
ramp.wrapS = ramp.wrapT = THREE.ClampToEdgeWrapping;

const COMMON = /* glsl */`
  uniform sampler2D uData, uBase;
  uniform vec2 uSize;
  uniform vec4 uGeo;     // lon0, dlon, lat0, dlat (grid)
  uniform vec4 uFrame;   // LON0, LON1, Y0, Y1 (Mercator frame)
  vec2 gridIdx(vec2 uv){
    float lon = mix(uFrame.x, uFrame.y, uv.x);
    float lat = degrees(atan(sinh(mix(uFrame.z, uFrame.w, uv.y))));
    return vec2((lon - uGeo.x) / uGeo.y, (lat - uGeo.z) / uGeo.w);
  }
  vec4 bspline(vec2 p){            // cubic B-spline from 4 bilinear taps; p in grid-index space
    vec2 i = floor(p), f = p - i, f2 = f * f, f3 = f2 * f;
    vec2 w0 = (1.0 - 3.0 * f + 3.0 * f2 - f3) / 6.0, w1 = (4.0 - 6.0 * f2 + 3.0 * f3) / 6.0;
    vec2 w2 = (1.0 + 3.0 * f + 3.0 * f2 - 3.0 * f3) / 6.0, w3 = f3 / 6.0;
    vec2 g0 = w0 + w1, g1 = w2 + w3;
    vec2 h0 = (i - 1.0 + w1 / g0 + 0.5) / uSize, h1 = (i + 1.0 + w3 / g1 + 0.5) / uSize;
    return g0.y * (g0.x * texture(uData, h0) + g1.x * texture(uData, vec2(h1.x, h0.y)))
         + g1.y * (g0.x * texture(uData, vec2(h0.x, h1.y)) + g1.x * texture(uData, h1));
  }
  float seaF(vec2 uv){ return 1.0 - smoothstep(0.05, 0.6, textureLod(uBase, uv, 4.0).a); }
  float hraw(vec2 uv){ return max(bspline(gridIdx(uv)).r, 0.0) * ${K.toFixed(2)}; }
  float hgt(vec2 uv){ return hraw(uv) * seaF(uv); }
`;
const mat = new THREE.ShaderMaterial({
  uniforms: {
    uData: { value: texData }, uBase: { value: base }, uRamp: { value: ramp },
    uSize: { value: new THREE.Vector2(NX, NY) },
    uGeo: { value: new THREE.Vector4(LON0, M.dlon, LAT0, M.dlat) },
    uFrame: { value: new THREE.Vector4(LON0, LON1, Y0, Y1) },
    uSky: { value: sky }, uFog: { value: new THREE.Vector2(1500, 3200) },
  },
  vertexShader: /* glsl */`
    ${COMMON}
    varying vec2 vUv; varying vec3 vN; varying float vDist;
    void main(){
      vUv = uv;
      // lighting normal from the wave field alone, so the ramp down to the coast isn't shaded as a slope
      float e = 1.0 / 900.0, h = hgt(uv);
      float dx = (hraw(uv + vec2(e, 0.0)) - hraw(uv - vec2(e, 0.0))) / (2.0 * e * ${WD.toFixed(1)});
      float dn = (hraw(uv + vec2(0.0, e)) - hraw(uv - vec2(0.0, e))) / (2.0 * e * ${DD.toFixed(1)});
      vN = normalize(vec3(-dx, 1.0, dn));
      vec4 mv = modelViewMatrix * vec4(position.x, h, position.z, 1.0);
      vDist = -mv.z;
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: /* glsl */`
    ${COMMON}
    uniform sampler2D uRamp; uniform vec3 uSky; uniform vec2 uFog;
    varying vec2 vUv; varying vec3 vN; varying float vDist;
    void main(){
      vec4 d = bspline(gridIdx(vUv));
      vec3 col = texture(uRamp, vec2(clamp(d.r / ${HMAX.toFixed(1)}, 0.0, 1.0), 0.5)).rgb;
      vec4 land = texture(uBase, vUv);
      vec3 L = normalize(vec3(-0.45, 0.8, -0.4));
      col *= 1.0 + 0.9 * (dot(normalize(vN), L) - L.y);
      col = mix(col, land.rgb, land.a);
      float p = d.g, fw = fwidth(p);
      float dd = abs(fract(p / 4.0 + 0.5) - 0.5) * 4.0;
      float line = 1.0 - smoothstep(0.7 * fw, 1.7 * fw, dd);
      col = mix(col, vec3(0.118, 0.18, 0.212), line * mix(0.72, 0.45, land.a));
      col = mix(col, uSky, smoothstep(uFog.x, uFog.y, vDist));
      gl_FragColor = vec4(col, 1.0);
      #include <colorspace_fragment>
    }`,
});
const geo = new THREE.PlaneGeometry(WD, DD, 420, Math.round(420 * DD / WD));
geo.rotateX(-Math.PI / 2);                                // uv.y = 1 at the far (north, -z) edge
scene.add(new THREE.Mesh(geo, mat));

// lon/lat -> world, and screen
const wx = lon => (lon - LON0) / (LON1 - LON0) * WD - WD / 2;
const wz = lat => -((merc(lat) - Y0) / (Y1 - Y0) * DD - DD / 2);
function surfY(lon, lat) { const s = sample(lon, lat); return s && s.sea ? s[0] * K : 0; }
function proj(lon, lat, up) {
  const v = new THREE.Vector3(wx(lon), surfY(lon, lat) + (up || 0), wz(lat)).project(camera);
  return [(v.x + 1) / 2 * W, (1 - v.y) / 2 * H, v.z];
}

// ---- swell crests (deterministic particle sim, stepped at the video frame rate) -------------------------
const ctx = document.getElementById("swell").getContext("2d");
const NP = 1100, FPS = 30;
let seed = 7;
const rnd = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
  t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
let P = [], simT = -1;
function spawn(o) {
  for (let k = 0; k < 30; k++) {
    o.lon = LON0 + rnd() * (LON1 - LON0); o.lat = LAT0 + rnd() * (LAT1 - LAT0);
    const s = sample(o.lon, o.lat);
    if (s && s.sea) break;
  }
  o.life = 1.8 + rnd() * 1.4; o.age = 0;
  return o;
}
function resetSim() { seed = 7; P = []; for (let n = 0; n < NP; n++) { const o = spawn({}); o.age = rnd() * o.life; P.push(o); } simT = 0; }
function stepSim(dt) {
  for (const o of P) {
    o.age += dt;
    const s = sample(o.lon, o.lat);
    if (o.age > o.life || !s || !s.sea) { spawn(o); continue; }
    const T = Math.hypot(s[2], s[3]) || 1, sp = 0.05 * T;   // deg-lat per second, faster for long-period swell
    o.lat += s[3] / T * sp * dt;
    o.lon += s[2] / T * sp * dt / Math.cos(o.lat * Math.PI / 180);
  }
}
function drawSwell() {
  ctx.clearRect(0, 0, W, H);
  ctx.lineCap = "round";
  for (const o of P) {
    const s = sample(o.lon, o.lat);
    if (!s || !s.sea) continue;
    const T = Math.hypot(s[2], s[3]) || 1, ux = s[2] / T, uy = s[3] / T, c = Math.cos(o.lat * Math.PI / 180);
    const L = 0.42 + 0.06 * s[0];                          // crest length (deg), longer in bigger seas
    const a = proj(o.lon - uy * L / 2 / c, o.lat + ux * L / 2, 1.5), b = proj(o.lon + uy * L / 2 / c, o.lat - ux * L / 2, 1.5);
    const m = proj(o.lon + ux * L * 0.12 / c, o.lat + uy * L * 0.12, 1.5);
    if (a[2] > 1 || b[2] > 1) continue;
    const alpha = Math.sin(Math.PI * Math.min(1, o.age / o.life)) * Math.min(1, 0.35 + s[0] / 5) * 0.95;
    ctx.strokeStyle = `rgba(255,255,255,${alpha.toFixed(3)})`;
    ctx.lineWidth = 2.4;
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.quadraticCurveTo(2 * m[0] - (a[0] + b[0]) / 2, 2 * m[1] - (a[1] + b[1]) / 2, b[0], b[1]);
    ctx.stroke();
  }
}

// ---- labels: H/L tracks, cities, clock -------------------------------------------------------------------
const box = document.getElementById("labels");
const hl = M.tracks.map(tr => {
  const el = document.createElement("div"); el.className = "lbl hl " + tr.kind;
  el.innerHTML = `<b>${tr.kind}</b><span></span>`; box.appendChild(el); return { tr, el, sp: el.querySelector("span") };
});
const CITIES = [["St. John's", -52.71, 47.56], ["Halifax", -63.57, 44.65], ["Boston", -71.06, 42.36], ["New York", -74.0, 40.71],
  ["Sydney", -60.19, 46.14], ["Cape Hatteras", -75.53, 35.25]];
const cities = CITIES.map(c => { const el = document.createElement("div"); el.className = "lbl city";
  el.innerHTML = `<i></i><span>${c[0]}</span>`; box.appendChild(el); return { c, el }; });
const NDT = ms => new Date(ms - 2.5 * 3600e3);
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const t0 = Date.parse(M.times[0]), t1 = Date.parse(M.times[NS - 1]);
{ const out = []; for (let ms = t0; ms <= t1; ms += 864e5) out.push(DAYS[NDT(ms).getUTCDay()]);
  document.getElementById("cdays").innerHTML = out.map(d => `<span>${d}</span>`).join(""); }
const run = new Date(M.run);
document.getElementById("run").textContent = `${String(run.getUTCHours()).padStart(2, "0")}Z ${MON[run.getUTCMonth()]} ${run.getUTCDate()} run`;
if (window.SUB) document.getElementById("sub").textContent = window.SUB;
document.getElementById("ramp").style.background = "linear-gradient(90deg," + STOPS.map(s => `${s[1]} ${(s[0] / HMAX * 100).toFixed(1)}%`).join(",") + ")";
document.getElementById("ticks").innerHTML = [0, 2, 4, 6, 8, 10, 12, 14].map(v => `<b style="left:${v / HMAX * 100}%">${v}${v === 14 ? "+" : ""}</b>`).join("");

function placeLabels(s) {
  hl.forEach(o => {
    const pts = o.tr.pts, first = pts[0][0], last = pts[pts.length - 1][0];
    let op = Math.min(1, (s - first + 0.6) / 0.6, (last + 0.6 - s) / 0.6);
    if (op <= 0) { o.el.style.opacity = 0; return; }
    let k = 0; while (k < pts.length - 2 && pts[k + 1][0] <= s) k++;
    const A = pts[k], B = pts[Math.min(k + 1, pts.length - 1)], f = B[0] > A[0] ? Math.min(1, Math.max(0, (s - A[0]) / (B[0] - A[0]))) : 0;
    const lon = A[1] + (B[1] - A[1]) * f, lat = A[2] + (B[2] - A[2]) * f, p = sample(lon, lat);
    const q = proj(lon, lat, 8);
    o.el.style.opacity = q[2] < 1 ? op : 0;
    o.el.style.transform = `translate(${q[0]}px,${q[1]}px) translate(-50%,-70%)`;
    o.sp.textContent = Math.round(p ? p[1] : A[3]);
  });
  cities.forEach(o => { const q = proj(o.c[1], o.c[2], 0); o.el.style.transform = `translate(${q[0] - 6}px,${q[1] - 6}px)`; });
}

// ---- camera + timeline ---------------------------------------------------------------------------------
const INTRO = 1.0, PER_STEP = 0.5, HOLD = 1.8;
window.ANIM_LEN = INTRO + PER_STEP * (NS - 1) + HOLD;
const KEYS = [{ t: 0, pos: [-90, 1010, 900], tgt: [-40, 0, 40] }, { t: window.ANIM_LEN, pos: [-10, 760, 760], tgt: [10, 0, 0] }];
const ease = x => (x = Math.min(1, Math.max(0, x)), x < .5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
const top = document.querySelector(".top");
let lastS = -1;
window.setT = function (t) {
  const s = Math.min(NS - 1, Math.max(0, (t - INTRO) / PER_STEP));
  if (s !== lastS) { interpStep(s); upload(); lastS = s; }
  const f = ease(t / window.ANIM_LEN), A = KEYS[0], B = KEYS[1];
  camera.position.set(...A.pos.map((v, i) => v + (B.pos[i] - v) * f));
  camera.lookAt(...A.tgt.map((v, i) => v + (B.tgt[i] - v) * f)); camera.updateMatrixWorld();
  renderer.render(scene, camera);
  // swell sim follows the video clock; jumping backwards (or far ahead) re-runs it from the start
  if (simT < 0 || t < simT - 1e-6 || t - simT > 3) { resetSim(); }
  while (simT + 1 / FPS <= t + 1e-6) { stepSim(1 / FPS); simT += 1 / FPS; }
  drawSwell();
  placeLabels(s);
  const ms = t0 + (t1 - t0) * s / (NS - 1), d = NDT(ms);
  document.getElementById("cd").textContent = `${DAYS[d.getUTCDay()]} ${MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
  const hr = d.getUTCHours(), mi = d.getUTCMinutes();
  document.getElementById("ch").textContent = `${(hr + 11) % 12 + 1}:${String(mi).padStart(2, "0")} ${hr < 12 ? "AM" : "PM"} NDT`;
  document.getElementById("cbar").style.width = (s / (NS - 1) * 100).toFixed(2) + "%";
  let pk = 0; for (let n = 0, c = 0; n < PER; n += 4, c++) if (cur[n] > pk && isSea(c % NX, (c / NX) | 0)) pk = cur[n];
  document.getElementById("cpk").textContent = pk.toFixed(1) + " m";
  const h = ease((t - 0.1) / 0.7); top.style.opacity = h;
};
window.setT(0);
window.READY = true;
