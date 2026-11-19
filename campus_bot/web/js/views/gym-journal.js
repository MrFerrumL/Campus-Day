// Food and sleep pages of the gym tab: progress toward personal goals, one-tap
// repeats of frequent meals and of the last sleep, and 7-day charts.
import { on, toast } from '../core.js';
import { barChart } from '../charts.js';
import { icon } from '../icons.js';
import { empty } from '../parts.js';
import { esc, todayIso } from '../util.js';

let source = () => null;
let currentDay = () => todayIso();
let picker = () => '';
let save = async () => {};

/** gym.js hands over its data, the journal day, its date picker and its save-and-reload. */
export function connectJournal(getData, getDay, datePicker, mutate) {
  source = getData;
  currentDay = getDay;
  picker = datePicker;
  save = mutate;
}

const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
const weekday = (iso) => WEEKDAYS[new Date(iso + 'T12:00:00').getDay()];
const dm = (iso) => `${Number(iso.slice(8, 10))}.${iso.slice(5, 7)}`;
const n = (v) => Math.round(Number(v) || 0).toLocaleString('ru-RU');
const hours = (minutes) => (minutes ? `${Math.floor(minutes / 60)} ч ${minutes % 60} мин` : '—');
const shortHours = (minutes) => (minutes ? `${(minutes / 60).toFixed(1).replace('.', ',')} ч` : '—');

/** A labelled bar toward a goal; without a goal just the number. */
function meter(label, value, goal, unit) {
  const v = Number(value) || 0;
  if (!goal) return `<div class="meter"><div class="meter-head"><span>${label}</span><b>${n(v)} ${unit}</b></div></div>`;
  const ratio = v / goal;
  const over = ratio > 1.05;
  const note = over ? `больше цели на ${n(v - goal)} ${unit}` : ratio >= 1 ? 'цель достигнута' : `осталось ${n(goal - v)} ${unit}`;
  return `<div class="meter ${over ? 'over' : ''}"><div class="meter-head"><span>${label}</span><b>${n(v)} / ${n(goal)} ${unit}</b></div>
    <div class="progress" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="${goal}" aria-valuenow="${Math.min(goal, v)}"><i style="width:${Math.min(100, ratio * 100)}%"></i></div>
    <span class="meta">${note}</span></div>`;
}

/** Steps, activities and gym workouts of the day with the active calories they burned. */
function activityCard(data, day) {
  const a = data.activity || { steps: 0, items: [], burned: null, weight_known: false };
  const s = data.summary;
  const balance = a.burned == null ? '' : `<p class="meta">Съедено − потрачено: <b>${n(s.calories - a.burned)} ккал</b></p>`;
  return `<section class="section card activity-card"><div class="section-head"><h2>Активность</h2>
      <span class="meta">${a.burned == null ? 'нужен вес' : `потрачено ${n(a.burned)} ккал`}</span></div>
    ${a.weight_known ? '' : '<button type="button" class="link-btn" data-action="gym-goals">Укажите вес и рост — без них расход не считается</button>'}
    <form class="row steps-row" data-submit="gym-steps-save"><label class="field grow">Шаги за день<input name="steps" type="number" min="0" max="100000" step="1" inputmode="numeric" value="${a.steps || ''}" placeholder="10000"></label>
      <button class="btn">Сохранить</button></form>
    ${a.steps ? `<p class="meta">≈ ${String(a.steps_km).replace('.', ',')} км${a.steps_kcal != null ? ` · ${n(a.steps_kcal)} ккал` : ''}</p>` : ''}
    ${a.items.map((i) => `<div class="journal-row"><div class="grow"><strong>${esc(i.name)}</strong>
      <div class="meta">${esc(i.time || '')} · ${i.minutes} мин${i.distance_km ? ` · ${String(i.distance_km).replace('.', ',')} км` : ''}${i.kcal != null ? ` · ${i.counted === false ? `<s>${n(i.kcal)} ккал</s> ${esc(i.why)}` : `${n(i.kcal)} ккал`}` : ''}${i.workout ? ' · из журнала тренировок' : ''}</div></div>
      ${i.workout ? '' : `<button type="button" class="icon-btn small ghost" data-action="gym-delete" data-kind="activity" data-id="${esc(i.id)}" aria-label="Удалить активность">${icon('trash', 18)}</button>`}</div>`).join('')}
    <button type="button" class="btn block" data-action="gym-activity">${icon('plus', 18)}Бег, зал, велосипед…</button>
    ${balance}
    <p class="muted small-text">Считаются только активные калории сверх покоя (MET × вес × время), поэтому норма калорий от них не меняется.</p></section>`;
}

