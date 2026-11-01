// ECT 50 fly-along: satellite terrain (TERRAIN + texture.jpg), the route drawn as the runner marker moves from
// Pouch Cove to Quidi Vidi, checkpoint tags, a card with each checkpoint's conditions for leaders and mid-pack,
// and wind/drizzle streaks from the RDPS. window.setT(t) draws frame t (seconds); window.ANIM_LEN; window.READY.
import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

const R = window.RACE, T = window.TERRAIN;
const GL = document.getElementById("gl"), W = GL.width, H = GL.height, U = 10, EX = 2.0;   // world unit = 10 m; heights x2
const merc = la => Math.log(Math.tan(Math.PI / 4 + la * Math.PI / 360));
const B = T.bounds, LON0 = B.lon[0], LON1 = B.lon[1], MY0 = merc(B.lat[1]), MY1 = merc(B.lat[0]);
const WD = T.w * T.m_per_cell / U, DD = T.h * T.m_per_cell / U;
const hgt = new Int16Array(Uint8Array.from(atob(T.data), c => c.charCodeAt(0)).buffer);
const uvOf = (la, lo) => [(lo - LON0) / (LON1 - LON0), (MY0 - merc(la)) / (MY0 - MY1)];   // v = 0 at the north edge
function groundAt(u, v) {                                  // bilinear height (world units, exaggerated)
  const x = Math.min(T.w - 1.001, Math.max(0, u * T.w - .5)), y = Math.min(T.h - 1.001, Math.max(0, v * T.h - .5));
  const i = Math.floor(y), j = Math.floor(x), fx = x - j, fy = y - i, k = i * T.w + j;
  const h = (hgt[k] * (1 - fx) + hgt[k + 1] * fx) * (1 - fy) + (hgt[k + T.w] * (1 - fx) + hgt[k + T.w + 1] * fx) * fy;
  return Math.max(h, 0) / U * EX;
}
const world = (la, lo, up = 0) => { const [u, v] = uvOf(la, lo); return new THREE.Vector3((u - .5) * WD, groundAt(u, v) + up, (v - .5) * DD); };

// ---- renderer / scene --------------------------------------------------------------------------------------
const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById("gl"), antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1); renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
const sea = new THREE.Color(`rgb(${T.sea.join(",")})`), haze = new THREE.Color("#5E7686");
scene.background = haze;
scene.fog = new THREE.Fog(haze, 2600, 6200);
const TVW = W / H > 1.5;                                        // 16:9: narrower lens so the wide frame stays on the terrain
const camera = new THREE.PerspectiveCamera(TVW ? 27 : 40, W / H, 5, 12000);

const pos = new Float32Array(T.w * T.h * 3), uv = new Float32Array(T.w * T.h * 2);
for (let i = 0; i < T.h; i++) for (let j = 0; j < T.w; j++) {
  const k = i * T.w + j;
  pos[k * 3] = ((j + .5) / T.w - .5) * WD; pos[k * 3 + 1] = Math.max(hgt[k], 0) / U * EX; pos[k * 3 + 2] = ((i + .5) / T.h - .5) * DD;
  uv[k * 2] = (j + .5) / T.w; uv[k * 2 + 1] = 1 - (i + .5) / T.h;
}
const idx = [];
for (let i = 0; i < T.h - 1; i++) for (let j = 0; j < T.w - 1; j++) { const a = i * T.w + j, b = a + 1, c = a + T.w, d = c + 1; idx.push(a, c, b, b, c, d); }
const geo = new THREE.BufferGeometry();
geo.setAttribute("position", new THREE.BufferAttribute(pos, 3)); geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
geo.setIndex(idx); geo.computeVertexNormals();
const tex = await new THREE.TextureLoader().loadAsync("texture.jpg");
tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0 })));
const seaPlane = new THREE.Mesh(new THREE.PlaneGeometry(30000, 30000), new THREE.MeshBasicMaterial({ color: sea }));
seaPlane.rotation.x = -Math.PI / 2; seaPlane.position.y = -0.3; scene.add(seaPlane);
scene.add(new THREE.HemisphereLight("#ffffff", "#41505a", 1.9));
const sun = new THREE.DirectionalLight("#f4f1ea", 1.1); sun.position.set(-900, 700, 400); scene.add(sun);   // overcast: soft light

