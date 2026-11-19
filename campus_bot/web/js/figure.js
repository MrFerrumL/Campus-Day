// A clean mannequin that performs each exercise: two key poses (traced from the
// Free Exercise DB photos, see poses.js) eased into a loop, working muscles in red,
// helpers in amber, simple equipment drawn from the exercise's gear.
import { JOINTS, POSES } from './poses.js';
import { esc } from './util.js';

const W = 200;
const H = 150;
const FLOOR = 141;
const DURATION = 3.2;
// Hold the start pose, move, hold the end pose, return — eased like a real repetition.
const TIMING = 'keyTimes="0;0.14;0.5;0.64;1" calcMode="spline" keySplines="0 0 1 1;.45 0 .55 1;0 0 1 1;.45 0 .55 1"';

// Which drawn part shows each muscle. The torso is split: chest and belly in front, back behind.
const PART_OF = {
  chest: 'chest', abs: 'belly', obliques: 'belly', lats: 'back', midback: 'back', lowerback: 'back', traps: 'back',
  shoulders: 'delt', biceps: 'upper', triceps: 'upper', forearms: 'fore', quads: 'thigh', hamstrings: 'thigh',
  adductors: 'thigh', abductors: 'back-hip', glutes: 'back-hip', calves: 'shin',
};

const round = (n) => Math.round(n * 10) / 10;
const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const pt = (p) => `${round(p[0])} ${round(p[1])}`;
const line = (...points) => `M${points.map(pt).join(' L')}`;
const shape = (...points) => `${line(...points)} Z`;
const along = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
const offset = (q, n, k) => [q[0] + n[0] * k, q[1] + n[1] * k];

function joints(frame) {
  const p = {};
  JOINTS.forEach((name, i) => { p[name] = [frame[2 * i], frame[2 * i + 1]]; });
  p.neck = mid(p.shL, p.shR);
  p.pelvis = mid(p.hipL, p.hipR);
  p.head = mid(p.earL, p.earR);
  return p;
}

function levels(primary = [], secondary = []) {
  const out = {};
  for (const m of secondary) if (PART_OF[m]) out[PART_OF[m]] = 'half';
  for (const m of primary) if (PART_OF[m]) out[PART_OF[m]] = 'on';
  return out;
}

/** A limb segment that narrows from one joint to the next, with a soft rounded outline. */
function taper(a, b, wa, wb) {
  const len = dist(a, b) || 1;
  const n = [-(b[1] - a[1]) / len, (b[0] - a[0]) / len];
  return shape(offset(a, n, wa / 2), offset(b, n, wb / 2), offset(b, n, -wb / 2), offset(a, n, -wa / 2));
}

/** Torso halves along the spine: front (chest, belly) and back, facing the way the nose points. */
function torso(p, unit, view) {
  const spine = [p.neck, along(p.neck, p.pelvis, 0.28), along(p.neck, p.pelvis, 0.66), p.pelvis];
  const len = dist(p.neck, p.pelvis) || 1;
  let n = [-(p.pelvis[1] - p.neck[1]) / len, (p.pelvis[0] - p.neck[0]) / len];
  const face = [p.nose[0] - p.head[0], p.nose[1] - p.head[1]];
  if (n[0] * face[0] + n[1] * face[1] < 0) n = [-n[0], -n[1]];
  const k = unit;
  if (view === 'front') {
    const half = [0.34, 0.5, 0.32, 0.4].map((v) => v * k);
    const side = (sign) => spine.map((q, i) => offset(q, n, sign * half[i]));
    const [l, r] = [side(1), side(-1)];
    return [
      { part: 'chest', depth: 'mid', d: shape(l[0], l[1], l[2], r[2], r[1], r[0]) },
      { part: 'belly', depth: 'mid', d: shape(l[2], l[3], r[3], r[2]) },
    ];
  }
  const front = [0.14, 0.24, 0.19, 0.2].map((v) => v * k);
  const back = [0.13, 0.2, 0.16, 0.24].map((v) => v * k);
  const f = spine.map((q, i) => offset(q, n, front[i]));
  const b = spine.map((q, i) => offset(q, n, -back[i]));
  return [
    { part: 'back', depth: 'mid', d: shape(spine[0], b[0], b[1], b[2], spine[2]) },
    { part: 'back-hip', depth: 'mid', d: shape(spine[2], b[2], b[3], spine[3]) },
    { part: 'chest', depth: 'mid', d: shape(spine[0], f[0], f[1], f[2], spine[2]) },
    { part: 'belly', depth: 'mid', d: shape(spine[2], f[2], f[3], spine[3]) },
  ];
}

