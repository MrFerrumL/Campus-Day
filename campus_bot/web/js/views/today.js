// «Сегодня»: what is happening now, the day's timeline, the weather and today's deadlines.
import { state } from '../core.js';
import { icon } from '../icons.js';
import { dayTitle, empty, eventCard, skeleton, taskRow, weatherCard } from '../parts.js';
import { clock, count, currentOrNext, duration, esc, eventsOn, isOpen, minutesBetween, nowIso, taskBuckets } from '../util.js';

function summary(events, dueToday) {
  const uni = events.filter((e) => e.source === 'university').length;
  const lessons = events.filter((e) => e.source === 'personal').length;
  const parts = [];
  if (uni) parts.push(count(uni, 'пара', 'пары', 'пар'));
  if (lessons) parts.push(count(lessons, 'занятие', 'занятия', 'занятий'));
  if (dueToday) parts.push(count(dueToday, 'дедлайн', 'дедлайна', 'дедлайнов'));
  return parts.join(' · ') || 'Свободный день';
}

function nowCard(found, now) {
  if (!found) return '';
  const e = found.event;
  const label = found.kind === 'now'
    ? `Сейчас · ещё ${duration(minutesBetween(now, e.end))}`
    : `Далее · через ${duration(minutesBetween(now, e.start))}`;
  const total = Math.max(1, minutesBetween(e.start, e.end));
  const progress = found.kind === 'now' ? Math.min(100, Math.round(minutesBetween(e.start, now) / total * 100)) : 0;
  return `<div class="card now" role="status">
    <div class="label">${esc(label)}</div>
    <h3>${esc(e.title)}</h3>
    <div class="details">${esc(clock(e.start))}${e.end !== e.start ? '–' + esc(clock(e.end)) : ''}${e.details ? ' · ' + esc(e.details) : ''}</div>
    ${found.kind === 'now' ? `<div class="bar" aria-hidden="true"><i style="width:${progress}%"></i></div>` : ''}
  </div>`;
}

const capital = (text) => text[0].toUpperCase() + text.slice(1);

const thousands = (v) => Math.round(Number(v) || 0).toLocaleString('ru-RU');
const litres = (ml) => `${(ml / 1000).toFixed(1).replace('.', ',')} л`;

/** Food, water, sleep and training at a glance; each tile opens its page in the gym tab. */
function wellnessCard(w) {
  if (!w) return '';
  const g = w.goals || {};
  const tile = (section, glyph, label, value, note, done) => `<button type="button" class="day-tile ${done ? 'done' : ''}" data-action="go-gym" data-section="${section}">
    <span class="day-tile-head">${icon(glyph, 16)}${label}</span><b>${esc(value)}</b><span class="meta">${esc(note)}</span></button>`;
  const sleepNote = g.sleep_hours ? `цель ${String(g.sleep_hours).replace('.', ',')} ч` : 'за прошлую ночь';
  const gym = w.active
    ? tile('workout', 'dumbbell', 'Зал', `${w.active.done} из ${w.active.total}`, 'тренировка идёт', false)
    : tile('train', 'dumbbell', 'Зал', w.workouts.length ? 'Сделано' : 'Нет', w.workouts.length ? w.workouts[0] : 'сегодня без тренировки', w.workouts.length > 0);
  return `<section class="section" aria-labelledby="today-health">
    <div class="section-head"><h2 id="today-health">Здоровье</h2>
      <button type="button" class="link-btn" data-action="go-gym" data-section="food">Дневник ${icon('right', 16)}</button></div>
    <div class="day-tiles">
      ${tile('food', 'flame', 'Еда', `${thousands(w.calories)} ккал`, g.calories ? `из ${thousands(g.calories)}` : `${w.meals} ${w.meals === 1 ? 'приём' : 'приёма'}`, g.calories && w.calories >= g.calories * 0.9)}
      ${tile('food', 'drop', 'Вода', litres(w.water_ml), g.water_ml ? `из ${litres(g.water_ml)}` : 'за сегодня', g.water_ml && w.water_ml >= g.water_ml)}
      ${tile('sleep', 'moon', 'Сон', w.sleep_minutes ? `${Math.floor(w.sleep_minutes / 60)} ч ${w.sleep_minutes % 60} мин` : 'Нет записи', sleepNote,
        g.sleep_hours && w.sleep_minutes >= g.sleep_hours * 60)}
      ${gym}
    </div></section>`;
}

export function view() {
  const data = state.data, now = nowIso(), day = now.slice(0, 10);
  if (!data) return `<div class="page-head"><h1>${esc(capital(dayTitle(day)))}</h1></div>${skeleton(4)}`;
  const events = eventsOn(data.events, day).filter((e) => !e.cancelled || e.source === 'university');
  const active = events.filter((e) => !e.cancelled);
  const open = data.tasks.filter((t) => isOpen(t) && !t.is_group);
  const buckets = taskBuckets(open, now);
  const doneToday = data.tasks.filter((t) => t.done && !t.is_group && t.due.slice(0, 10) === day).length;
  return `
    <header class="today-overview">
      <div class="today-heading">
        <div><h1>${esc(capital(dayTitle(day)))}</h1><p>${esc(summary(active, buckets.today.length))}</p></div>
        <span class="today-mark" aria-hidden="true">${icon('sun', 34)}</span>
      </div>
      <div class="today-actions">
        <button type="button" data-action="go-tab" data-tab="calendar">${icon('calendar',18)} Расписание</button>
        <button type="button" data-action="go-tab" data-tab="tasks">${icon('tasks',18)} Задачи</button>
        <button type="button" data-action="go-gym" data-section="train">${icon('dumbbell',18)} Тренировки</button>
      </div>
    </header>
    <div class="stack">
      ${nowCard(currentOrNext(active, now), now)}
      ${weatherCard(data.weather_brief, data.weather)}
    </div>
    ${wellnessCard(data.wellness)}
    <section class="section" aria-labelledby="today-plan">
      <div class="section-head"><h2 id="today-plan">Расписание</h2>
        <button type="button" class="link-btn" data-action="go-tab" data-tab="calendar">Неделя ${icon('right', 16)}</button></div>
      <div class="timeline">${events.map((e) => eventCard(e, { now })).join('') || empty('Можно выдохнуть', 'На сегодня ничего не запланировано.')}</div>
    </section>
    <section class="section" aria-labelledby="today-deadlines">
      <div class="section-head"><h2 id="today-deadlines">Дедлайны сегодня</h2>
        <span class="meta">${doneToday ? `сделано ${doneToday}` : ''}</span></div>
      ${buckets.overdue.length ? `<button type="button" class="notice danger" style="width:100%;text-align:left;margin-bottom:10px" data-action="go-tab" data-tab="tasks" data-filter="overdue">
        ${icon('alert', 18)}<span>${esc(count(buckets.overdue.length, 'просроченная задача', 'просроченные задачи', 'просроченных задач'))} — открыть</span></button>` : ''}
      ${buckets.today.length ? `<div class="tasks">${buckets.today.map((t) => taskRow(t, { now })).join('')}</div>` : empty('Дедлайнов нет', 'Новые задачи добавляются кнопкой «+».')}
    </section>`;
}