// ---- route -------------------------------------------------------------------------------------------------
const step = Math.max(1, Math.floor(R.route.length / 700));
const rp = R.route.filter((_, i) => i % step === 0 || i === R.route.length - 1);
const rk = R.routeKm.filter((_, i) => i % step === 0 || i === R.route.length - 1);
const curve = new THREE.CatmullRomCurve3(rp.map(p => world(p[0], p[1], 4)), false, "centripetal");
const SEG = 1400, RAD = 8;
const ghost = new THREE.Mesh(new THREE.TubeGeometry(curve, SEG, 3.2, RAD, false), new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: .55 }));
const tubeGeo = new THREE.TubeGeometry(curve, SEG, 5.5, RAD, false);
const tube = new THREE.Mesh(tubeGeo, new THREE.MeshBasicMaterial({ color: "#FFB21F" }));
const casing = new THREE.Mesh(new THREE.TubeGeometry(curve, SEG, 7.5, RAD, false), new THREE.MeshBasicMaterial({ color: "#5A3500" }));
scene.add(ghost, casing, tube);
const runner = new THREE.Mesh(new THREE.SphereGeometry(11, 24, 16), new THREE.MeshBasicMaterial({ color: "#ffffff" }));
const halo = new THREE.Mesh(new THREE.SphereGeometry(20, 24, 16), new THREE.MeshBasicMaterial({ color: "#FFB21F", transparent: true, opacity: .45 }));
scene.add(runner, halo);
function uAtKm(km) {           // curve.getPointAt / TubeGeometry are arc-length parameterised; route km is arc length too
  return Math.min(1, Math.max(0, km / R.km));
}

// ---- checkpoint tags + card ---------------------------------------------------------------------------------
const pinsBox = document.getElementById("pins");
const pins = R.checkpoints.map(c => {
  const el = document.createElement("div"); el.className = "pin";
  el.innerHTML = `<div class="tag"><b>${c.name.replace(", Logy Bay", "")}</b><span>${c.kind === "Finish" ? "FINISH" : c.kind === "Start" ? "START" : c.km + " km"}</span></div>`;
  pinsBox.appendChild(el);
  return { c, el, p: world(c.ll[0], c.ll[1], 20) };
});
const bar = document.getElementById("bar");
R.checkpoints.forEach(c => { const u = document.createElement("u"); u.style.left = (c.km / R.km * 100) + "%"; bar.appendChild(u); });
const CARD = document.getElementById("card");
const card16 = d => ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][Math.round(d / 22.5) % 16];
const arrow = d => `<svg class="ar" viewBox="-12 -12 24 24"><g transform="rotate(${d + 180})"><path d="M0-10 6 6 0 2-6 6z" fill="#10222B"/></g></svg>`;
const sky = w => w.pr >= 1 ? "Rain" : w.pr >= 0.3 ? "Showers" : w.pr >= 0.05 ? "Drizzle" : w.cc >= 85 ? "Overcast" : w.cc >= 50 ? "Cloudy" : "Sun & cloud";
function cardHtml(c) {
  const row = (who, p) => { const w = c.wx[p];
    return `<div class="row"><div class="who">${who}<em>${c.eta[p]}</em></div><div class="tmp">${w.t}°</div>
      <div class="wx">${arrow(w.wd)}${card16(w.wd)} ${w.ws} <span>gust ${w.g} km/h</span><br><span>${sky(w)}</span></div></div>`; };
  return `<div class="hd"><b>${c.name}</b><span>${c.kind}${c.kind === "Aid station" ? " · " + c.km + " km" : c.kind === "Finish" ? " · " + c.km + " km" : ""}</span></div>
    <div class="rows">${row("Leaders", "lead")}${row("Mid-pack", "mid")}</div>`;
}
let shownCard = -1;

