// Program editor: training days with exercises shown as figures, sets / reps / rest
// per exercise, reordering, and exercises added through the picker.
import { api, ask, closeSheet, haptic, on, openSheet, toast } from '../core.js';
import { figure, watchFigures } from '../figure.js';
import { icon } from '../icons.js';
import { $, esc } from '../util.js';
import { pickExercise } from './gym-picker.js';

let source = () => null;
let reload = async () => {};
let draft = null;
let saving = false;
const MAX_DAYS = 10;
const MAX_ENTRIES = 30;

export function connectPrograms(getData, reloadData) {
  source = getData;
  reload = reloadData;
}

const find = (id) => (source()?.exercises || []).find((e) => e.id === id);
const newEntry = (id) => ({ exercise_id: id, sets: 3, reps: '8–12', rest_seconds: 90, note: '' });
const field = (label, name, value, extra = '') => `<label class="field">${label}<input name="${name}" value="${esc(value ?? '')}" ${extra}></label>`;

function entryRow(e, d, j, count) {
  const x = find(e.exercise_id) || { name: e.exercise_id };
  const unit = x.unit === 'minutes' ? 'мин' : x.unit === 'seconds' ? 'сек' : 'повт.';
  return `<div class="pg-entry">
    <div class="pg-entry-head">${figure(x, { size: 'thumb', still: true })}<strong class="grow">${esc(x.name)}</strong>
      <button type="button" class="icon-btn small ghost" data-action="pg-move" data-day="${d}" data-entry="${j}" data-step="-1" aria-label="Выше" ${j ? '' : 'disabled'}>${icon('up', 16)}</button>
      <button type="button" class="icon-btn small ghost" data-action="pg-move" data-day="${d}" data-entry="${j}" data-step="1" aria-label="Ниже" ${j < count - 1 ? '' : 'disabled'}>${icon('down', 16)}</button>
      <button type="button" class="icon-btn small ghost" data-action="pg-remove" data-day="${d}" data-entry="${j}" aria-label="Убрать «${esc(x.name)}»">${icon('x', 16)}</button></div>
    <div class="pg-numbers">
      <label>Подходы<input name="sets-${d}-${j}" type="number" inputmode="numeric" min="1" max="20" step="1" value="${e.sets}" required></label>
      <label>${unit}<input name="reps-${d}-${j}" value="${esc(e.reps)}" maxlength="60" required></label>
      <label>Отдых, сек<input name="rest-${d}-${j}" type="number" inputmode="numeric" min="0" max="900" step="5" value="${e.rest_seconds}"></label>
    </div></div>`;
}

function editor() {
  openSheet(`<div class="sheet-head"><h2>${draft.id ? 'Моя программа' : 'Новая программа'}</h2><button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <form class="form" data-submit="pg-save" id="program-form">
      ${field('Название', 'name', draft.name, 'required maxlength="100"')}
      ${field('Заметка', 'note', draft.note, 'maxlength="1000"')}
      ${draft.days.map((d, i) => `<fieldset class="program-editor-day"><legend>День ${i + 1}</legend>
        ${field('Название дня', 'day-' + i, d.name, 'required maxlength="100"')}
        ${d.exercises.map((e, j) => entryRow(e, i, j, d.exercises.length)).join('') || '<p class="meta">Пока пусто — добавьте упражнения.</p>'}
        <div class="row"><button type="button" class="btn small" data-action="pg-add" data-day="${i}">${icon('plus', 16)}Упражнение</button>
          <span class="grow"></span>${draft.days.length > 1 ? `<button type="button" class="link-btn" data-action="pg-day-remove" data-day="${i}">Удалить день</button>` : ''}</div>
      </fieldset>`).join('')}
      <button type="button" class="btn" data-action="pg-day-add" ${draft.days.length >= MAX_DAYS ? 'disabled' : ''}>${icon('plus', 16)}Тренировочный день</button>
      <button class="btn primary block">Сохранить программу</button>
      ${draft.id ? '<button type="button" class="btn danger block" data-action="pg-delete">Удалить программу</button>' : ''}
    </form>`);
  watchFigures();
}

/** Keep what was typed before the editor redraws. */
function readForm() {
  const form = $('#program-form');
  if (!form) return;
  const v = (name) => form.elements.namedItem(name)?.value ?? '';
  draft.name = v('name');
  draft.note = v('note');
  draft.days.forEach((d, i) => {
    d.name = v('day-' + i);
    d.exercises = d.exercises.map((e, j) => ({
      ...e, sets: Number(v(`sets-${i}-${j}`)) || 1, reps: v(`reps-${i}-${j}`) || e.reps, rest_seconds: Number(v(`rest-${i}-${j}`)) || 0,
    }));
  });
}

const dayOf = (b) => draft.days[Number(b.dataset.day)];

on('click', 'gym-new-program', () => {
  draft = { name: 'Моя программа', note: '', days: [{ id: 'day-1', name: 'Тренировка 1', exercises: [] }] };
  editor();
});
on('click', 'gym-edit-program', (b) => {
  const program = source().programs.find((p) => p.id === b.dataset.id);
  if (!program) return;
  draft = structuredClone(program);
  editor();
});
on('click', 'pg-add', (b) => {
  readForm();
  const day = dayOf(b);
  if (day.exercises.length >= MAX_ENTRIES) { toast('До 30 упражнений в дне'); return; }
  pickExercise('Упражнение в программу', (id) => { day.exercises.push(newEntry(id)); editor(); }, editor);
});
on('click', 'pg-move', (b) => {
  readForm();
  const list = dayOf(b).exercises;
  const i = Number(b.dataset.entry);
  const j = i + Number(b.dataset.step);
  if (j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
  editor();
});
on('click', 'pg-remove', (b) => {
  readForm();
  dayOf(b).exercises.splice(Number(b.dataset.entry), 1);
  editor();
});
on('click', 'pg-day-add', () => {
  readForm();
  if (draft.days.length >= MAX_DAYS) return;
  draft.days.push({ id: crypto.randomUUID().slice(0, 8), name: `Тренировка ${draft.days.length + 1}`, exercises: [] });
  editor();
});
on('click', 'pg-day-remove', async (b) => {
  readForm();
  if (dayOf(b).exercises.length && !(await ask('Удалить этот день вместе с упражнениями?'))) return;
  draft.days.splice(Number(b.dataset.day), 1);
  editor();
});
on('submit', 'pg-save', async () => {
  readForm();
  if (draft.days.some((d) => !d.exercises.length)) { toast('В каждом дне должно быть хотя бы одно упражнение'); return; }
  if (saving) return; // a double tap must not create the program twice
  saving = true;
  try {
    const saved = await api('wellness-program', draft);
    draft.id = saved.id;
  } finally {
    saving = false;
  }
  haptic();
  closeSheet();
  await reload();
  toast('Программа сохранена');
});
on('click', 'pg-delete', async () => {
  if (!(await ask('Удалить программу? Завершённые тренировки останутся в журнале.'))) return;
  await api('wellness-delete', { id: draft.id, kind: 'program' });
  closeSheet();
  await reload();
});
