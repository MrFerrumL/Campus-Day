// Editors in the bottom sheet. The request bodies are the same the server has
// always accepted (miniapp.py App.mutate); only the presentation is new.
import { api, ask, closeSheet, haptic, load, on, openSheet, state, toast } from './core.js';
import { icon } from './icons.js';
import { WEEKDAYS, esc, iso, parseDay } from './util.js';

let editing = null;
const NOUN = { task: 'задачу', event: 'план', rule: 'занятие', override: 'занятие', stage: 'этап' };
const CYCLES = [['once', 'Один раз'], ['all', 'Каждую неделю'], ['daily', 'Каждый день'], ['weekdays', 'По будням'],
  ['a', 'По неделям A'], ['b', 'По неделям B']];
const TASK_REPEATS = [['once', 'Не повторять'], ['daily', 'Каждый день'], ['weekdays', 'По будням'], ['weekly', 'Каждую неделю']];
const STAGE_KINDS = [['task', 'Дедлайн — сдать к сроку'], ['event', 'Событие со временем'], ['allday', 'Событие на весь день']];
const options = (pairs, value) => pairs.map(([k, v]) => `<option value="${esc(k)}" ${k === value ? 'selected' : ''}>${esc(v)}</option>`).join('');
const hackName = (id) => (state.data?.hackathons || []).find((h) => h.id === id)?.title || 'Хакатон';
export const stageById = (id) => (state.data?.hackathons || []).flatMap((h) => h.stages).find((s) => s.id === +id);

function defaults(type, item) {
  const v = {
    title: item?.title || '',
    date: item?.date || item?.start?.slice(0, 10) || item?.due?.slice(0, 10) || iso(state.selected),
    time: item?.all_day ? '09:00' : item?.start?.slice(11, 16) || item?.due?.slice(11, 16) || item?.time || '18:00',
    duration: item?.all_day ? 120 : item?.duration_minutes || (item?.end ? Math.round((Date.parse(item.end) - Date.parse(item.start)) / 60000) : 120),
    allDay: type === 'task' && !!item?.all_day, priority: !!item?.priority, note: item?.note || '',
    cycle: item?.cycle || 'once', startDate: item?.start_date || (item ? '' : iso(state.selected)), endDate: item?.end_date || '',
    weekdays: item?.weekdays || [(state.selected.getDay() + 6) % 7], kind: 'task', days: 1, minDuration: 5,
  };
  if (type === 'stage') {
    v.kind = item ? (item.all_day ? 'allday' : item.kind) : 'task';
    v.time = item && !item.all_day ? item.start.slice(11, 16) : '23:59';
    v.duration = item?.kind === 'event' && !item.all_day ? item.duration : 60;
    v.days = item?.all_day ? Math.round(item.duration / 1440) : 1;
  }
  if (type === 'override' && item?.start === item?.end) v.minDuration = 0;
  return v;
}

function hint(type, item, v) {
  if (type === 'stage') return `Этап «${hackName(editing.project)}»: дедлайн попадёт в задачи, событие — в календарь.`;
  if (type === 'override') return v.minDuration === 0
    ? 'Известно только начало. Длительность 0 сохраняет неизвестное окончание.'
    : 'Изменение только на эту дату, остальные недели не меняются.';
  if (type === 'rule') return 'Выберите повторение и период. Пустая дата окончания — без ограничения.';
  return 'Сохранится в календаре и сразу будет видно в боте.';
}

function deleteLabel(type, item) {
  if (type === 'stage') return 'Удалить этап';
  if (type === 'task' || type === 'event') return 'Удалить';
  if (type === 'rule') return item?.cycle === 'once' ? 'Удалить разовое занятие' : 'Удалить все повторения';
  return item?.cancelled ? 'Вернуть занятие' : 'Отменить только эту дату';
}