export function foodView() {
  const data = source();
  const day = currentDay();
  const s = data.summary;
  const g = data.settings || {};
  const meals = data.records.meal.filter((r) => r.day === day).sort((a, b) => (a.time || '').localeCompare(b.time || ''));
  const water = data.records.water.filter((r) => r.day === day);
  const hasGoals = g.calories || g.protein || g.water_ml;
  const week = data.week || [];
  const grams = (key) => meals.some((meal) => meal[key] != null) ? `${n(s[key])} г` : '—';
  return `${picker()}
    <section class="section card day-meters nutrition-overview">
      <div class="section-head"><h2>Дневные цели</h2>
        <button type="button" class="btn small" data-action="gym-goals">${hasGoals ? 'Изменить' : 'Настроить'}</button></div>
      ${meter('Калории', s.calories, g.calories, 'ккал')}
      ${meter('Белок', s.protein, g.protein, 'г')}
      ${meter('Вода', s.water_ml, g.water_ml, 'мл')}
      <div class="macro-strip"><span>Б ${grams('protein')}</span><span>Ж ${grams('fat')}</span><span>У ${grams('carbs')}</span></div>
      ${s.missing_calories ? `<p class="muted small-text">У ${s.missing_calories} записей не указаны калории — они не вошли в сумму.</p>` : ''}
      <button type="button" class="btn primary block" data-action="gym-meal">${icon('plus', 18)}Записать еду</button>
    </section>
    <section class="section card"><div class="section-head"><h2>Записать воду</h2></div>
      <div class="water-controls">${[200, 300, 500].map((ml) => `<button type="button" class="btn" data-action="gym-water" data-ml="${ml}">+${ml} мл</button>`).join('')}
        <button type="button" class="btn" data-action="gym-water-custom">Свой объём</button></div>
      ${water.length ? `<details class="section"><summary>Записи · ${water.length}</summary>${water.map((r) => `<div class="journal-row"><span class="grow">${n(r.ml)} мл</span>
        <button type="button" class="icon-btn small ghost" data-action="gym-delete" data-kind="water" data-id="${esc(r.id)}" aria-label="Удалить воду">${icon('x', 16)}</button></div>`).join('')}</details>` : ''}</section>
    ${data.frequent?.length ? `<section class="section"><div class="section-head"><h2>Часто ем</h2><span class="meta">одно касание — запись</span></div>
      <div class="repeat-list">${data.frequent.map((m, i) => `<button type="button" class="repeat" data-action="food-repeat" data-i="${i}">
        ${icon('plus', 16)}<span><strong>${esc(m.name)}</strong><span class="meta">${m.calories != null ? `${n(m.calories)} ккал` : 'без калорий'}${m.protein != null ? ` · Б ${n(m.protein)} г` : ''}</span></span></button>`).join('')}</div></section>` : ''}
    <section class="section"><div class="section-head"><h2>Питание за день</h2></div>${meals.map((m) => `<article class="card journal-row"><div class="grow"><strong>${esc(m.name)}</strong>
      <div class="meta">${esc(m.time || '')} · ${m.calories == null ? 'калории не указаны' : n(m.calories) + ' ккал'}${m.protein == null ? '' : ' · Б ' + n(m.protein) + ' г'}</div>${m.note ? `<p class="meta">${esc(m.note)}</p>` : ''}</div>
      <button type="button" class="icon-btn small ghost" data-action="gym-meal" data-id="${esc(m.id)}" aria-label="Изменить приём пищи">${icon('edit', 18)}</button>
      <button type="button" class="icon-btn small ghost" data-action="gym-delete" data-kind="meal" data-id="${esc(m.id)}" aria-label="Удалить приём пищи">${icon('trash', 18)}</button></article>`).join('')
      || empty('Что было на завтрак?', 'Добавьте еду и известные калории или БЖУ. Неизвестное можно не заполнять.')}</section>
    ${activityCard(data, day)}
    ${week.length ? `<section class="section card"><div class="section-head"><h2>Калории за неделю</h2>${g.calories ? `<span class="meta">цель ${n(g.calories)}</span>` : ''}</div>
      ${barChart(week.map((d) => ({ label: weekday(d.day), value: d.calories, tip: `${weekday(d.day)} ${dm(d.day)}: ${n(d.calories)} ккал, белок ${n(d.protein)} г, вода ${n(d.water_ml)} мл` })), {
        goal: Number(g.calories) || 0, aria: 'Калории по дням за неделю',
        columns: [['День', (d) => d.label], ['Ккал', (d) => n(d.value)]],
      })}</section>` : ''}`;
}

