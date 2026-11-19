// Exercise helpers: which pose an exercise uses and the front/back muscle map.
import { esc } from './util.js';

// Drawn custom exercises from before the photo library pointed at a motion name.
const OLD_MOTIONS = { press: 'bench' };

export function photoId(item, exercises = []) {
  if (!item) return 'squat';
  if (item.photo) return item.photo;
  const known = exercises.find((e) => e.id === item.exercise_id);
  if (known?.photo) return known.photo;
  return OLD_MOTIONS[item.motion] || item.motion || 'squat';
}

/* ---------- Muscle map ---------- */
// Each muscle is a list of shapes on a 100×200 figure; "b" marks the back view.
// Shapes: e = ellipse [cx, cy, rx, ry, rotate], p = path.
const MAP = {
  shoulders: [['e', 29, 47, 8, 8], ['e', 71, 47, 8, 8], ['b', 'e', 29, 47, 8, 8], ['b', 'e', 71, 47, 8, 8]],
  chest: [['p', 'M50 42 C44 40 36 41 33 47 C33 56 39 61 49 60 Z'], ['p', 'M50 42 C56 40 64 41 67 47 C67 56 61 61 51 60 Z']],
  biceps: [['e', 24, 67, 5, 11, -8], ['e', 76, 67, 5, 11, 8]],
  forearms: [['e', 19, 93, 4.5, 12, -10], ['e', 81, 93, 4.5, 12, 10], ['b', 'e', 19, 93, 4.5, 12, -10], ['b', 'e', 81, 93, 4.5, 12, 10]],
  abs: [['p', 'M43 63 h14 v36 q-7 6 -14 0 Z']],
  obliques: [['e', 37, 82, 5, 12, 6], ['e', 63, 82, 5, 12, -6]],
  quads: [['e', 40, 131, 8, 21, 4], ['e', 60, 131, 8, 21, -4]],
  adductors: [['e', 46.5, 121, 3.5, 11, -6], ['e', 53.5, 121, 3.5, 11, 6]],
  calves: [['e', 40, 170, 5, 13, 2], ['e', 60, 170, 5, 13, -2], ['b', 'e', 40, 168, 6.5, 13, 2], ['b', 'e', 60, 168, 6.5, 13, -2]],
  traps: [['b', 'p', 'M50 30 L63 41 L56 56 L50 60 L44 56 L37 41 Z'], ['p', 'M41 37 L46 33 L46 38 Z'], ['p', 'M59 37 L54 33 L54 38 Z']],
  lats: [['b', 'p', 'M36 52 C33 62 35 76 44 86 L45 66 Z'], ['b', 'p', 'M64 52 C67 62 65 76 56 86 L55 66 Z']],
  midback: [['b', 'p', 'M45 58 L50 62 L55 58 L55 80 L50 84 L45 80 Z']],
  lowerback: [['b', 'p', 'M44 86 L50 89 L56 86 L56 100 L44 100 Z']],
  triceps: [['b', 'e', 24, 67, 5, 11, -8], ['b', 'e', 76, 67, 5, 11, 8]],
  glutes: [['b', 'e', 43, 110, 8, 9], ['b', 'e', 57, 110, 8, 9]],
  hamstrings: [['b', 'e', 41, 136, 7, 18, 3], ['b', 'e', 59, 136, 7, 18, -3]],
  abductors: [['b', 'e', 33, 112, 3.5, 8, 8], ['b', 'e', 67, 112, 3.5, 8, -8]],
};

// The figure underneath: head, torso, limbs.
const BODY = '<circle cx="50" cy="17" r="10"/><path d="M45 26h10v8h-10z"/>'
  + '<path d="M32 38 Q50 32 68 38 L66 100 Q50 108 34 100 Z"/>'
  + '<path d="M30 42 L18 82 L14 108 L20 109 L26 84 L35 52 Z"/><path d="M70 42 L82 82 L86 108 L80 109 L74 84 L65 52 Z"/>'
  + '<path d="M34 98 L31 150 L34 190 L45 190 L47 150 L50 108 Z"/><path d="M66 98 L69 150 L66 190 L55 190 L53 150 L50 108 Z"/>';

function shape(item, cls) {
  const [kind, ...args] = item;
  if (kind === 'p') return `<path class="${cls}" d="${args[0]}"/>`;
  const [cx, cy, rx, ry, rotate = 0] = args;
  return `<ellipse class="${cls}" cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}"${rotate ? ` transform="rotate(${rotate} ${cx} ${cy})"` : ''}/>`;
}

function figure(back, level) {
  const parts = Object.entries(MAP).flatMap(([muscle, shapes]) => shapes
    .filter((s) => (s[0] === 'b') === back)
    .map((s) => shape(back ? s.slice(1) : s, `m ${level(muscle)}`)));
  return `<g class="body">${BODY}</g>${parts.join('')}`;
}

export function muscleMap(primary = [], secondary = [], names = {}) {
  const level = (m) => (primary.includes(m) ? 'on' : secondary.includes(m) ? 'half' : '');
  const legend = [[primary, 'on', 'Работают'], [secondary, 'half', 'Помогают']]
    .filter(([list]) => list.length)
    .map(([list, cls, title]) => `<div class="legend"><i class="${cls}"></i><span><b>${title}:</b> ${list.map((m) => esc(names[m] || m)).join(', ')}</span></div>`)
    .join('');
  const cardio = primary.includes('cardio') ? '<p class="meta">Главная нагрузка — сердце и дыхание.</p>' : '';
  return `<div class="muscle-map"><svg viewBox="0 0 210 200" role="img" aria-label="Схема мышц: спереди и сзади">`
    + `<g>${figure(false, level)}</g><g transform="translate(110 0)">${figure(true, level)}</g>`
    + '<text x="50" y="199">спереди</text><text x="160" y="199">сзади</text></svg>'
    + `<div class="legends">${legend}${cardio}</div></div>`;
}
