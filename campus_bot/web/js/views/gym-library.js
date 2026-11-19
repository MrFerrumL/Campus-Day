// The exercise library of the gym tab: filters, the photo grid, the full exercise
// card and the form for your own exercises.
import { api, ask, closeSheet, haptic, on, openSheet, render, toast } from '../core.js';
import { icon } from '../icons.js';
import { empty } from '../parts.js';
import { esc } from '../util.js';
import { muscleMap } from '../fitness.js';
import { figure, watchFigures } from '../figure.js';

const KINDS = [['all', 'Все'], ['strength', 'Силовые'], ['cardio', 'Кардио'], ['stretch', 'Растяжка']];
const LEVELS = { beginner: 'Новичок', intermediate: 'Средний' };
const UNITS = [['reps', 'Повторения'], ['seconds', 'Секунды'], ['minutes', 'Минуты']];
const filters = { query: '', kind: 'all', group: 'all', gear: 'all' };
let source = () => null;
let reload = async () => {};
let afterSheet = () => watchFigures();

/** gym.js hands over its data getter, its reload and what to run after a sheet opens. */
export function connect(getData, reloadData, onSheet) {
  source = getData;
  reload = reloadData;
  afterSheet = onSheet;
}

const exercises = () => source()?.exercises || [];
const find = (id) => exercises().find((e) => e.id === id);
const muscleNames = () => source()?.muscles || {};

function matches(e) {
  const data = source();
  const text = `${e.name} ${e.muscles} ${e.equipment}`.toLowerCase();
  if (filters.query && !text.includes(filters.query.toLowerCase())) return false;
  if (filters.kind !== 'all' && (e.kind || 'strength') !== filters.kind) return false;
  // Your own exercises have free-text equipment, so the gear filter leaves them in the list.
  if (filters.gear !== 'all' && !e.custom && e.gear !== filters.gear) return false;
  if (filters.group === 'all') return true;
  const group = data.groups[filters.group]?.muscles || [];
  return (e.primary || []).some((m) => group.includes(m));
}

function chips(list, key, action) {
  return list.map(([id, name]) => `<button type="button" class="chip" data-action="${action}" data-value="${esc(id)}" aria-pressed="${filters[key] === id}">${esc(name)}</button>`).join('');
}

export function libraryView() {
  const data = source();
  const groups = [['all', 'Все мышцы'], ...Object.entries(data.groups).map(([id, g]) => [id, g.name])];
  const gear = [['all', 'Любое оборудование'], ...Object.entries(data.gear)];
  const list = exercises().filter(matches);
  return `<section class="section library">
    <div class="section-head"><h2>Упражнения <span class="count">${list.length}</span></h2>
      <button type="button" class="btn small" data-action="gym-custom-exercise">${icon('plus', 16)}Своё</button></div>
    <label class="field"><span class="sr-only">Поиск упражнений</span>
      <input type="search" data-input="gym-search" value="${esc(filters.query)}" placeholder="Жим, присед, гантели…"></label>
    <div class="chips scroll-chips" role="group" aria-label="Тип нагрузки">${chips(KINDS, 'kind', 'gym-kind')}</div>
    <div class="chips scroll-chips" role="group" aria-label="Группа мышц">${chips(groups, 'group', 'gym-group')}</div>
    <label class="field compact"><span class="sr-only">Оборудование</span><select data-change="gym-gear">
      ${gear.map(([id, name]) => `<option value="${esc(id)}" ${filters.gear === id ? 'selected' : ''}>${esc(name)}</option>`).join('')}</select></label>
    <div class="exercise-grid">${grid(list)}</div>
    <p class="muted small-text">Позы фигур построены по фото Free Exercise DB (общественное достояние). Нагрузку подбирайте под свой опыт; боль — повод остановиться.</p>
  </section>`;
}

const grid = (list) => list.map(card).join('') || empty('Ничего не нашлось', 'Измените поиск или фильтры.');

function card(e) {
  return `<button type="button" class="card exercise-card" data-action="gym-exercise" data-id="${esc(e.id)}">
    ${figure(e, { label: e.name })}<strong>${esc(e.name)}</strong><span class="meta">${esc(e.muscles || 'Своё упражнение')}</span></button>`;
}

/** Last finished sets of an exercise, newest workout first. */
function lastResult(id) {
  const workouts = (source()?.records?.workout || []).filter((w) => w.status === 'done');
  for (const w of workouts) {
    const entry = w.exercises.find((e) => e.exercise_id === id);
    const sets = entry?.sets.filter((s) => s.done) || [];
    if (sets.length) return { day: w.day, entry, sets };
  }
  return null;
}

function unitLabel(unit) {
  return unit === 'minutes' ? ' мин' : unit === 'seconds' ? ' сек' : '';
}

export function exerciseSheet(id) {
  const e = find(id);
  if (!e) return;
  const last = lastResult(e.id);
  const data = source();
  const badges = [e.equipment, LEVELS[e.level], KINDS.find(([k]) => k === e.kind)?.[1]].filter(Boolean);
  openSheet(`<div class="sheet-head"><h2>${esc(e.name)}</h2><button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    ${figure(e, { size: 'big', label: e.name })}
    <div class="badges">${badges.map((b) => `<span class="badge">${esc(b)}</span>`).join('')}</div>
    ${muscleMap(e.primary || [], e.secondary || [], muscleNames())}
    ${e.tips?.length ? `<h3>Техника</h3><ol class="exercise-steps">${e.tips.map((t) => `<li>${esc(t)}</li>`).join('')}</ol>` : ''}
    ${e.mistake ? `<div class="mistake">${icon('alert', 18)}<span><b>Частая ошибка.</b> ${esc(e.mistake)}</span></div>` : ''}
    ${last ? `<div class="card last-result"><span class="meta">В прошлый раз · ${esc(last.day)}</span><p>${last.sets.map((s) => (s.weight != null ? `${s.weight} кг × ` : '') + s.reps + unitLabel(last.entry.unit)).join(' · ')}</p></div>` : ''}
    ${data.progress?.history?.[e.id] ? `<button type="button" class="btn block" data-action="progress-exercise" data-id="${esc(e.id)}">${icon('trophy', 18)}Мой прогресс</button>` : ''}
    ${data.active ? `<button type="button" class="btn primary block" data-action="gym-add-this" data-id="${esc(e.id)}">${icon('plus', 18)}Добавить в текущую тренировку</button>` : ''}
    ${e.custom ? `<button type="button" class="btn block" data-action="gym-custom-exercise" data-id="${esc(e.id)}">${icon('edit', 18)}Изменить своё упражнение</button>` : ''}`);
  afterSheet();
}