/* Each shape is described per frame; frames with the same structure animate smoothly. */
function shapes(p, near, unit, gear, view, extra) {
  const far = near === 'L' ? 'R' : 'L';
  const k = unit;
  // A cable runs from its pulley to the near hand; a leg-press sled sits under the soles.
  const cable = extra.cable ? [{ part: 'cable', w: 0.045, d: line(extra.cable, p['wr' + near]) }] : [];
  let sled = [];
  if (extra.sled) {
    const a = p['he' + near];
    const b = p['to' + near];
    const len = dist(a, b) || 1;
    const v = [(b[0] - a[0]) / len, (b[1] - a[1]) / len];
    sled = [{ part: 'sled', w: 0.2, d: line([a[0] - v[0] * 7, a[1] - v[1] * 7], [b[0] + v[0] * 7, b[1] + v[1] * 7]) }];
  }
  const limb = (side, depth) => [
    { part: 'thigh', depth, d: taper(p['hip' + side], p['kn' + side], 0.46 * k, 0.3 * k) },
    { part: 'shin', depth, d: taper(p['kn' + side], p['an' + side], 0.3 * k, 0.17 * k) },
    { part: 'knee', depth, r: 0.15, c: p['kn' + side] },
    { part: 'foot', depth, w: 0.16, d: line(p['he' + side], p['to' + side]) },
  ];
  const arm = (side, depth) => [
    { part: 'upper', depth, d: taper(p['sh' + side], p['el' + side], 0.3 * k, 0.21 * k) },
    { part: 'fore', depth, d: taper(p['el' + side], p['wr' + side], 0.21 * k, 0.14 * k) },
    { part: 'elbow', depth, r: 0.105, c: p['el' + side] },
    { part: 'hand', depth, r: 0.09, c: p['wr' + side] },
    { part: 'delt', depth, r: 0.17, c: p['sh' + side] },
  ];
  const body = [
    ...torso(p, unit, view),
    { part: 'neck', depth: 'mid', w: 0.17, d: line(p.neck, p.head) },
    { part: 'head', depth: 'mid', r: 0.26, c: p.head },
  ];
  return [...cable, ...gearShapes(p, unit, gear, view, 'back'), ...arm(far, 'far'), ...limb(far, 'far'), ...body,
    ...limb(near, 'near'), ...arm(near, 'near'), ...sled, ...gearShapes(p, unit, gear, view, 'front')];
}

function gearShapes(p, unit, gear, view, layer) {
  const hands = mid(p.wrL, p.wrR);
  if (gear === 'barbell') {
    if (view === 'front') {
      const dx = p.wrR[0] - p.wrL[0] || 1;
      const dy = p.wrR[1] - p.wrL[1];
      const k = unit * 0.75 / Math.hypot(dx, dy);
      const a = [p.wrL[0] - dx * k, p.wrL[1] - dy * k];
      const b = [p.wrR[0] + dx * k, p.wrR[1] + dy * k];
      return layer === 'front' ? [{ part: 'bar', w: 0.07, d: line(a, b) }, { part: 'plate', w: 0.18, d: line([a[0], a[1] - unit * 0.45], [a[0], a[1] + unit * 0.45]) },
        { part: 'plate', w: 0.18, d: line([b[0], b[1] - unit * 0.45], [b[0], b[1] + unit * 0.45]) }] : [];
    }
    return layer === 'back' ? [{ part: 'plate', r: 0.4, c: hands }] : [{ part: 'hub', r: 0.1, c: hands }];
  }
  if (gear === 'dumbbell' && layer === 'front') {
    return ['wrL', 'wrR'].map((j) => ({ part: 'bell', r: 0.17, c: p[j] }));
  }
  if (gear === 'kettlebell' && layer === 'front') return [{ part: 'bell', r: 0.24, c: [hands[0], hands[1] + unit * 0.2] }];
  return [];
}

function attrsFor(shape, frames, unit) {
  if (shape.c) {
    const xs = frames.map((s) => round(s.c[0]));
    const ys = frames.map((s) => round(s.c[1]));
    return { tag: 'circle', base: `cx="${xs[0]}" cy="${ys[0]}" r="${round(shape.r * unit)}"`, anim: [['cx', xs], ['cy', ys]] };
  }
  if (shape.w == null) return { tag: 'path', base: `d="${frames[0].d}"`, anim: [['d', frames.map((s) => s.d)]] };
  const stroke = round(shape.w * unit);
  return { tag: 'path', base: `d="${frames[0].d}" stroke-width="${stroke}"`, anim: [['d', frames.map((s) => s.d)]] };
}

