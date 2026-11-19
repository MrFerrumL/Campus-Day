// Workout mode: one exercise at a time, sets with last time's numbers as hints,
// a rest timer between sets and a summary at the end.
import { api, ask, closeSheet, haptic, on, openSheet, render, toast } from '../core.js';
import { figure, watchFigures } from '../figure.js';
import { icon } from '../icons.js';
import { esc } from '../util.js';
import { pickExercise } from './gym-picker.js';

let source = () => null;
let reload = async () => {};
let leave = () => {};
let index = 0;
let shownId = null;
let rest = null; // { until, total }
let ticker = null;
let busy = false;
// entry id -> { w0: '60', r0: '5', ... } typed into sets that are not saved yet
const typed = new Map();

/** gym.js hands over its data, reload and how to go back to the training page. */
export function connect(getData, reloadData, back) {
  source = getData;
  reload = reloadData;
  leave = back;
}

const active = () => source()?.active;
const findExercise = (id) => (source()?.exercises || []).find((e) => e.id === id);
const minutes = (from, to = Date.now()) => Math.max(0, Math.round((to - Date.parse(from)) / 60000));
const UNIT = { reps: 'повт.', seconds: 'сек', minutes: 'мин' };
const fmtSet = (s, unit) => `${s.weight != null && unit !== 'minutes' ? `${s.weight} кг × ` : ''}${s.reps}${unit === 'reps' ? '' : ' ' + UNIT[unit]}`;

function counts(w) {
  const sets = w.exercises.flatMap((e) => e.sets);
  return { done: sets.filter((s) => s.done).length, total: sets.length };
}

/** The card on the training page while a workout is open. */
export function activeCard() {
  const w = active();
  if (!w) return '';
  const { done, total } = counts(w);
  return `<section class="section card workout-card"><span class="badge">Тренировка идёт · ${minutes(w.started)} мин</span>
    <h2>${esc(w.name)}</h2><p class="meta">${done} из ${total} подходов · ${w.exercises.length} упражнений</p>
    <div class="progress"><i style="width:${total ? (done / total) * 100 : 0}%"></i></div>
    <button type="button" class="btn primary block" data-action="workout-open">${icon('right', 18)}Продолжить тренировку</button></section>`;
}

function chips(w) {
  return `<div class="chips scroll-chips workout-steps" role="tablist" aria-label="Упражнения тренировки">${w.exercises.map((e, i) => {
    const complete = e.sets.length && e.sets.every((s) => s.done);
    return `<button type="button" class="chip ${complete ? 'complete' : ''}" role="tab" data-action="workout-go" data-i="${i}" aria-selected="${i === index}" aria-pressed="${i === index}">${complete ? icon('check', 14) : ''}${i + 1}</button>`;
  }).join('')}</div>`;
}

function hint(entry, i) {
  const last = source()?.last?.[entry.exercise_id];
  const fromLast = last?.sets[Math.min(i, last.sets.length - 1)];
  const prev = entry.sets.slice(0, i).reverse().find((s) => s.done);
  return prev || fromLast || {};
}

function setRow(entry, s, i) {
  const h = hint(entry, i);
  const draft = typed.get(entry.id) || {};
  const shown = (key, saved) => esc(String(s.done ? saved ?? '' : draft[key] ?? saved ?? ''));
  const weight = entry.unit === 'minutes' ? '' : `<input type="number" inputmode="decimal" min="0" max="1000" step="0.5" name="w${i}" data-input="workout-type" value="${shown('w' + i, s.weight)}" placeholder="${h.weight ?? '—'}" aria-label="Вес, подход ${i + 1}" ${s.done ? 'disabled' : ''}>`;
  return `<div class="set-line ${s.done ? 'done' : ''}" data-row="${i}"><b>${i + 1}</b>${weight || '<span></span>'}
    <input type="number" inputmode="decimal" min="0" max="10000" step="any" name="r${i}" data-input="workout-type" value="${shown('r' + i, s.reps)}" placeholder="${h.reps ?? '—'}" aria-label="${UNIT[entry.unit]}, подход ${i + 1}" ${s.done ? 'disabled' : ''}>
    <button type="button" class="set-check" data-action="workout-set" data-i="${i}" aria-pressed="${s.done}" aria-label="${s.done ? 'Отменить подход' : 'Подход выполнен'} ${i + 1}">${icon('check', 20)}</button></div>`;
}