export function openEditor(type, item = null, project = null) {
  if (!item && type === 'override') return;
  editing = { type, item, project: project || item?.project };
  const v = defaults(type, item);
  const days = WEEKDAYS.map((d, i) => `<label><input type="checkbox" name="weekday" value="${i}" ${v.weekdays.includes(i) ? 'checked' : ''}><span>${d}</span></label>`).join('');
  openSheet(`
    <div class="sheet-head"><h2>${item ? 'Изменить' : 'Добавить ' + NOUN[type]}</h2>
      <button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <p class="sheet-hint" id="edit-hint">${esc(hint(type, item, v))}</p>
    <form class="form" id="edit-form" data-submit="save-editor" data-change="layout-editor" novalidate>
      <label class="field">Название<input name="title" maxlength="300" required value="${esc(v.title)}" placeholder="Например, подготовка к зачёту" ${item ? '' : 'autofocus'}></label>
      <label class="field" data-show="stage">Тип этапа<select name="kind">${options(STAGE_KINDS, v.kind)}</select></label>
      <label class="field" data-show="rule">Повторять<select name="cycle">${options(CYCLES, v.cycle)}</select></label>
      <fieldset class="weekday-picker" data-show="weekdays"><legend>Дни недели</legend>${days}</fieldset>
      <div class="form-row" data-show="limits">
        <label class="field">Начиная с<input name="start_date" type="date" value="${esc(v.startDate)}"></label>
        <label class="field">До даты<input name="end_date" type="date" value="${esc(v.endDate)}"></label>
      </div>
      <label class="field" data-show="task">Повторять<select name="recurrence">${options(TASK_REPEATS, item?.recurrence || 'once')}</select></label>
      <label class="switch" data-show="task">Без точного времени<input type="checkbox" name="all_day" ${v.allDay ? 'checked' : ''}></label>
      <label class="switch" data-show="task">Важная задача<input type="checkbox" name="priority" ${v.priority ? 'checked' : ''}></label>
      <div class="form-row">
        <label class="field" data-show="date">Дата<input name="date" type="date" value="${esc(v.date)}" ${type === 'override' ? 'disabled' : ''}></label>
        <label class="field" data-show="time">Время<input name="time" type="time" value="${esc(v.time)}"></label>
      </div>
      <label class="field" data-show="duration">Длительность, минут<input name="duration" type="number" min="${v.minDuration}" max="1440" value="${esc(v.duration)}"></label>
      <div class="presets" data-show="duration">${[30, 60, 90, 120].map((m) => `<button type="button" class="chip" data-action="preset-duration" data-minutes="${m}">${m < 60 ? m + ' мин' : m / 60 + ' ч'}</button>`).join('')}</div>
      <label class="field" data-show="days">Сколько дней<input name="days" type="number" min="1" max="14" value="${esc(v.days)}"></label>
      <label class="field" data-show="note">Заметка<input name="note" maxlength="500" value="${esc(v.note)}" placeholder="Аудитория, ссылка или что взять с собой"></label>
      <button class="btn primary block" id="edit-save">Сохранить</button>
      ${item ? `<button type="button" class="btn danger block" data-action="delete-editor">${icon('trash', 18)}${esc(deleteLabel(type, item))}</button>` : ''}
      ${type === 'override' ? '<button type="button" class="btn block" data-action="reset-editor">Вернуть исходное расписание</button>' : ''}
    </form>`, { onClose: () => { editing = null; } });
  layout();
}

function layout() {
  const form = document.getElementById('edit-form');
  if (!form || !editing) return;
  const { type } = editing, stage = type === 'stage', rule = type === 'rule';
  const kind = form.kind.value, cycle = form.cycle.value, once = rule && cycle === 'once';
  const dayOnly = type === 'task' && form.all_day.checked, allday = stage && kind === 'allday';
  const show = {
    stage, rule, task: type === 'task', weekdays: rule && ['all', 'a', 'b'].includes(cycle), limits: rule && !once,
    date: !rule || once, time: !(dayOnly || allday), duration: !(type === 'task' || (stage && kind !== 'event')),
    days: allday, note: type !== 'override',
  };
  form.querySelectorAll('[data-show]').forEach((el) => { el.hidden = !show[el.dataset.show]; });
  form.duration.disabled = !show.duration;
  if (rule) document.getElementById('edit-hint').textContent = once
    ? 'Занятие появится только в выбранную дату.' : 'Выберите повторение и период. Пустая дата окончания — без ограничения.';
}
on('change', 'layout-editor', () => layout());
on('click', 'preset-duration', (button) => { document.getElementById('edit-form').duration.value = button.dataset.minutes; });

