// Lot 201 viewer. Scroll drives a list of camera stops; each stop also says which parts of the
// building are shown (roof, first floor) and which apartment is lit up.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const $ = (id) => document.getElementById(id);
const stage = $('stage'), canvas = $('gl'), story = $('story'), labelsEl = $('labels');
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const smooth = (t) => t * t * (3 - 2 * t);
const reduced = matchMedia('(prefers-reduced-motion: reduce)');

const data = await (await fetch('assets/building.json')).json();
const [W, D] = data.extent;
const zOf = (level) => data.level_z[level];
// plan metres (x east, y north, h up) -> scene, with the building centred on the origin
const toWorld = (x, y, h = 0) => new THREE.Vector3(x - W / 2, h, -(y - D / 2));

// ----------------------------------------------------------------- story text
const units = data.apartments;
const byLevel = (lv) => units.filter((u) => u.level === lv);
const totalSqft = units.reduce((n, u) => n + u.area_sqft, 0);
const fmt = (n) => n.toLocaleString('en-US');

function unitChapter(u) {
  const rooms = u.rooms.map((r) => `<li><span>${r.name}</span><span>${r.size ? r.size.replace(' x ', ' × ') : '—'}</span></li>`).join('');
  return {
    id: u.id, view: u.name, roof: 0, first: u.level === 'first' ? 1 : 0, unit: u.id, stop: () => stopUnit(u),
    html: `<p class="eyebrow" style="--dot:${u.color}"><i></i>${u.level === 'first' ? 'First floor' : 'Ground floor'} · ${u.type}</p>
      <h2>${u.name}</h2>
      <div class="facts"><div><b>${fmt(u.area_sqft)}</b><span>sq ft</span></div><div><b>${Math.round(u.area_m2)}</b><span>m²</span></div><div><b>${u.rooms.length}</b><span>spaces</span></div></div>
      <ul class="rooms">${rooms}</ul>`,
  };
}

const chapters = [
  { id: 'intro', view: 'Exterior', roof: 1, first: 1, unit: null, stop: stopExterior,
    html: `<p class="eyebrow"><i></i>Proposed residential building</p>
      <h1>Eight homes.<br><em>Two floors.</em></h1>
      <p>Lot 201, Oxford, Manchester. Every wall here was traced from the architect's floor plans, then raised into 3D. Scroll to take the building apart.</p>
      <div class="facts"><div><b>${units.length}</b><span>apartments</span></div><div><b>${fmt(totalSqft)}</b><span>sq ft of homes</span></div><div><b>${Math.round(W * 3.2808)} × ${Math.round(D * 3.2808)}</b><span>ft footprint</span></div></div>
      <a class="next" href="#first">Open it up</a>` },
  { id: 'first', view: 'First floor', roof: 0, first: 1, unit: null, stop: () => stopLevel('first'),
    html: `<p class="eyebrow"><i></i>Level 02</p><h2>The roof <em>lifts off.</em></h2>
      <p>Four homes share the first floor: one two-bedroom at the back and three one-bedrooms along the front, joined by an open deck that looks over the street.</p>
      <ul class="rooms">${byLevel('first').map((u) => `<li><span>${u.name} · ${u.type}</span><span>${fmt(u.area_sqft)} sq ft</span></li>`).join('')}</ul>` },
  ...byLevel('first').map(unitChapter),
  { id: 'ground', view: 'Ground floor', roof: 0, first: 0, unit: null, stop: () => stopLevel('ground'),
    html: `<p class="eyebrow"><i></i>Level 01</p><h2>One level <em>down.</em></h2>
      <p>The ground floor repeats the idea: a two-bedroom behind, three one-bedrooms in front, each with its own covered entry. Laundry and a two-car port sit at the east end.</p>
      <ul class="rooms">${byLevel('ground').map((u) => `<li><span>${u.name} · ${u.type}</span><span>${fmt(u.area_sqft)} sq ft</span></li>`).join('')}</ul>` },
  ...byLevel('ground').map(unitChapter),
  { id: 'end', view: 'Exterior', roof: 1, first: 1, unit: null, stop: stopExterior,
    html: `<p class="eyebrow"><i></i>All together</p><h2>Back in <em>one piece.</em></h2>
      <p>Use <strong>Furnished / Empty</strong> at the top to clear the rooms, or <strong>Explore freely</strong> to orbit the model and jump to any home.</p>
      <p class="note">Walls, doors, windows, counters and fixtures follow drawings 003 and 004. Heights, finishes, colours and furniture are placeholders until elevations arrive. The lower ground floor is not modelled.</p>` },
];
story.innerHTML = chapters.map((c) => `<section class="chapter" id="${c.id}" data-chapter>${c.html}</section>`).join('');
const chapterEls = [...story.querySelectorAll('[data-chapter]')];