function animate(name, values) {
  if (values.every((v) => v === values[0])) return '';
  const [a, b] = values;
  return `<animate attributeName="${name}" dur="${DURATION}s" repeatCount="indefinite" values="${a};${a};${b};${b};${a}" ${TIMING}/>`;
}

function staticGear(p, unit, gear, view, data) {
  const parts = [`<path class="floor" d="M14 ${FLOOR}H186"/>`];
  if (data.bar) {
    const y = round(Math.min(p.wrL[1], p.wrR[1]) - unit * 0.05);
    parts.push(`<path class="gear-line" d="M${round(Math.min(p.wrL[0], p.wrR[0]) - unit * 0.7)} ${y}H${round(Math.max(p.wrL[0], p.wrR[0]) + unit * 0.7)}" stroke-width="${round(unit * 0.1)}"/>`);
  }
  if (data.wall) {
    const x = round(Math.max(p.wrL[0], p.wrR[0]) + unit * 0.12);
    parts.push(`<path class="gear-line" d="M${x} 8V${FLOOR}" stroke-width="${round(unit * 0.12)}"/>`);
  }
  const gearLine = (d, w) => `<path class="gear-line" d="${d}" stroke-width="${round(unit * w)}"/>`;
  if (data.tread) {
    const xs = [p.toL[0], p.toR[0], p.heL[0], p.heR[0]];
    const front = Math.max(...xs) + unit * 0.5;
    parts.push(gearLine(`M${round(Math.min(...xs) - unit * 0.6)} ${FLOOR - 3}H${round(front)}`, 0.16));
    parts.push(gearLine(`M${round(front)} ${FLOOR - 3}L${round(front + unit * 0.15)} ${round(p.neck[1] + unit * 0.4)}`, 0.1));
  }
  if (data.bike) {
    const wheel = [p.pelvis[0] + unit * 0.75, FLOOR - unit * 0.42];
    parts.push(`<circle class="gear-wheel" cx="${round(wheel[0])}" cy="${round(wheel[1])}" r="${round(unit * 0.4)}" stroke-width="${round(unit * 0.09)}"/>`);
    parts.push(gearLine(`M${round(p.pelvis[0] - unit * 0.2)} ${round(p.pelvis[1] + unit * 0.12)}H${round(p.pelvis[0] + unit * 0.2)}`, 0.13));
    parts.push(gearLine(`M${round(p.pelvis[0])} ${round(p.pelvis[1] + unit * 0.12)}L${round(wheel[0])} ${round(wheel[1])}`
      + `L${round(p.wrL[0])} ${round(p.wrL[1])}M${round(p.pelvis[0])} ${round(p.pelvis[1] + unit * 0.12)}V${FLOOR}`, 0.1));
  }
  // Hand-built poses list their equipment; traced ones get it guessed from the pose.
  if (data.props) {
    for (const [width, flat] of data.props) {
      const pts = [];
      for (let i = 0; i < flat.length; i += 2) pts.push([flat[i], flat[i + 1]]);
      parts.push(`<path class="gear-line" d="${line(...pts)}" stroke-width="${width}"/>`);
    }
    return parts.join('');
  }
  const neck = p.neck;
  const pelvis = p.pelvis;
  const lying = Math.abs(neck[1] - pelvis[1]) < 0.55 * Math.abs(neck[0] - pelvis[0]);
  const lowHands = Math.min(p.wrL[1], p.wrR[1]);
  if (lying && ['barbell', 'dumbbell', 'machine'].includes(gear) && Math.max(neck[1], pelvis[1]) < FLOOR - unit * 0.6) {
    const top = Math.max(neck[1], pelvis[1]) + unit * 0.32;
    const x0 = Math.min(neck[0], pelvis[0]) - unit * 0.35;
    const x1 = Math.max(neck[0], pelvis[0]) + unit * 0.35;
    parts.push(`<path class="gear-line" d="M${round(x0)} ${round(top)}H${round(x1)}M${round(x0 + unit * 0.3)} ${round(top)}V${FLOOR}M${round(x1 - unit * 0.3)} ${round(top)}V${FLOOR}" stroke-width="${round(unit * 0.16)}"/>`);
  } else if (gear === 'mat' || (lying && gear === 'bodyweight')) {
    parts.push(`<path class="mat" d="M30 ${FLOOR - 1}H170" stroke-width="4"/>`);
  }
  // Reclined on an incline bench: a backrest behind the spine and a seat under the hips.
  const spine = [neck[0] - pelvis[0], neck[1] - pelvis[1]];
  const tilt = Math.atan2(Math.abs(spine[0]), -spine[1]) * 180 / Math.PI;
  const facing = Math.sign(p.nose[0] - p.head[0]) || 1;
  if (!lying && view === 'side' && tilt > 18 && tilt < 72 && Math.sign(spine[0]) === -facing
      && ['machine', 'dumbbell', 'barbell'].includes(gear)) {
    const len = Math.hypot(...spine) || 1;
    const back = [-facing * Math.abs(spine[1]) / len, -Math.abs(spine[0]) / len];
    const a0 = [pelvis[0] + back[0] * unit * 0.32, pelvis[1] + back[1] * unit * 0.32 + unit * 0.2];
    const a1 = [neck[0] + back[0] * unit * 0.3 + spine[0] / len * unit * 0.2, neck[1] + back[1] * unit * 0.3 + spine[1] / len * unit * 0.2];
    parts.push(`<path class="gear-line" d="M${round(a0[0])} ${round(a0[1])}L${round(a1[0])} ${round(a1[1])}M${round(pelvis[0] - unit * 0.4)} ${round(pelvis[1] + unit * 0.25)}H${round(pelvis[0] + unit * 0.4)}M${round(pelvis[0])} ${round(pelvis[1] + unit * 0.25)}V${FLOOR}" stroke-width="${round(unit * 0.16)}"/>`);
    return parts.join('');
  }
  if (!lying && Math.abs(pelvis[1] - (p.knL[1] + p.knR[1]) / 2) < unit * 0.45 && ['machine', 'dumbbell', 'barbell', 'cable'].includes(gear)) {
    const top = pelvis[1] + unit * 0.25;
    parts.push(`<path class="gear-line" d="M${round(pelvis[0] - unit * 0.45)} ${round(top)}H${round(pelvis[0] + unit * 0.45)}M${round(pelvis[0])} ${round(top)}V${FLOOR}" stroke-width="${round(unit * 0.16)}"/>`);
  }
  return parts.join('');
}