on('submit', 'save-editor', async (form) => {
  const { type, item } = editing;
  if (!form.title.value.trim()) { toast('Введите название'); form.title.focus(); return; }
  const needsDate = !form.date.closest('[data-show]').hidden && !form.date.disabled;
  const needsTime = !form.time.closest('[data-show]').hidden;
  if (needsDate && !form.date.value) { toast('Укажите дату'); return; }
  if (needsTime && !form.time.value) { toast('Укажите время'); return; }
  if (!form.duration.disabled && !form.duration.closest('[data-show]').hidden) {
    const minutes = Number(form.duration.value);
    if (!(minutes >= Number(form.duration.min) && minutes <= 1440)) { toast(`Длительность: ${form.duration.min}–1440 минут`); return; }
  }
  const time = form.time.value || '00:00';
  const body = { title: form.title.value, start: `${form.date.value}T${time}:00` };
  if (type === 'rule') {
    Object.assign(body, { id: item?.id, time, duration_minutes: +form.duration.value, cycle: form.cycle.value,
      date: form.date.value, start_date: form.start_date.value, end_date: form.end_date.value, note: form.note.value,
      weekdays: [...form.querySelectorAll('[name=weekday]:checked')].map((x) => +x.value) });
  } else if (type === 'override') {
    const end = new Date(Date.parse(body.start + 'Z') + Number(form.duration.value) * 60000).toISOString().slice(0, 19);
    Object.assign(body, { key: item.key, end, cancelled: false });
  } else if (type === 'stage') {
    Object.assign(body, { id: item?.id, project: editing.project, kind: form.kind.value, date: form.date.value,
      days: +form.days.value, duration: +form.duration.value, note: form.note.value,
      start: `${form.date.value}T${form.kind.value === 'allday' ? '00:00' : time}:00` });
  } else {
    Object.assign(body, { id: item?.id, duration: +form.duration.value || 0, note: form.note.value });
    if (type === 'task') Object.assign(body, { all_day: form.all_day.checked, priority: +form.priority.checked, recurrence: form.recurrence.value,
      start: `${form.date.value}T${form.all_day.checked ? '23:59' : time}:00` });
  }
  const button = document.getElementById('edit-save');
  button.disabled = true;
  try {
    await api(type, body);
    haptic('success');
    closeSheet();
    if (type === 'rule' && body.cycle === 'once') { state.selected = parseDay(body.date); state.tab = 'calendar'; state.mode = 'day'; }
    toast(type === 'rule' && body.cycle === 'once' ? 'Разовое занятие сохранено' : 'Сохранено');
    await load();
  } finally { button.disabled = false; }
});

on('click', 'delete-editor', async () => {
  const { type, item } = editing;
  const question = type === 'rule' ? 'Удалить это правило для всех недель?' : type === 'task' ? 'Удалить задачу?'
    : type === 'stage' ? 'Удалить этап?' : item.cancelled ? 'Вернуть занятие?' : 'Отменить занятие на эту дату?';
  if (!await ask(question)) return;
  if (type === 'override') await api('override', { key: item.key, title: item.title, start: item.start, end: item.end, cancelled: !item.cancelled });
  else await api(type === 'rule' ? 'delete-rule' : type === 'stage' ? 'delete-stage' : 'delete-task', { id: item.id });
  closeSheet();
  toast('Готово');
  await load();
});
on('click', 'reset-editor', async () => {
  await api('reset-override', { key: editing.item.key });
  closeSheet();
  toast('Исходное расписание возвращено');
  await load();
});