// ------------------------------------------------------- phone caption card
// On narrow screens the story column is hidden (its sections stay as invisible scroll spacers so
// scrolling still drives the camera) and the current section shows in a card under the model.
let capIndex = -1;
function setCaption(i) {
  if (i === capIndex) return;
  capIndex = i;
  const el = chapterEls[i];
  $('capEyebrow').textContent = `${String(i + 1).padStart(2, '0')} / ${chapterEls.length} · ${el.querySelector('.eyebrow').textContent}`;
  $('capTitle').innerHTML = el.querySelector('h1, h2').innerHTML.replace(/<br\s*\/?>/g, ' ');
  $('capBody').innerHTML = el.innerHTML;
  $('capPrev').disabled = i === 0;
  $('capNext').disabled = i === chapterEls.length - 1;
}
function setCaptionOpen(open) {
  $('capToggle').setAttribute('aria-expanded', String(open));
  $('capBody').hidden = !open;
  $('capMore').textContent = open ? 'Hide' : 'Details';
  document.body.classList.toggle('caption-open', open);
}
let capTarget = null;   // section a prev/next tap is still smooth-scrolling towards
function goToChapter(i) {
  capTarget = i;
  // Land a little way into the section so the camera has arrived and is holding still.
  const r = chapterEls[i].getBoundingClientRect();
  scrollTo({ top: scrollY + r.top - innerHeight * 0.5 + r.height * 0.2 });
}
addEventListener('scrollend', () => { capTarget = null; });
const step = (d) => goToChapter(clamp((capTarget ?? capIndex) + d, 0, chapterEls.length - 1));
$('capToggle').addEventListener('click', () => setCaptionOpen($('capBody').hidden));
$('capPrev').addEventListener('click', () => step(-1));
$('capNext').addEventListener('click', () => step(1));
$('capBody').addEventListener('click', (e) => {
  const a = e.target.closest('a[href^="#"]');
  if (!a) return;
  e.preventDefault();
  goToChapter(chapterEls.findIndex((c) => `#${c.id}` === a.getAttribute('href')));
});
if (matchMedia('(pointer: coarse)').matches) $('dockHint').textContent = 'Drag to orbit · pinch to zoom · two-finger drag to pan';
setCaption(0);

// ---------------------------------------------------------------- 3D set-up
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
} catch (e) {
  $('loader').remove();
  $('fail').hidden = false;
  throw e;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.92;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(32, 1, 0.5, 400);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.35;
scene.add(new THREE.HemisphereLight(0xfff4e2, 0x7d7868, 0.55));
const sun = new THREE.DirectionalLight(0xfff1dc, 2.9);
sun.position.set(-22, 38, 26);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -30, right: 30, top: 26, bottom: -26, near: 1, far: 140 });
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.04;
sun.shadow.radius = 3;
scene.add(sun);