// ---- wind + drizzle streaks (2D overlay, projected from 3D) -------------------------------------------------
const fx = document.getElementById("fx").getContext("2d");
let seed = 11;
const rnd = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
const NW_ = 260, ND = 220;
let streaks = [], drops = [], simT = -1;
function windAt(p) {                                       // race progress -> (dir, speed, precip) from the mid-course series
  const s = R.series, f = Math.min(s.length - 1.001, Math.max(0, p * (R.paces.lead) + 1)), i = Math.floor(f), w = f - i, a = s[i], b = s[i + 1];
  const d = ((b.wd - a.wd + 540) % 360) - 180;
  return { wd: (a.wd + d * w + 360) % 360, ws: a.ws + (b.ws - a.ws) * w, pr: a.pr + (b.pr - a.pr) * w };
}
function resetFx() {
  seed = 11; streaks = []; drops = [];
  for (let n = 0; n < NW_; n++) streaks.push({ x: (rnd() - .5) * WD * 1.3, z: (rnd() - .5) * DD * 1.3, y: 60 + rnd() * 160, age: rnd() * 1.4, life: 1 + rnd() * .8 });
  for (let n = 0; n < ND; n++) drops.push({ x: (rnd() - .5) * WD, z: (rnd() - .5) * DD, y: rnd() * 420 });
  simT = 0;
}
function stepFx(dt, wind) {
  const to = (wind.wd + 180) * Math.PI / 180, vx = Math.sin(to), vz = -Math.cos(to), sp = wind.ws * 6;   // world units/s (visual)
  for (const s of streaks) {
    s.age += dt; s.x += vx * sp * dt; s.z += vz * sp * dt;
    if (s.age > s.life) { s.x = (rnd() - .5) * WD * 1.3; s.z = (rnd() - .5) * DD * 1.3; s.y = 60 + rnd() * 160; s.age = 0; s.life = 1 + rnd() * .8; }
  }
  for (const d of drops) { d.y -= 900 * dt; d.x += vx * sp * .6 * dt; d.z += vz * sp * .6 * dt; if (d.y < 0) { d.y = 420; d.x = (rnd() - .5) * WD; d.z = (rnd() - .5) * DD; } }
}
const proj = v => { const p = v.clone().project(camera); return [(p.x + 1) / 2 * W, (1 - p.y) / 2 * H, p.z]; };
function drawFx(wind) {
  fx.clearRect(0, 0, W, H);
  const to = (wind.wd + 180) * Math.PI / 180, vx = Math.sin(to), vz = -Math.cos(to), L = 26 + wind.ws * .9;
  fx.lineCap = "round";
  for (const s of streaks) {
    const a = proj(new THREE.Vector3(s.x, s.y, s.z)), b = proj(new THREE.Vector3(s.x + vx * L, s.y, s.z + vz * L));
    if (a[2] > 1 || b[2] > 1 || Math.hypot(b[0] - a[0], b[1] - a[1]) > 90) continue;
    const al = Math.sin(Math.PI * Math.min(1, s.age / s.life)) * .55;
    fx.strokeStyle = `rgba(255,255,255,${al.toFixed(3)})`; fx.lineWidth = 2;
    fx.beginPath(); fx.moveTo(a[0], a[1]); fx.lineTo(b[0], b[1]); fx.stroke();
  }
  const rainA = Math.min(.5, wind.pr * 2.5);
  if (rainA > .02) {
    fx.strokeStyle = `rgba(220,232,240,${rainA.toFixed(3)})`; fx.lineWidth = 1.2;
    for (const d of drops) {
      const a = proj(new THREE.Vector3(d.x, d.y, d.z)), b = proj(new THREE.Vector3(d.x + vx * 6, d.y - 22, d.z + vz * 6));
      if (a[2] > 1 || b[2] > 1 || Math.hypot(b[0] - a[0], b[1] - a[1]) > 24) continue;   // skip drops right at the lens
      fx.beginPath(); fx.moveTo(a[0], a[1]); fx.lineTo(b[0], b[1]); fx.stroke();
    }
  }
}

