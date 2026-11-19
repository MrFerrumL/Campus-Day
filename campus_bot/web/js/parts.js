// UI pieces used by several screens, and the actions behind them.
import { api, haptic, on, openLink, render, save, state, switchTab, toast } from './core.js';
import { openEditor } from './editor.js';
import { icon } from './icons.js';
import { SOURCE_LABEL, clock, esc, fmt, humanDay, nowIso, parseDay, todayIso } from './util.js';

export const empty = (title, text) => `<div class="empty"><strong>${esc(title)}</strong>${esc(text)}</div>`;

export function skeleton(n = 3) {
  return Array.from({ length: n }, () => '<div class="skeleton" aria-hidden="true"></div>').join('');
}

/* ---------- Weather ---------- */
export function weatherCard(brief, text) {
  if (!brief) {
    return text ? `<div class="card weather"><div class="wicon">${icon('cloudy', 26)}</div><div class="grow small-text">${esc(text.split('\n')[0])}</div></div>` : '';
  }
  const n = (value) => Math.round(Number(value)) || 0;
  brief = { ...brief, temperature: n(brief.temperature), low: n(brief.low), high: n(brief.high), wind: n(brief.wind),
    feels_like: brief.feels_like == null ? null : n(brief.feels_like) };
  const parts = [`${brief.low}…${brief.high}°`, `ветер ${brief.wind} м/с`, `осадки ${brief.precipitation}`];
  return `<div class="card weather" aria-label="Прогноз погоды">
    <div class="wicon">${icon(brief.icon, 26)}</div>
    <div class="grow">
      <div class="row"><span class="temp">${brief.temperature > 0 ? '+' : ''}${brief.temperature}°</span>
        <span class="desc">${esc(brief.description)}</span></div>
      <div class="details">${esc(parts.join(' · '))}${brief.feels_like != null ? ` · ощущается ${brief.feels_like > 0 ? '+' : ''}${brief.feels_like}°` : ''}</div>
      ${brief.stale ? `<div class="details">Прогноз от ${esc(brief.updated)}: источник временно недоступен</div>` : ''}
    </div>
    ${brief.umbrella ? `<span class="badge src-plan umbrella">${icon('umbrella', 14)} Зонт</span>` : ''}
  </div>`;
}

/* ---------- Events ---------- */
function attendance(e) {
  const status = e.attendance || 'pending';
  const future = e.start.slice(0, 10) > todayIso();
  if (e.cancelled) return '<span class="attend-note">Пара отменена</span>';
  if (future) return '<span class="attend-note">Отметка посещения — в день пары</span>';
  const button = (value, label, glyph) => `<button type="button" class="${value}" data-action="attendance"
      data-key="${esc(e.key)}" data-status="${status === value ? 'pending' : value}" aria-pressed="${status === value}">${icon(glyph, 14)}${label}</button>`;
  return `<div class="attend" role="group" aria-label="Посещение пары">${button('present', 'Был', 'check')}${button('absent', 'Не был', 'x')}</div>`;
}

const MARKS = { present: 'был', absent: 'не был', pending: 'не отмечено' };
function markLabel(e) {
  if (e.source !== 'university' || e.cancelled || e.start.slice(0, 10) > todayIso()) return '';
  const status = e.attendance || 'pending';
  return `<span class="mark ${status}">${MARKS[status]}</span>`;
}

export function eventCard(e, { showDay = false, now = nowIso() } = {}) {
  const uni = e.source === 'university';
  const current = !e.cancelled && !e.all_day && e.start.slice(0, 16) <= now && now < e.end.slice(0, 16);
  const doneClass = !uni && e.done ? 'done' : '';
  const time = e.all_day ? 'весь день' : clock(e.start);
  const end = e.all_day || e.start === e.end ? '' : clock(e.end);
  const editAttr = e.source === 'hackathon'
    ? `data-action="edit-stage" data-id="${esc(e.uid.split(':')[1])}"`
    : `data-action="edit-event" data-key="${esc(e.key)}"`;
  const missed = uni && e.attendance === 'absent' ? 'missed' : '';
  return `<article class="event src-${esc(e.source)} ${doneClass} ${missed} ${e.cancelled ? 'cancelled' : ''} ${current ? 'current' : ''}">
    <div class="when ${e.all_day ? 'allday' : ''}">${esc(time)}${end ? `<small>${esc(end)}</small>` : ''}</div>
    <div class="card">
      <div class="head">
        <div class="grow">
          <span class="tag">${SOURCE_LABEL[e.source] || ''}${e.cancelled ? ' · отменено' : ''}${showDay ? ' · ' + esc(humanDay(e.start.slice(0, 10))) : ''}</span>${markLabel(e)}
          <h3>${esc(e.title)}</h3>
          ${e.details ? `<div class="details">${esc(e.details)}</div>` : ''}
        </div>
        <button type="button" class="icon-btn small ghost" ${editAttr} aria-label="Изменить «${esc(e.title)}»">${icon('edit', 18)}</button>
        ${uni ? '' : `<button type="button" class="check" data-action="check-event" data-key="${esc(e.key)}" aria-pressed="${!!e.done}"
            aria-label="Выполнено" ${e.cancelled ? 'disabled' : ''}>${icon('check', 18)}</button>`}
      </div>
      ${uni ? `<div class="actions">${attendance(e)}</div>` : ''}
    </div>
  </article>`;
}