// ------------------------------------------------------------- camera stops
// A stop is "look at this point, from this direction, far enough back to fit this much".
function stop(target, dir, spanW, spanH) {
  const v = THREE.MathUtils.degToRad(camera.fov) / 2;
  const h = Math.atan(Math.tan(v) * camera.aspect);
  const dist = Math.max(spanW / (2 * Math.tan(h)), spanH / (2 * Math.tan(v))) * 1.06;
  return { tgt: target, pos: target.clone().add(dir.normalize().multiplyScalar(dist)) };
}
function stopExterior() { return stop(toWorld(W / 2, D * 0.45, 2.4), new THREE.Vector3(0.34, 0.4, 0.85), W + 5, 17); }
function stopLevel(level) { return stop(toWorld(W / 2, D / 2 - 0.5, zOf(level) + 0.5), new THREE.Vector3(0.05, 0.9, 0.44), W + 3, D * 0.95 + 4); }
function stopUnit(u) {
  const [x0, y0, x1, y1] = u.bbox;
  return stop(toWorld((x0 + x1) / 2, (y0 + y1) / 2 - 0.4, zOf(u.level) + 0.6), new THREE.Vector3(0.1, 0.9, 0.42),
    (x1 - x0) + 4.5, (y1 - y0) * 0.95 + 5.5);
}

// ------------------------------------------------------------ model + fades
const parts = {};                 // roof, first, ground, firstFurn, groundFurn: { group, mats }
const unitMats = {};              // apartment id -> floor materials to tint
const unitGlow = Object.fromEntries(units.map((u) => [u.id, 0]));
const tags = [];
let root;

function under(o, group) { for (let p = o; p; p = p.parent) if (p === group) return true; return false; }

function adopt(group, key, furnGroup, furnKey) {
  // Each part gets its own copies of the materials so it can fade without touching the others.
  parts[key] = { group, mats: [] };
  if (furnGroup) parts[furnKey] = { group: furnGroup, mats: [] };
  const cache = new Map();
  group.traverse((o) => {
    if (!o.isMesh) return;
    const furn = furnGroup && under(o, furnGroup);
    const room = o.userData.kind === 'room' ? o.userData.unit || 'common' : '';
    const k = `${furn ? 'f' : 's'}|${room}|${o.material.name}`;
    let m = cache.get(k);
    if (!m) {
      m = o.material.clone();
      m.userData.base = { opacity: m.opacity, transparent: m.transparent, color: m.color.clone() };
      if (m.transparent) m.depthWrite = false;
      cache.set(k, m);
      parts[furn ? furnKey : key].mats.push(m);
      if (room && room !== 'common') (unitMats[room] ||= []).push(m);
    }
    o.material = m;
    o.castShadow = !m.userData.base.transparent && !/rug/.test(o.name);
    o.receiveShadow = true;
  });
}

function setFade(part, v, lift = 0) {
  part.group.visible = v > 0.01;
  if (lift) part.group.position.y = (1 - smooth(v)) * lift;
  for (const m of part.mats) {
    const b = m.userData.base;
    const see = b.transparent || v < 0.995;
    if (m.transparent !== see) { m.transparent = see; m.needsUpdate = true; }
    m.opacity = b.opacity * v;
    m.depthWrite = !b.transparent && v > 0.35;
  }
}

function makeTags() {
  for (const u of units) {
    for (const r of u.rooms) {
      const el = document.createElement('div');
      el.className = 'tag';
      el.innerHTML = `${r.name}${r.size ? `<small>${r.size.replace(' x ', ' × ')}</small>` : ''}`;
      labelsEl.append(el);
      tags.push({ el, unit: u.id, at: toWorld(r.at[0], r.at[1], zOf(u.level) + 1.5) });
    }
  }
}

// --------------------------------------------------------------- live state
const want = { ...stopExterior(), roof: 1, first: 1, unit: null, furn: 1, view: 'Exterior' };
const cur = { pos: want.pos.clone(), tgt: want.tgt.clone(), roof: 1, first: 1, furn: 1 };
let exploring = false, controls = null, fly = null, dirty = true, last = performance.now(), savedScroll = 0;

