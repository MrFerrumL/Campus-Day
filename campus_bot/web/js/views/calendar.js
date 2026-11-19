// «Календарь»: day, week and month with source filters and university attendance.
import { api, closeSheet, load, on, openSheet, rangeFor, render, state, toast } from '../core.js';
import { icon } from '../icons.js';
import { dayTitle, empty, eventCard, skeleton } from '../parts.js';
import { WEEKDAYS, conflicts, count, esc, eventsOn, fmt, iso, nowIso, parseDay, plus, today, todayIso } from '../util.js';

const FILTERS = [['all', 'Все'], ['university', 'Вуз'], ['personal', 'Занятия'], ['plan', 'Планы'], ['hackathon', 'Хакатоны']];
const MODES = [['day', 'День'], ['week', 'Неделя'], ['month', 'Месяц']];

function title() {
  const [a, b] = rangeFor('calendar');
  if (state.mode === 'month') return fmt(state.selected, { month: 'long', year: 'numeric' });
  if (state.mode === 'week') return `${fmt(a, { day: 'numeric', month: 'short' })} — ${fmt(b, { day: 'numeric', month: 'short' })}`;
  return fmt(state.selected, { weekday: 'short', day: 'numeric', month: 'long' });
}

function dots(events, day) {
  const sources = [...new Set(eventsOn(events, day).filter((e) => !e.cancelled).map((e) => e.source))];
  return `<span class="dots" aria-hidden="true">${sources.map((s) => `<i class="src-${esc(s)}"></i>`).join('')}</span>`;
}

function grid(events) {
  const [a, b] = rangeFor('calendar'), selected = iso(state.selected), now = todayIso();
  let cells = '';
  for (let d = a; d <= b; d = plus(d, 1)) {
    const key = iso(d), out = state.mode === 'month' && d.getMonth() !== state.selected.getMonth();
    const n = eventsOn(events, key).filter((e) => !e.cancelled).length;
    cells += `<button type="button" class="day-pill ${key === now ? 'today' : ''} ${out ? 'out' : ''}" data-action="pick-day" data-day="${key}"
      aria-pressed="${key === selected}" aria-label="${esc(fmt(d, { weekday: 'long', day: 'numeric', month: 'long' }))}, ${esc(count(n, 'событие', 'события', 'событий'))}">
      ${state.mode === 'month' ? '' : WEEKDAYS[(d.getDay() + 6) % 7]}<strong>${d.getDate()}</strong>${dots(events, key)}</button>`;
  }
  if (state.mode === 'month') return `<div class="month-grid">${WEEKDAYS.map((d) => `<div class="dow">${d}</div>`).join('')}${cells}</div>`;
  return `<div class="week-strip">${cells}</div>`;
}

function attendance(events) {
  const [a, b] = rangeFor('calendar'), now = todayIso();
  let from = iso(a), to = iso(b);
  if (state.mode === 'day') from = to = iso(state.selected);
  if (state.mode === 'month') {
    from = iso(new Date(state.selected.getFullYear(), state.selected.getMonth(), 1, 12));
    to = iso(new Date(state.selected.getFullYear(), state.selected.getMonth() + 1, 0, 12));
  }
  const rows = events.filter((e) => e.source === 'university' && !e.cancelled && e.start.slice(0, 10) >= from && e.start.slice(0, 10) <= to);
  if (!rows.length) return '';
  const present = rows.filter((e) => e.attendance === 'present').length, absent = rows.filter((e) => e.attendance === 'absent').length;
  const unmarked = rows.filter((e) => (e.attendance || 'pending') === 'pending' && e.start.slice(0, 10) <= now).length;
  const ahead = rows.length - present - absent - unmarked, marked = present + absent;
  return `<div class="card section" aria-label="Посещение пар">
    <div class="section-head"><h2>Посещение пар</h2><span class="meta">${marked ? `${Math.round(present / marked * 100)}% по отмеченным` : 'отметьте на карточке пары'}</span></div>
    <div class="metrics">
      <div class="metric"><b>${present}</b><span>был</span></div>
      <div class="metric"><b>${absent}</b><span>не был</span></div>
      <div class="metric"><b>${unmarked}</b><span>без отметки</span></div>
      <div class="metric"><b>${ahead}</b><span>впереди</span></div>
    </div></div>`;
}