// ---- text ------------------------------------------------------------------------------------------------------
const run = new Date(R.run);
document.getElementById("eyebrow").textContent = `ECT 50 · ${R.start.replace(" · ", " · ")} start`;
const all = R.checkpoints.flatMap(c => Object.values(c.wx));
const tmin = Math.min(...all.map(w => w.t)), tmax = Math.max(...all.map(w => w.t)), wsmax = Math.max(...all.map(w => w.ws)), gmax = Math.max(...all.map(w => w.g));
const wdom = card16(R.checkpoints[1].wx.lead.wd);
document.getElementById("sub").textContent = window.SUB ||
  `Raw on the trail: ${wdom} winds up to ${Math.round(wsmax / 5) * 5} km/h, gusting near ${Math.round(gmax / 5) * 5}, ${tmin}–${tmax}°C with drizzle.`;
document.getElementById("src").innerHTML = `RDPS (ECCC) ${String(run.getUTCHours()).padStart(2, "0")}Z ${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][run.getUTCMonth()]} ${run.getUTCDate()} · even pace: leaders 5 h, mid-pack 8 h<br>Route: ECT 50 GPX · Imagery © Mapbox © Maxar · © OpenStreetMap`;

// ---- camera + timeline -------------------------------------------------------------------------------------------
// schedule: hold at the start, then travel between checkpoints (time in proportion to distance, easing into
// each stop) and pause HOLD seconds at every aid station; the outro starts on arrival at the finish
const SIM_DT = 1 / 120;          // effects step: finer than any render frame rate, so streaks move every frame
const INTRO = 2.2, START_HOLD = 4.0, TRAVEL = 24.0, HOLD = 4.6, OUTRO = 6.2;
const SCHED = [];                                             // {t0, t1, k0, k1} travel legs, holds between them
{ let t = INTRO + START_HOLD; const cps = R.checkpoints;
  for (let i = 1; i < cps.length; i++) {
    const dur = TRAVEL * (cps[i].km - cps[i - 1].km) / R.km;
    SCHED.push({ t0: t, t1: t + dur, k0: cps[i - 1].km, k1: cps[i].km, arrive: t + dur });
    t += dur + (i < cps.length - 1 ? HOLD : 0);
  } }