/* ---------- Tasks ---------- */
const REPEAT_LABEL = { daily: 'каждый день', weekdays: 'по будням', weekly: 'каждую неделю' };
export function taskRow(t, { now = nowIso() } = {}) {
  const day = t.due.slice(0, 10);
  const late = !t.done && !t.skipped && (t.all_day ? day < now.slice(0, 10) : t.due.slice(0, 16) < now);
  const when = t.all_day ? humanDay(day) : `${humanDay(day)}, ${t.duration ? clock(blockStart(t)) + '–' : ''}${clock(t.due)}`;
  const project = t.project ? (state.data?.hackathons || []).find((h) => h.id === t.project)?.title : '';
  return `<div class="task ${t.done ? 'done' : ''} ${t.skipped ? 'failed' : ''}" style="padding-left:${14 + Math.min(t.depth || 0, 3) * 22}px">
    <button type="button" class="check" data-action="check-task" data-id="${Number(t.id)}" aria-pressed="${!!t.done}"
      aria-label="Сделано">${icon('check', 18)}</button>
    <div class="body">
      <div class="title">${t.priority ? `<span class="flag">${icon('flame', 16, 'Важная')}</span>` : ''}${esc(t.title)}</div>
      <div class="meta">
        <span class="${late ? 'late' : ''}">${late ? 'Просрочено · ' : ''}${esc(when)}</span>
        ${t.skipped ? '<span>Не сделано</span>' : ''}
        ${REPEAT_LABEL[t.recurrence] ? `<span>${icon('refresh', 12)} ${REPEAT_LABEL[t.recurrence]}</span>` : ''}
        ${project ? `<span class="badge src-hackathon">${icon('trophy', 12)} ${esc(project)}</span>` : ''}
      </div>
      ${t.note ? `<div class="note">${esc(t.note)}</div>` : ''}
    </div>
    <div class="tools">
      ${t.done ? '' : `<button type="button" class="icon-btn small ghost" data-action="fail-task" data-id="${t.id}"
        aria-label="${t.skipped ? 'Вернуть в работу' : 'Не сделано'}">${icon(t.skipped ? 'undo' : 'x', 18)}</button>`}
      <button type="button" class="icon-btn small ghost" data-action="edit-task" data-id="${t.id}" aria-label="Изменить задачу">${icon('edit', 18)}</button>
    </div>
  </div>`;
}
const blockStart = (t) => new Date(Date.parse(t.due.slice(0, 19) + 'Z') - t.duration * 60000).toISOString().slice(0, 16);

export const dayTitle = (day) => fmt(parseDay(day), { weekday: 'long', day: 'numeric', month: 'long' });

/* ---------- Shared actions ---------- */
const findEvent = (key) => state.data?.events.find((x) => x.key === key);
const findTask = (id) => state.data?.tasks.find((x) => x.id === +id);

on('click', 'attendance', async (button) => {
  const item = findEvent(button.dataset.key);
  button.closest('.attend').querySelectorAll('button').forEach((b) => { b.disabled = true; });
  try {
    await api('attendance', { key: button.dataset.key, status: button.dataset.status });
    if (item) { item.attendance = button.dataset.status; item.done = button.dataset.status === 'present'; }
    haptic('success');
    toast('Посещение сохранено');
  } finally { render(); }
});
on('click', 'check-event', async (button) => {
  const item = findEvent(button.dataset.key);
  button.disabled = true;
  await save('check', { key: item.key, done: !item.done }, item.done ? 'Отметка снята' : 'Отмечено');
});
on('click', 'edit-event', (button) => openEditor('override', findEvent(button.dataset.key)));
on('click', 'check-task', async (button) => {
  const item = findTask(button.dataset.id);
  button.disabled = true;
  await save('task-check', { id: item.id, done: !item.done }, item.done ? 'Задача снова в работе' : 'Сделано');
});
on('click', 'fail-task', async (button) => {
  const item = findTask(button.dataset.id);
  button.disabled = true;
  await save('task-status', { id: item.id, status: item.skipped ? 'pending' : 'failed' }, item.skipped ? 'Задача снова в работе' : 'Отмечено: не сделано');
});
on('click', 'edit-task', (button) => openEditor('task', findTask(button.dataset.id)));
on('click', 'open-link', (link, event) => { event.preventDefault(); openLink(link.dataset.url); });
on('click', 'go-tab', (button) => {
  if (button.dataset.filter) state.taskFilter = button.dataset.filter;
  return switchTab(button.dataset.tab);
});