function list(events) {
  const now = nowIso(), visible = (rows) => rows.filter((e) => state.filter === 'all' || e.source === state.filter);
  const warn = (rows) => conflicts(rows).length ? `<div class="notice">${icon('alert', 18)}<span>Есть пересечения по времени. Нажмите карандаш, чтобы сдвинуть занятие.</span></div>` : '';
  if (state.mode !== 'week') {
    const day = iso(state.selected), rows = eventsOn(events, day);
    return `<div class="day-title">${esc(dayTitle(day))}<span>${esc(count(rows.filter((e) => !e.cancelled).length, 'событие', 'события', 'событий'))}</span></div>
      ${warn(rows)}<div class="timeline">${visible(rows).map((e) => eventCard(e, { now })).join('') || empty('Свободно', 'На этот день ничего нет.')}</div>`;
  }
  const [a, b] = rangeFor('calendar');
  let html = '';
  for (let d = a; d <= b; d = plus(d, 1)) {
    const day = iso(d), rows = eventsOn(events, day), shown = visible(rows);
    html += `<div class="day-title">${esc(dayTitle(day))}<span>${shown.length ? esc(count(shown.length, 'событие', 'события', 'событий')) : 'свободно'}</span></div>
      ${shown.length ? warn(rows) + `<div class="timeline">${shown.map((e) => eventCard(e, { now })).join('')}</div>` : ''}`;
  }
  return html;
}

export function view() {
  const events = state.data?.events || [];
  return `
    <div class="segmented" role="group" aria-label="Период">${MODES.map(([k, v]) => `<button type="button" data-action="calendar-mode" data-mode="${k}" aria-pressed="${state.mode === k}">${v}</button>`).join('')}</div>
    <div class="datebar">
      <button type="button" class="icon-btn" data-action="calendar-step" data-step="-1" aria-label="Назад">${icon('left', 20)}</button>
      <label class="title">${esc(title())}<input type="date" data-change="calendar-date" value="${iso(state.selected)}" aria-label="Выбрать дату"></label>
      <button type="button" class="icon-btn" data-action="calendar-step" data-step="1" aria-label="Вперёд">${icon('right', 20)}</button>
      <button type="button" class="chip" data-action="calendar-today">Сегодня</button>
    </div>
    ${grid(events)}
    <div class="calendar-tools"><button type="button" class="btn small" data-action="calendar-import">Импорт</button></div>
    <div class="chips section" role="group" aria-label="Что показывать">${FILTERS.map(([k, v]) => `<button type="button" class="chip" data-action="calendar-filter" data-filter="${k}" aria-pressed="${state.filter === k}">${v}</button>`).join('')}</div>
    ${state.data ? attendance(events) + list(events) : skeleton(3)}`;
}

on('click', 'calendar-import', () => openSheet(`
  <div class="sheet-head"><h2>Импорт календаря</h2>
    <button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button>
  </div>
  <form class="form" data-submit="calendar-import">
    <label class="field">Ссылка iCal или webcal
      <input name="url" type="text" inputmode="url" autocapitalize="off" autocomplete="off" spellcheck="false"
        maxlength="2048" placeholder="https://… или webcal://…" required>
    </label>
    <button type="submit" class="btn primary block">Перенести события</button>
    <p class="meta"><b>Google</b> · Настройки → Интеграция календаря → адрес в формате iCal.</p>
    <p class="meta"><b>Apple</b> · Календари → ⓘ → Общедоступный календарь → Поделиться ссылкой.</p>
    <p class="meta">Период импорта — последние 30 и следующие 180 дней. Для обновления вставьте ту же ссылку ещё раз.</p>
  </form>`));
on('submit', 'calendar-import', async (form) => {
  const button = form.querySelector('button[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  try {
    const result = await api('calendar-import', { url: form.elements.url.value.trim() });
    closeSheet();
    toast(result.message);
    await load();
  } finally {
    button.disabled = false;
  }
});

on('click', 'calendar-mode', (b) => { state.mode = b.dataset.mode; return load(); });
on('click', 'calendar-filter', (b) => { state.filter = b.dataset.filter; render(); });
on('click', 'calendar-today', () => { state.selected = today(); return load(); });
on('click', 'calendar-step', (b) => {
  const step = +b.dataset.step;
  state.selected = state.mode === 'month'
    ? new Date(state.selected.getFullYear(), state.selected.getMonth() + step, 1, 12)
    : plus(state.selected, step * (state.mode === 'week' ? 7 : 1));
  return load();
});
on('click', 'pick-day', (b) => {
  const before = rangeFor('calendar')[0].getTime();
  state.selected = parseDay(b.dataset.day);
  if (state.mode === 'week') state.mode = 'day';
  if (rangeFor('calendar')[0].getTime() !== before) return load();
  render();
});
on('change', 'calendar-date', (input) => { if (input.value) { state.selected = parseDay(input.value); return load(); } });