function muscleChecks(name, chosen) {
  return `<div class="muscle-checks">${Object.entries(muscleNames()).map(([id, label]) => `<label class="check-chip"><input type="checkbox" name="${name}" value="${id}" ${chosen.includes(id) ? 'checked' : ''}><span>${esc(label)}</span></label>`).join('')}</div>`;
}

export function customSheet(id) {
  const e = find(id) || {};
  const catalog = exercises().filter((x) => !x.custom);
  const current = e.photo || 'squat';
  openSheet(`<div class="sheet-head"><h2>${e.id ? 'Своё упражнение' : 'Добавить упражнение'}</h2><button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <form class="form" data-submit="gym-exercise-save" data-id="${esc(e.id || '')}">
      <label class="field">Название<input name="name" value="${esc(e.name || '')}" required maxlength="100"></label>
      <label class="field">Как выглядит — похожее движение из каталога<select name="photo" data-change="gym-photo-pick">
        ${catalog.map((x) => `<option value="${esc(x.id)}" ${x.id === current ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label>
      <div id="custom-photo">${figure(find(current), { size: 'card' })}</div>
      <fieldset class="field"><legend>Какие мышцы работают</legend>${muscleChecks('primary', e.primary || [])}</fieldset>
      <fieldset class="field"><legend>Какие помогают</legend>${muscleChecks('secondary', e.secondary || [])}</fieldset>
      <label class="field">Оборудование<input name="equipment" value="${esc(e.equipment || '')}" maxlength="100" placeholder="Гантели, блок, свой вес…"></label>
      <div class="form-row">
        <label class="field">Тип<select name="kind">${KINDS.slice(1).map(([k, t]) => `<option value="${k}" ${k === (e.kind || 'strength') ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
        <label class="field">Что записывать<select name="unit">${UNITS.map(([k, t]) => `<option value="${k}" ${k === (e.unit || 'reps') ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      </div>
      <label class="field">Техника и заметки · по одной на строку<textarea name="tips" rows="4" maxlength="2000">${esc((e.tips || []).join('\n'))}</textarea></label>
      <button class="btn primary block">Сохранить упражнение</button>
      ${e.id ? `<button type="button" class="btn danger block" data-action="gym-remove-custom" data-id="${esc(e.id)}">Удалить упражнение</button>` : ''}
    </form>`);
  afterSheet();
}

function readCustom(form) {
  const values = new FormData(form);
  const body = Object.fromEntries(['name', 'photo', 'equipment', 'kind', 'unit'].map((k) => [k, values.get(k) || '']));
  body.primary = values.getAll('primary').slice(0, 4);
  body.secondary = values.getAll('secondary').filter((m) => !body.primary.includes(m)).slice(0, 6);
  body.tips = String(values.get('tips') || '').split('\n').map((t) => t.trim()).filter(Boolean).slice(0, 8);
  if (form.dataset.id) body.id = form.dataset.id;
  return body;
}

const refresh = () => { render(); afterSheet(); };
// Typing redraws only the grid, so the search field keeps focus and caret.
on('input', 'gym-search', (input) => {
  filters.query = input.value;
  const list = exercises().filter(matches);
  const box = document.querySelector('.library .exercise-grid');
  const count = document.querySelector('.library .count');
  if (box) box.innerHTML = grid(list);
  watchFigures(box || document);
  if (count) count.textContent = list.length;
});
on('click', 'gym-kind', (b) => { filters.kind = b.dataset.value; refresh(); });
on('click', 'gym-group', (b) => { filters.group = b.dataset.value; refresh(); });
on('change', 'gym-gear', (select) => { filters.gear = select.value; refresh(); });
on('click', 'gym-exercise', (b) => exerciseSheet(b.dataset.id));
on('click', 'gym-custom-exercise', (b) => customSheet(b.dataset.id));
on('change', 'gym-photo-pick', (select) => {
  const box = document.getElementById('custom-photo');
  if (box) box.innerHTML = figure(find(select.value), { size: 'card' });
});
on('submit', 'gym-exercise-save', async (form) => {
  const body = readCustom(form);
  if (!body.primary.length && !(await ask('Не выбраны рабочие мышцы — упражнение не попадёт в фильтры по мышцам. Сохранить так?'))) return;
  await api('wellness-exercise', body);
  haptic();
  closeSheet();
  await reload();
  toast('Упражнение сохранено');
});
on('click', 'gym-remove-custom', async (b) => {
  if (!(await ask('Удалить своё упражнение? История тренировок сохранится.'))) return;
  await api('wellness-delete', { id: b.dataset.id, kind: 'exercise' });
  closeSheet();
  await reload();
});
on('click', 'gym-add-this', async (b) => {
  await api('workout-add', { id: source().active.id, exercise_id: b.dataset.id });
  haptic();
  closeSheet();
  await reload();
  toast('Добавлено в тренировку');
});