export function workoutView() {
  const w = active();
  if (!w) {
    return `<div class="workout-head"><button type="button" class="icon-btn" data-action="workout-back" aria-label="К тренировкам">${icon('left', 20)}</button></div>
      <div class="empty"><strong>Тренировки сейчас нет</strong>Она завершена или ещё не начата.</div>`;
  }
  // A new workout (or one reopened later) starts at its first unfinished exercise.
  if (w.id !== shownId) {
    shownId = w.id;
    index = Math.max(0, w.exercises.findIndex((e) => !e.sets.length || e.sets.some((s) => !s.done)));
  }
  index = Math.min(index, Math.max(0, w.exercises.length - 1));
  const { done, total } = counts(w);
  const head = `<div class="workout-head"><button type="button" class="icon-btn" data-action="workout-back" aria-label="К тренировкам">${icon('left', 20)}</button>
    <div class="grow"><strong>${esc(w.name)}</strong><span class="meta">${minutes(w.started)} мин · ${done} из ${total} подходов</span></div></div>
    <div class="progress"><i style="width:${total ? (done / total) * 100 : 0}%"></i></div>`;
  if (!w.exercises.length) {
    return `${head}<div class="empty section"><strong>Добавьте первое упражнение</strong>Выберите его из каталога.</div>${footer()}`;
  }
  const entry = w.exercises[index];
  const exercise = findExercise(entry.exercise_id) || { photo: entry.photo, name: entry.name };
  const last = source()?.last?.[entry.exercise_id];
  const unit = entry.unit || 'reps';
  const next = w.exercises[index + 1];
  return `${head}${chips(w)}
    <section class="section card workout-focus">
      ${figure(exercise, { size: 'big', label: entry.name })}
      <div class="row"><h2 class="grow">${esc(entry.name)}</h2>
        <button type="button" class="icon-btn small ghost" data-action="gym-exercise" data-id="${esc(entry.exercise_id)}" aria-label="Техника">${icon('book', 18)}</button></div>
      <p class="meta">${entry.sets.length} подх.${entry.target ? ' · ' + esc(entry.target) : ''}${entry.rest_seconds ? ` · отдых ${entry.rest_seconds} сек` : ''}</p>
      ${last ? `<p class="last-time">${icon('clock', 14)} В прошлый раз (${esc(last.day.slice(8, 10))}.${esc(last.day.slice(5, 7))}): ${last.sets.map((s) => esc(fmtSet(s, unit))).join(' · ')}</p>` : ''}
      <div class="set-head"><span>№</span><span>${unit === 'minutes' ? '' : 'кг'}</span><span>${UNIT[unit]}</span><span></span></div>
      <form class="sets" data-submit="workout-noop" data-entry="${esc(entry.id)}">${entry.sets.map((s, i) => setRow(entry, s, i)).join('')}</form>
      <div class="row wrap"><button type="button" class="btn small" data-action="workout-extra">${icon('plus', 16)}Подход</button>
        <span class="grow"></span>
        <button type="button" class="icon-btn small ghost" data-action="workout-move" data-step="-1" aria-label="Выше" ${index ? '' : 'disabled'}>${icon('left', 18)}</button>
        <button type="button" class="icon-btn small ghost" data-action="workout-move" data-step="1" aria-label="Ниже" ${next ? '' : 'disabled'}>${icon('right', 18)}</button>
        <button type="button" class="icon-btn small ghost" data-action="workout-remove" aria-label="Убрать из тренировки">${icon('trash', 18)}</button></div>
      <div class="row workout-nav">
        <button type="button" class="btn grow" data-action="workout-go" data-i="${index - 1}" ${index ? '' : 'disabled'}>${icon('left', 18)}Назад</button>
        <button type="button" class="btn primary grow" data-action="workout-go" data-i="${index + 1}" ${next ? '' : 'disabled'}>${next ? esc(next.name) : 'Последнее'}${icon('right', 18)}</button>
      </div>
    </section>${footer()}${restPanel()}`;
}