/** The last sleep can be repeated only if its times fit the chosen day: not in the future, not 24 hours long. */
function canRepeat(prev, day) {
  if (!prev) return false;
  const start = prev.start.slice(11, 16);
  const end = prev.end.slice(11, 16);
  if (start === end) return false;
  if (day !== todayIso()) return true;
  const now = new Date();
  return end <= `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
}

function lastSleep() {
  return [...(source()?.records?.sleep || [])].sort((a, b) => b.end.localeCompare(a.end))[0];
}

export function sleepView() {
  const data = source();
  const day = currentDay();
  const g = data.settings || {};
  const rows = data.records.sleep.filter((r) => r.day === day);
  const minutes = rows.reduce((v, r) => v + r.minutes, 0);
  const goal = Number(g.sleep_hours) ? Number(g.sleep_hours) * 60 : 0;
  const prev = lastSleep();
  const week = data.week || [];
  const tiles = [[shortHours(minutes), 'сон за выбранный день'], [shortHours(data.summary.sleep_average), 'среднее за 7 дней'],
    [goal ? shortHours(goal) : String(data.summary.sleep_days), goal ? 'цель' : 'дней с записями']];
  return `${picker()}<div class="stats wellness-stats section">${tiles.map(([v, label]) => `<div class="stat"><b>${esc(String(v))}</b><span>${label}</span></div>`).join('')}</div>
    <div class="row section"><button type="button" class="btn primary grow" data-action="gym-sleep">${icon('plus', 18)}Записать сон</button>
      ${canRepeat(prev, day) && !rows.some((r) => r.minutes >= 180) ? `<button type="button" class="btn grow" data-action="sleep-again">Как в прошлый раз: ${esc(prev.start.slice(11, 16))}–${esc(prev.end.slice(11, 16))}</button>` : ''}</div>
    ${rows.map((r) => `<article class="card section"><div class="row"><h2 class="grow">${hours(r.minutes)}</h2>
      <button type="button" class="icon-btn small ghost" data-action="gym-sleep" data-id="${esc(r.id)}" aria-label="Изменить сон">${icon('edit', 18)}</button>
      <button type="button" class="icon-btn small ghost" data-action="gym-delete" data-kind="sleep" data-id="${esc(r.id)}" aria-label="Удалить сон">${icon('trash', 18)}</button></div>
      <p>${esc(dm(r.start.slice(0, 10)))} ${esc(r.start.slice(11, 16))} → ${esc(dm(r.end.slice(0, 10)))} ${esc(r.end.slice(11, 16))}</p>
      <p class="meta">Самочувствие: ${'★'.repeat(r.quality)}${'☆'.repeat(5 - r.quality)}${r.note ? ' · ' + esc(r.note) : ''}</p></article>`).join('')}
    ${week.length ? `<section class="section card"><div class="section-head"><h2>Сон за неделю</h2>${goal ? `<span class="meta">цель ${shortHours(goal)}</span>` : ''}</div>
      ${barChart(week.map((d) => ({ label: weekday(d.day), value: d.sleep_minutes,
        tip: `${weekday(d.day)} ${dm(d.day)}: ${hours(d.sleep_minutes)}${d.quality ? `, самочувствие ${String(d.quality).replace('.', ',')} из 5` : ''}` })), {
        goal, aria: 'Сон по дням за неделю',
        columns: [['День', (d) => d.label], ['Сон', (d) => hours(d.value)]],
      })}<p class="meta">Дата записи — день пробуждения. Дневной сон тоже можно записать.</p></section>` : ''}`;
}

on('click', 'food-repeat', async (b) => {
  const m = source().frequent?.[Number(b.dataset.i)];
  if (!m) return;
  b.disabled = true;
  const now = new Date();
  // Today the meal is logged now; on a past day at the time it is usually eaten.
  const time = currentDay() === todayIso() || !m.time
    ? `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}` : m.time;
  try {
    await save('wellness-meal', { day: currentDay(), name: m.name, time, calories: m.calories, protein: m.protein, fat: m.fat, carbs: m.carbs });
    toast(`Записано: ${m.name}`);
  } finally { b.disabled = false; }
});

on('click', 'sleep-again', async (b) => {
  const prev = lastSleep();
  if (!prev) return;
  const day = currentDay();
  const startClock = prev.start.slice(11, 16);
  const endClock = prev.end.slice(11, 16);
  // Overnight sleep starts the evening before the wake-up day; a nap starts and ends the same day.
  const before = new Date(day + 'T12:00:00');
  before.setDate(before.getDate() - 1);
  const startDay = startClock < endClock ? day : `${before.getFullYear()}-${String(before.getMonth() + 1).padStart(2, '0')}-${String(before.getDate()).padStart(2, '0')}`;
  b.disabled = true;
  try {
    await save('wellness-sleep', { day, start: `${startDay}T${startClock}`, end: `${day}T${endClock}`, quality: prev.quality });
    toast('Сон записан');
  } finally { b.disabled = false; }
});