/* ---------- Hackathon card editor ---------- */
let hackId = '';
export function openHack(h = null) {
  if (!state.data) return;
  hackId = h?.id || '';
  const pairs = (o) => Object.entries(o || {});
  openSheet(`
    <div class="sheet-head"><h2>${h ? 'Изменить хакатон' : 'Новый хакатон'}</h2>
      <button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <p class="sheet-hint">Этапы добавляются в карточке после сохранения.</p>
    <form class="form" data-submit="save-hack">
      <label class="field">Название<input name="title" maxlength="300" required value="${esc(h?.title || '')}" placeholder="Например, Hack&amp;Change 2026" ${h ? '' : 'autofocus'}></label>
      <div class="form-row">
        <label class="field">Тип<select name="kind">${options(pairs(state.data.kinds), h?.kind || 'hackathon')}</select></label>
        <label class="field">Статус<select name="status">${options(pairs(state.data.statuses), h?.status || 'registration')}</select></label>
      </div>
      <label class="field">Организатор<input name="organizer" maxlength="200" value="${esc(h?.organizer || '')}" placeholder="Компания или площадка"></label>
      <label class="field">Моя роль<input name="role" maxlength="60" value="${esc(h?.role || '')}" placeholder="Например, капитан"></label>
      <label class="field">Описание<textarea name="summary" maxlength="1000" rows="3">${esc(h?.summary || '')}</textarea></label>
      <label class="field">Призы<input name="prize" maxlength="300" value="${esc(h?.prize || '')}"></label>
      <label class="field">Ссылки — по одной на строку<textarea name="links" rows="3" placeholder="Кабинет | https://…">${esc((h?.links || []).map((l) => `${l.title} | ${l.url}`).join('\n'))}</textarea></label>
      <button class="btn primary block">Сохранить</button>
      ${h ? `<button type="button" class="btn danger block" data-action="delete-hack">${icon('trash', 18)}Удалить хакатон</button>` : ''}
    </form>`);
}
on('submit', 'save-hack', async (form) => {
  const button = form.querySelector('.btn.primary');
  if (button.disabled) return;
  button.disabled = true;
  try {
  const links = form.links.value.split('\n').map((x) => x.trim()).filter(Boolean).map((line) => {
    const match = line.match(/https?:\/\/\S+/), url = match ? match[0] : line;
    return { url, title: line.replace(url, '').replace(/\|/g, '').trim() || 'Ссылка' };
  });
  await api('project', { id: hackId || undefined, title: form.title.value, kind: form.kind.value, status: form.status.value,
    organizer: form.organizer.value, role: form.role.value, summary: form.summary.value, prize: form.prize.value, links });
  } finally { button.disabled = false; }
  closeSheet();
  toast('Сохранено');
  await load();
});
on('click', 'delete-hack', async () => {
  if (!await ask('Удалить хакатон и все его этапы?')) return;
  await api('delete-project', { id: hackId });
  closeSheet();
  await load();
});

/* ---------- "+" button: what to add ---------- */
export function openAddChooser(kinds = ['task', 'event', 'rule']) {
  const items = {
    task: ['src-plan', 'tasks', 'Задача', 'Дедлайн с напоминаниями'],
    event: ['src-plan', 'clock', 'План со временем', 'Блок в календаре, например подготовка'],
    rule: ['src-personal', 'book', 'Занятие', 'Разовое или повторяющееся'],
    hack: ['src-hackathon', 'trophy', 'Хакатон', 'Этапы попадут в календарь'],
  };
  openSheet(`
    <div class="sheet-head"><h2>Добавить</h2>
      <button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <div class="choice-list">${kinds.map((k) => {
      const [cls, ic, title, text] = items[k];
      return `<button type="button" class="choice ${cls}" data-action="add-kind" data-kind="${k}"><span class="ic">${icon(ic, 22)}</span><span><strong>${title}</strong><small>${text}</small></span></button>`;
    }).join('')}</div>`);
}
on('click', 'add-kind', (button) => (button.dataset.kind === 'hack' ? openHack() : openEditor(button.dataset.kind)));