// Joints take the colour of the segment they belong to.
const LINKED = { knee: 'thigh', elbow: 'fore' };

const reduceMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

/** The animated mannequin for an exercise (catalog or custom: uses its pose id, gear and muscles). */
export function figure(exercise, { size = 'card', label = '', still = false } = {}) {
  const id = exercise?.photo || 'squat';
  const data = Object.hasOwn(POSES, id) ? POSES[id] : POSES.squat;
  const frames = data.frames.map(joints);
  const unit = frames.map((p) => dist(p.neck, p.pelvis)).reduce((a, b) => a + b, 0) / frames.length || 40;
  const view = Math.abs(frames[0].shL[0] - frames[0].shR[0]) > 0.45 * unit ? 'front' : 'side';
  const gear = exercise?.gear || '';
  const per = frames.map((p) => shapes(p, data.near, unit, gear, view, data));
  const level = levels(exercise?.primary, exercise?.secondary);
  // Facing the viewer the back is hidden, so back muscles colour the whole torso instead.
  if (view === 'front') {
    level.chest = level.chest || level.back;
    level.belly = level.belly || level['back-hip'] || level.back;
  }
  const moving = !still && !reduceMotion();
  const body = per[0].map((shape, i) => {
    const { tag, base, anim } = attrsFor(shape, per.map((f) => f[i]), unit);
    const solid = shape.w == null && !shape.c;
    const cls = [shape.part, shape.depth, level[shape.part] || level[LINKED[shape.part]], solid ? 'solid' : ''].filter(Boolean).join(' ');
    const motion = moving ? anim.map(([name, values]) => animate(name, values)).join('') : '';
    return `<${tag} class="${cls}" ${base}>${motion}</${tag}>`;
  }).join('');
  const alt = label ? `${esc(label)}: схема движения` : 'Схема движения';
  return `<div class="ex-figure fig-${esc(size)}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${alt}">`
    + `${staticGear(frames[0], unit, gear, view, data)}<g class="fig">${body}</g></svg></div>`;
}

// Only figures on screen move: dozens of looping SVG animations would drain a phone.
const watcher = typeof IntersectionObserver === 'function'
  ? new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const svg = entry.target;
      if (entry.isIntersecting) svg.unpauseAnimations?.();
      else svg.pauseAnimations?.();
    }
  }, { rootMargin: '80px' })
  : null;

/** Start watching the figures inside `root`; call after every render that adds them. */
export function watchFigures(root = document) {
  if (!watcher) return;
  for (const svg of root.querySelectorAll('.ex-figure svg:not([data-watched])')) {
    // Not paused up front: if the observer never reports (some WebViews), figures still move.
    svg.dataset.watched = '1';
    watcher.observe(svg);
  }
}