function footer() {
  return `<div class="row section"><button type="button" class="btn grow" data-action="workout-add">${icon('plus', 18)}Упражнение</button>
    <button type="button" class="btn primary grow" data-action="workout-finish">${icon('flag', 18)}Завершить</button></div>`;
}

function restPanel() {
  if (!rest) return '';
  return `<div class="rest-panel" role="timer" aria-live="off"><div class="rest-bar"><i id="rest-fill"></i></div>
    <div class="row"><span class="grow">Отдых <b id="rest-left">${clock(rest.until - Date.now())}</b></span>
    <button type="button" class="btn small" data-action="rest-add" data-s="-15">−15</button>
    <button type="button" class="btn small" data-action="rest-add" data-s="15">+15</button>
    <button type="button" class="btn small primary" data-action="rest-skip">Дальше</button></div></div>`;
}

const clock = (ms) => {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

function tick() {
  if (!rest) return;
  const left = rest.until - Date.now();
  const label = document.getElementById('rest-left');
  const fill = document.getElementById('rest-fill');
  if (label) label.textContent = clock(left);
  if (fill) fill.style.width = `${Math.max(0, Math.min(100, (left / rest.total) * 100))}%`;
  if (left <= 0) {
    const panel = document.querySelector('.rest-panel');
    stopRest();
    if (!panel) return; // the workout screen was left: finish quietly
    panel.remove();
    haptic('success');
    try { navigator.vibrate?.([200, 100, 200]); } catch { /* not supported */ }
    toast('Отдых окончен — следующий подход');
  }
}

function startRest(seconds) {
  if (!seconds) return;
  rest = { until: Date.now() + seconds * 1000, total: seconds * 1000 };
  clearInterval(ticker);
  ticker = setInterval(tick, 250);
}

function stopRest() {
  rest = null;
  clearInterval(ticker);
  ticker = null;
}

export function afterRender() {
  tick();
  watchFigures();
}

/* ---------- Actions ---------- */
function readSets(entry) {
  const draft = typed.get(entry.id) || {};
  const pick = (key, saved) => (key in draft ? (draft[key] === '' ? null : draft[key]) : saved ?? null);
  return entry.sets.map((s, i) => (s.done ? { ...s } : { weight: pick('w' + i, s.weight), reps: pick('r' + i, s.reps), done: false }));
}

on('input', 'workout-type', (input) => {
  const entry = input.closest('form.sets')?.dataset.entry;
  if (!entry) return;
  typed.set(entry, { ...(typed.get(entry) || {}), [input.name]: input.value });
});

async function saveSets(entry, sets) {
  const row = await api('workout-sets', { id: active().id, exercise: entry.id, sets });
  source().active = row;
  typed.delete(entry.id); // saved: the server copy now holds every typed value
  return row;
}

/** One request at a time: a double tap must not finish or remove twice. */
async function once(fn) {
  if (busy) return;
  busy = true;
  try { await fn(); } finally { busy = false; }
}

on('click', 'workout-open', () => { shownId = null; leave('workout'); });
on('click', 'workout-back', () => { stopRest(); leave('train'); });
on('click', 'workout-go', (b) => {
  const i = Number(b.dataset.i);
  if (!Number.isInteger(i) || i < 0 || i >= active().exercises.length) return;
  index = i;
  render();
});
on('submit', 'workout-noop', () => {});
on('click', 'workout-set', async (b) => {
  const entry = active().exercises[index];
  const i = Number(b.dataset.i);
  const sets = readSets(entry);
  const set = sets[i];
  if (set.done) {
    set.done = false;
  } else {
    // An empty field takes the grey hint: the same numbers as last time.
    const h = hint(entry, i);
    if (set.reps == null) set.reps = h.reps ?? null;
    if (set.weight == null && entry.unit !== 'minutes') set.weight = h.weight ?? null;
    if (set.reps == null) { toast('Запишите повторения или время'); return; }
    set.done = true;
  }
  b.disabled = true;
  try {
    const row = await saveSets(entry, sets);
    haptic('light');
    const at = row.exercises.findIndex((e) => e.id === entry.id);
    const fresh = row.exercises[at];
    if (!fresh) return;
    const allDone = fresh.sets.every((s) => s.done);
    const lastExercise = at === row.exercises.length - 1;
    if (set.done && !(allDone && lastExercise)) startRest(fresh.rest_seconds || 90);
    if (set.done && allDone && !lastExercise) toast('Упражнение готово — дальше: ' + row.exercises[at + 1].name);
  } finally {
    render();
  }
});
on('click', 'workout-extra', async () => {
  const entry = active().exercises[index];
  if (entry.sets.length >= 30) return;
  await saveSets(entry, [...readSets(entry), { weight: null, reps: null, done: false }]);
  render();
});
on('click', 'workout-move', (b) => once(async () => {
  const entry = active().exercises[index];
  const step = Number(b.dataset.step);
  source().active = await api('workout-move', { id: active().id, exercise: entry.id, step });
  index = Math.max(0, active().exercises.findIndex((e) => e.id === entry.id));
  render();
}));
on('click', 'workout-remove', () => once(async () => {
  const entry = active().exercises[index];
  if (!(await ask(`Убрать «${entry.name}» из этой тренировки?`))) return;
  source().active = await api('workout-remove', { id: active().id, exercise: entry.id });
  typed.delete(entry.id);
  index = Math.min(index, Math.max(0, active().exercises.length - 1)); // the next one takes its place
  render();
}));
on('click', 'workout-add', () => pickExercise('Добавить в тренировку', async (id) => {
  source().active = await api('workout-add', { id: active().id, exercise_id: id });
  index = active().exercises.length - 1;
  closeSheet();
  render();
  toast('Упражнение добавлено');
}));
on('click', 'rest-add', (b) => {
  if (!rest) return;
  rest.until += Number(b.dataset.s) * 1000;
  rest.total = Math.max(rest.total, rest.until - Date.now());
  tick();
});
on('click', 'rest-skip', () => { stopRest(); render(); });
on('click', 'workout-finish', () => once(async () => {
  const w = active();
  const { done } = counts(w);
  if (!(await ask(done ? 'Завершить тренировку и сохранить её в истории?' : 'Ни одного подхода не отмечено. Всё равно завершить?'))) return;
  await api('workout-finish', { id: w.id });
  stopRest();
  typed.clear();
  source().active = null; // even if the reload below fails, the finished workout is not shown as running
  haptic('success');
  leave('train');
  try { await reload(); } finally { summary(w); }
}));

function summary(w) {
  // New records come from the progress the server just recalculated.
  const records = (source()?.progress?.prs?.[w.id] || []).map((id) => {
    const r = source().progress.records[id];
    const e = w.exercises.find((x) => x.exercise_id === id);
    return r && e ? `<li class="pr">${icon('trophy', 16)}<span><b>${esc(e.name)}</b><span class="meta">${esc(fmtSet(r, e.unit || 'reps'))}</span></span></li>` : '';
  }).join('');
  const unitOf = (e) => e.unit || 'reps';
  const doneSets = w.exercises.flatMap((e) => e.sets.filter((s) => s.done).map((s) => ({ ...s, unit: unitOf(e) })));
  const volume = doneSets.filter((s) => s.unit === 'reps').reduce((v, s) => v + (Number(s.weight) || 0) * (Number(s.reps) || 0), 0);
  const rows = w.exercises.map((e) => {
    const sets = e.sets.filter((s) => s.done);
    return sets.length ? `<li><b>${esc(e.name)}</b><span class="meta">${sets.map((s) => esc(fmtSet(s, unitOf(e)))).join(' · ')}</span></li>` : '';
  }).join('');
  openSheet(`<div class="sheet-head"><h2>Тренировка завершена</h2><button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <div class="stats section"><div class="stat"><b>${minutes(w.started)}</b><span>минут</span></div>
      <div class="stat"><b>${doneSets.length}</b><span>подходов</span></div>
      <div class="stat"><b>${Math.round(volume).toLocaleString('ru-RU')}</b><span>кг объёма</span></div></div>
    ${records ? `<h3>Новые рекорды</h3><ul class="summary-list">${records}</ul>` : ''}
    ${rows ? `<ul class="summary-list">${rows}</ul>` : '<p class="meta">Подходы не отмечены.</p>'}
    <button type="button" class="btn primary block" data-action="close-sheet">Готово</button>`);
}