function fromScroll() {
  if (exploring) return;
  // A chapter becomes current when its top crosses this line (middle of the readable area).
  const anchor = innerHeight * 0.5;
  let i = 0;
  for (let k = 0; k < chapterEls.length; k++) if (chapterEls[k].getBoundingClientRect().top <= anchor) i = k;
  setCaption(i);
  const rect = chapterEls[i].getBoundingClientRect();
  const frac = clamp((anchor - rect.top) / rect.height);
  const a = chapters[i], b = chapters[Math.min(i + 1, chapters.length - 1)];
  let t = a === b ? 0 : smooth(clamp((frac - 0.62) / 0.38));  // hold while the text is read, then travel
  if (reduced.matches) t = t > 0.5 ? 1 : 0;
  const sa = a.stop(), sb = b.stop();
  want.pos.lerpVectors(sa.pos, sb.pos, t);
  want.tgt.lerpVectors(sa.tgt, sb.tgt, t);
  want.roof = a.roof + (b.roof - a.roof) * t;
  want.first = a.first + (b.first - a.first) * t;
  const lead = t > 0.5 ? b : a;
  want.unit = lead.unit;
  if (want.view !== lead.view) { want.view = lead.view; $('sheetView').textContent = lead.view; }
  dirty = true;
}

function frame(now) {
  requestAnimationFrame(frame);
  update(now);
}

function update(now, snap = false) {
  const dt = Math.min(0.25, (now - last) / 1000);   // generous cap so a throttled tab still catches up
  last = now;
  if (!root) return;
  if (snap) dirty = true;
  const k = snap || reduced.matches ? 1 : 1 - Math.exp(-dt * 5.5);
  let moving = false;
  const ease = (key) => {
    const d = want[key] - cur[key];
    if (Math.abs(d) > 0.002) { cur[key] += d * k; moving = true; } else cur[key] = want[key];
  };
  ease('roof'); ease('first'); ease('furn');
  for (const u of units) {
    const goal = want.unit === u.id ? 1 : 0;
    const d = goal - unitGlow[u.id];
    if (Math.abs(d) > 0.004) { unitGlow[u.id] += d * k; moving = true; } else unitGlow[u.id] = goal;
  }

  if (fly) {                                      // a button asked the camera to travel somewhere
    fly.t = Math.min(1, fly.t + dt / 0.9);
    const e = smooth(fly.t);
    camera.position.lerpVectors(fly.p0, fly.p1, e);
    controls.target.lerpVectors(fly.t0, fly.t1, e);
    camera.lookAt(controls.target);
    moving = true;
    if (fly.t === 1) { fly = null; controls.enabled = true; controls.update(); }
  } else if (exploring) {
    if (controls.update()) moving = true;
  } else {
    if (cur.pos.distanceToSquared(want.pos) > 1e-5 || cur.tgt.distanceToSquared(want.tgt) > 1e-5) {
      cur.pos.lerp(want.pos, k); cur.tgt.lerp(want.tgt, k); moving = true;
    }
    camera.position.copy(cur.pos);
    camera.lookAt(cur.tgt);
  }
  if (!moving && !dirty) return;
  dirty = false;

  setFade(parts.roof, cur.roof, 7);
  setFade(parts.first, cur.first, 6);
  setFade(parts.ground, 1);
  setFade(parts.firstFurn, cur.first * cur.furn);
  setFade(parts.groundFurn, cur.furn);
  for (const u of units) {
    const tint = new THREE.Color(u.color);
    for (const m of unitMats[u.id] || []) m.color.copy(m.userData.base.color).lerp(tint, 0.62 * unitGlow[u.id]);
  }
  renderer.render(scene, camera);

  const w = stage.clientWidth, h = stage.clientHeight, v = new THREE.Vector3();
  for (const t of tags) {
    v.copy(t.at).project(camera);
    const on = unitGlow[t.unit] > 0.6 && v.z < 1 && Math.abs(v.x) < 0.96 && Math.abs(v.y) < 0.94;
    t.el.classList.toggle('on', on);
    if (on) t.el.style.transform = `translate(-50%,-50%) translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px)`;
  }
}

function resize() {
  const w = stage.clientWidth, h = stage.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  fromScroll();
  dirty = true;
}

// ------------------------------------------------------------------ controls
function setFurniture(on) {
  want.furn = on ? 1 : 0;
  document.querySelectorAll('[data-furniture]').forEach((b) => b.setAttribute('aria-pressed', String((b.dataset.furniture === 'on') === on)));
  dirty = true;
}
document.querySelectorAll('[data-furniture]').forEach((b) => b.addEventListener('click', () => setFurniture(b.dataset.furniture === 'on')));

