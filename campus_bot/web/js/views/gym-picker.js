// A sheet for choosing an exercise: search, muscle group chips and figure cards.
// Used by the workout (add an exercise) and the program editor.
import { on, openSheet } from '../core.js';
import { figure, watchFigures } from '../figure.js';
import { icon } from '../icons.js';
import { esc } from '../util.js';

let source = () => null;
let chosen = null;
let back = null;
let query = '';
let group = 'all';

export function connectPicker(getData) {
  source = getData;
}

function list() {
  const data = source();
  const muscles = group === 'all' ? null : data.groups[group]?.muscles || [];
  const q = query.toLowerCase();
  return data.exercises.filter((e) => (!q || `${e.name} ${e.muscles} ${e.equipment}`.toLowerCase().includes(q))
    && (!muscles || (e.primary || []).some((m) => muscles.includes(m))));
}

const cards = () => list().map((e) => `<button type="button" class="pick-card" data-action="pick-exercise" data-id="${esc(e.id)}">
  ${figure(e, { size: 'thumb', still: true })}<span><strong>${esc(e.name)}</strong><span class="meta">${esc(e.muscles || e.equipment || '')}</span></span></button>`).join('')
  || '<p class="meta">Ничего не нашлось.</p>';

/** Open the picker; `onPick(id)` runs with the chosen exercise id, `onBack` returns to the previous sheet. */
export function pickExercise(title, onPick, onBack = null) {
  chosen = onPick;
  back = onBack;
  const groups = [['all', 'Все'], ...Object.entries(source().groups).map(([id, g]) => [id, g.name])];
  const close = back
    ? `<button type="button" class="icon-btn" data-action="pick-back" aria-label="Назад">${icon('left', 20)}</button>`
    : `<button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button>`;
  openSheet(`<div class="sheet-head"><h2>${esc(title)}</h2>${close}</div>
    <label class="field"><span class="sr-only">Поиск</span><input type="search" data-input="pick-search" value="${esc(query)}" placeholder="Жим, тяга, гантели…"></label>
    <div class="chips scroll-chips pick-groups">${groups.map(([id, name]) => `<button type="button" class="chip" data-action="pick-group" data-value="${esc(id)}" aria-pressed="${group === id}">${esc(name)}</button>`).join('')}</div>
    <div class="pick-list">${cards()}</div>`);
  watchFigures();
}

function refreshList() {
  const box = document.querySelector('.pick-list');
  if (box) box.innerHTML = cards();
}

on('click', 'pick-back', () => back?.());
on('input', 'pick-search', (input) => { query = input.value; refreshList(); });
on('click', 'pick-group', (b) => {
  group = b.dataset.value;
  document.querySelectorAll('.pick-groups .chip').forEach((c) => c.setAttribute('aria-pressed', String(c.dataset.value === group)));
  refreshList();
});
on('click', 'pick-exercise', async (b) => {
  const fn = chosen;
  if (!fn) return;
  b.disabled = true;
  try { await fn(b.dataset.id); } finally { b.disabled = false; }
});