const FINISH_T = SCHED[SCHED.length - 1].t1;
const ARRIVE = [INTRO].concat(SCHED.map(l => l.arrive));      // when each checkpoint is reached (start: when the run begins)
window.ANIM_LEN = FINISH_T + OUTRO;
function kmAt(t) {
  if (t <= SCHED[0].t0) return 0;
  for (const l of SCHED) {
    if (t < l.t0) return l.k0;                                // holding at the previous stop
    if (t <= l.t1) return l.k0 + (l.k1 - l.k0) * ease((t - l.t0) / (l.t1 - l.t0));
  }
  return R.km;
}
const ease = x => (x = Math.min(1, Math.max(0, x)), x < .5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
const back = x => { x = Math.min(1, Math.max(0, x)); const c = 1.4; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
const OVER = { pos: new THREE.Vector3(1150, 3500, 2350), tgt: new THREE.Vector3(-40, 0, 380) };          // whole course from the southeast
if (TVW) { OVER.pos.sub(OVER.tgt).multiplyScalar(1.42).add(OVER.tgt); scene.fog.near *= 1.42; scene.fog.far *= 1.42; }   // pull back for the narrower lens
const FOLLOW = new THREE.Vector3(520, 430, -560);                 // behind (north of) and above the runner, looking south-west
const lerpV = (a, b, f) => a.clone().lerp(b, f);
function runnerAt(p) { return curve.getPointAt(uAtKm(p * R.km)); }
// camera track: the route smoothed with a wide Gaussian (sigma ~1.5 km) so the camera glides along the coast
// instead of copying every switchback; the runner marker itself stays on the real trail
const CAM_N = 1000, CAM_SIG = 1.5 / R.km * CAM_N;
const camRaw = Array.from({ length: CAM_N + 1 }, (_, i) => runnerAt(i / CAM_N));
const camTrack = camRaw.map((_, i) => {
  const v = new THREE.Vector3(); let wsum = 0;
  for (let k = -Math.ceil(CAM_SIG * 3); k <= Math.ceil(CAM_SIG * 3); k++) {
    const j = Math.min(CAM_N, Math.max(0, i + k)), w = Math.exp(-k * k / (2 * CAM_SIG * CAM_SIG));
    v.addScaledVector(camRaw[j], w); wsum += w;
  }
  return v.multiplyScalar(1 / wsum);
});
function smoothRunner(p) {
  const f = Math.min(CAM_N - 1e-6, Math.max(0, p * CAM_N)), i = Math.floor(f);
  return camTrack[i].clone().lerp(camTrack[Math.min(CAM_N, i + 1)], f - i);
}
const top = document.querySelector(".top");

window.setT = function (t) {
  const p = kmAt(t) / R.km;                                       // race progress 0..1 along the course
  const rpos = runnerAt(p), look = smoothRunner(p);
  const followPos = look.clone().add(FOLLOW), followTgt = look.clone().add(new THREE.Vector3(-40, 0, 60));
  const into = ease((t - INTRO + 1.2) / 2.4), out = ease((t - FINISH_T - .3) / (OUTRO - .6));
  let cp = lerpV(OVER.pos, followPos, into), ct = lerpV(OVER.tgt, followTgt, into);
  cp = lerpV(cp, OVER.pos, out); ct = lerpV(ct, OVER.tgt, out);
  camera.position.copy(cp); camera.lookAt(ct); camera.updateMatrixWorld();
  const u = uAtKm(p * R.km);
  tube.geometry.setDrawRange(0, Math.floor(u * SEG) * RAD * 6);
  casing.geometry.setDrawRange(0, Math.floor(u * SEG) * RAD * 6);
  runner.position.copy(rpos).add(new THREE.Vector3(0, 6, 0)); halo.position.copy(runner.position);
  halo.scale.setScalar(1 + .25 * Math.sin(t * 6));
  renderer.render(scene, camera);
  // tags
  const km = p * R.km;
  let cur = 0; R.checkpoints.forEach((c, i) => { if (km >= c.km - 0.05) cur = i; });
  pins.forEach((o, i) => {
    const q = proj(o.p);
    o.el.style.transform = `translate(${q[0]}px,${q[1]}px)`;
    o.el.style.opacity = q[2] < 1 ? Math.min(1, (t - .6 - i * .15) / .5) : 0;
    o.el.classList.toggle("on", i === cur);
  });
  // card: pops each time the runner reaches a checkpoint; finish card stays for the outro
  if (cur !== shownCard) { CARD.innerHTML = cardHtml(R.checkpoints[cur]); shownCard = cur; }
  const reach = ARRIVE[cur];
  const k = (t - Math.max(reach, INTRO * .6)) / .4;
  CARD.style.transform = `scale(${Math.max(.001, k <= 0 ? 0 : back(k))})`; CARD.style.opacity = Math.min(1, Math.max(0, k * 2));
  document.getElementById("km").textContent = km.toFixed(1);
  document.getElementById("barfill").style.width = (p * 100).toFixed(2) + "%";
  // wind + drizzle
  const wind = windAt(p);
  if (simT < 0 || t < simT - 1e-6 || t - simT > 3) resetFx();
  while (simT + SIM_DT <= t + 1e-6) { stepFx(SIM_DT, wind); simT += SIM_DT; }
  drawFx(wind);
  top.style.opacity = ease((t - .1) / .6);
};
window.setT(0);
window.__cam = camera;          // for tests
window.READY = true;