function flyTo(s) {
  fly = { t: 0, p0: camera.position.clone(), t0: controls.target.clone(), p1: s.pos, t1: s.tgt };
  controls.enabled = false;
}
function pick(chip, state) {
  $('dock').querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', String(c === chip)));
  Object.assign(want, { roof: state.roof, first: state.first, unit: state.unit });
  $('sheetView').textContent = state.view;
  flyTo(state.stop());
}
function buildDock() {
  const chip = (label, state, color) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'chip'; b.setAttribute('aria-pressed', 'false');
    b.innerHTML = `${color ? `<i style="--dot:${color}"></i>` : ''}${label}`;
    b.addEventListener('click', () => pick(b, state));
    return b;
  };
  $('dockLevels').append(
    chip('Whole building', { roof: 1, first: 1, unit: null, view: 'Exterior', stop: stopExterior }),
    chip('First floor', { roof: 0, first: 1, unit: null, view: 'First floor', stop: () => stopLevel('first') }),
    chip('Ground floor', { roof: 0, first: 0, unit: null, view: 'Ground floor', stop: () => stopLevel('ground') }));
  for (const u of units) {
    $('dockUnits').append(chip(u.name, { roof: 0, first: u.level === 'first' ? 1 : 0, unit: u.id, view: u.name, stop: () => stopUnit(u) }, u.color));
  }
}
function setExploring(on) {
  exploring = on;
  $('exploreBtn').setAttribute('aria-pressed', String(on));
  $('exploreBtn').textContent = on ? 'Back to story' : 'Explore';
  if (on) setCaptionOpen(false);
  if (on) savedScroll = scrollY;
  document.body.classList.toggle('exploring', on);
  $('dock').hidden = !on;
  if (on) {
    controls.target.copy(cur.tgt);
    camera.position.copy(cur.pos);
    controls.enabled = true;
    controls.update();
  } else {
    controls.enabled = false;
    fly = null;
    cur.pos.copy(camera.position);
    cur.tgt.copy(controls.target);
    scrollTo({ top: savedScroll, behavior: 'instant' });
  }
  resize();
}
$('exploreBtn').addEventListener('click', () => setExploring(!exploring));
addEventListener('keydown', (e) => { if (e.key === 'Escape' && exploring) setExploring(false); });

// ---------------------------------------------------------------------- load
new GLTFLoader().load('assets/clint.glb', (gltf) => {
  root = gltf.scene;
  root.position.set(-W / 2, 0, D / 2);
  scene.add(root);
  const get = (n) => root.getObjectByName(n);
  adopt(get('Roof'), 'roof');
  adopt(get('L1'), 'first', get('L1_Furniture'), 'firstFurn');
  adopt(get('L0'), 'ground', get('L0_Furniture'), 'groundFurn');
  get('Site').traverse((o) => { if (o.isMesh) o.receiveShadow = true; });
  makeTags();

  controls = new OrbitControls(camera, canvas);
  Object.assign(controls, { enabled: false, enableDamping: true, dampingFactor: 0.08, maxPolarAngle: Math.PI * 0.49, minDistance: 6, maxDistance: 120 });
  controls.addEventListener('change', () => { dirty = true; });
  buildDock();

  addEventListener('scroll', fromScroll, { passive: true });
  new ResizeObserver(resize).observe(stage);
  resize();
  cur.pos.copy(want.pos); cur.tgt.copy(want.tgt);
  $('loader').classList.add('done');
  requestAnimationFrame(frame);
  window.__viewer = { want, cur, parts, setFurniture, setExploring, units, camera,
    snap: () => { fromScroll(); if (fly) fly.t = 0.9999; update(performance.now(), true); update(performance.now(), true); } };   // handy in the console
}, (e) => { if (e.total) $('loadBar').style.width = `${(e.loaded / e.total) * 100}%`; }, (err) => {
  console.error(err);
  $('loader').remove();
  $('fail').hidden = false;
  $('fail').textContent = 'The 3D model did not load. Serve the web folder over http (see README) and reload.';
});
