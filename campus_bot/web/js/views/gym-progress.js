// Progress: weekly workouts, a training calendar, personal records, a chart per
// exercise and the workout journal. Charts are single-series SVG in the accent
// colour, with a tap/hover tooltip and a table view for every one.
import { on, openSheet } from '../core.js';
import { figure, watchFigures } from '../figure.js';
import { icon } from '../icons.js';
import { empty } from '../parts.js';
import { esc, todayIso } from '../util.js';

let source = () => null;

export function connectProgress(getData) {
  source = getData;
}

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const shortDay = (iso) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
const kg = (n) => `${Math.round(n).toLocaleString('ru-RU')} кг`;
const num = (n) => (Number.isInteger(n) ? String(n) : String(n).replace('.', ','));
const find = (id) => (source()?.exercises || []).find((e) => e.id === id);
const plural = (n, one, few, many) => {
  const d = n % 10;
  const h = n % 100;
  if (d === 1 && h !== 11) return one;
  if (d >= 2 && d <= 4 && (h < 12 || h > 14)) return few;
  return many;
};

/** «60 кг × 5», «12 повт.», «1:30»: the record or best set in the person's own terms. */
export function setText(item, unit) {
  if (!item) return '';
  if (unit === 'seconds') {
    const s = Math.round(item.reps || item.value || 0);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }
  if (unit === 'minutes') return `${num(item.reps || item.value || 0)} мин`;
  return item.weight ? `${num(item.weight)} кг × ${num(item.reps)}` : `${num(item.reps)} повт.`;
}

/* ---------- Charts ---------- */
function weeksChart(weeks) {
  const W = 320;
  const H = 120;
  const top = Math.max(1, ...weeks.map((w) => w.workouts));
  const step = W / weeks.length;
  const bar = Math.min(18, step - 6);
  const goal = Number(source()?.settings?.workouts_week) || 0;
  const y = (v) => H - 18 - (v / Math.max(top, goal)) * (H - 30);
  const bars = weeks.map((w, i) => {
    const x = i * step + (step - bar) / 2;
    const h = H - 18 - y(w.workouts);
    const tip = `Неделя с ${shortDay(w.start)}: ${w.workouts} ${plural(w.workouts, 'тренировка', 'тренировки', 'тренировок')}, ${w.sets} подх., ${kg(w.volume)}`;
    return `<g class="tip-target" data-tip="${esc(tip)}" tabindex="0"><rect class="hit" x="${i * step}" y="0" width="${step}" height="${H}"/>
      ${w.workouts ? `<path class="bar" d="M${x} ${H - 18}V${H - 18 - Math.max(h, 6) + 4}a4 4 0 0 1 4 -4h${bar - 8}a4 4 0 0 1 4 4V${H - 18}Z"/>`
    : `<rect class="bar zero" x="${x}" y="${H - 20}" width="${bar}" height="2" rx="1"/>`}</g>`;
  }).join('');
  const goalLine = goal ? `<path class="goal" d="M0 ${y(goal)}H${W}"/><text class="axis" x="${W}" y="${y(goal) - 4}" text-anchor="end">цель ${goal}</text>` : '';
  const labels = [0, weeks.length - 1].map((i) => `<text class="axis" x="${i * step + step / 2}" y="${H - 4}" text-anchor="middle">${shortDay(weeks[i].start)}</text>`).join('');
  return `<div class="chart" data-chart><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Тренировки по неделям за 12 недель">
    <path class="baseline" d="M0 ${H - 18}H${W}"/>${goalLine}${bars}${labels}</svg>
    <p class="chart-tip" aria-live="polite">Нажмите на столбик, чтобы увидеть неделю.</p>
    <details class="chart-table"><summary>Таблица</summary><table><thead><tr><th>Неделя с</th><th>Тренировки</th><th>Подходы</th><th>Объём</th></tr></thead>
    <tbody>${weeks.map((w) => `<tr><td>${shortDay(w.start)}</td><td>${w.workouts}</td><td>${w.sets}</td><td>${kg(w.volume)}</td></tr>`).join('')}</tbody></table></details></div>`;
}

function calendar(days, weeks) {
  const start = new Date(weeks[0].start + 'T00:00:00');
  const today = todayIso();
  const cells = [];
  for (let i = 0; i < weeks.length * 7; i += 1) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const n = days[iso] || 0;
    const future = iso > today;
    const tip = future ? '' : ` data-tip="${esc(shortDay(iso))}: ${n ? `${n} ${plural(n, 'тренировка', 'тренировки', 'тренировок')}` : 'без тренировки'}" tabindex="0"`;
    const cls = [n ? 'on' : '', iso === today ? 'today' : '', future ? 'future' : ''].filter(Boolean).join(' ');
    cells.push(`<i class="${cls}" style="grid-column:${Math.floor(i / 7) + 2};grid-row:${(i % 7) + 1}"${tip}></i>`);
  }
  return `<div class="chart" data-chart><div class="train-cal" role="img" aria-label="Дни с тренировками за 12 недель">
    <span class="dow" style="grid-row:1">пн</span><span class="dow" style="grid-row:4">чт</span><span class="dow" style="grid-row:7">вс</span>${cells.join('')}</div>
    <p class="chart-tip" aria-live="polite">${Object.keys(days).length} ${plural(Object.keys(days).length, 'день', 'дня', 'дней')} с тренировками за 12 недель</p></div>`;
}

function lineChart(points, unit, kind) {
  const W = 320;
  const H = 150;
  const pad = { l: 34, r: 12, t: 12, b: 22 };
  const values = points.map((p) => p.value);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (hi - lo < 1) { lo -= 1; hi += 1; }
  const x = (i) => pad.l + (points.length === 1 ? (W - pad.l - pad.r) / 2 : (i / (points.length - 1)) * (W - pad.l - pad.r));
  const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const fmt = (v) => (kind === 'time' ? setText({ value: v }, unit) : `${num(Math.round(v))}`);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join(' ');
  const grid = [lo, (lo + hi) / 2, hi].map((v) => `<path class="grid" d="M${pad.l} ${y(v).toFixed(1)}H${W - pad.r}"/>
    <text class="axis" x="${pad.l - 6}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end">${esc(fmt(v))}</text>`).join('');
  const dots = points.map((p, i) => {
    const tip = `${shortDay(p.day)}: ${setText(p, unit)}${kind === 'weight' ? ` · ≈${num(Math.round(p.value))} кг на 1 раз` : ''}`;
    return `<g class="tip-target" data-tip="${esc(tip)}" tabindex="0"><circle class="hit" cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" r="14"/>
      <circle class="dot" cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" r="4.5"/></g>`;
  }).join('');
  const label = (i, anchor) => `<text class="axis" x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="${anchor}">${shortDay(points[i].day)}</text>`;
  const what = kind === 'weight' ? 'Расчётный максимум на 1 раз, кг' : kind === 'time' ? 'Лучшее время' : 'Лучшее число повторений';
  return `<div class="chart" data-chart><p class="chart-title">${what}</p><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(what)}: ${points.length} тренировок">
    ${grid}<path class="line" d="${path}"/>${dots}${label(0, 'start')}${points.length > 1 ? label(points.length - 1, 'end') : ''}</svg>
    <p class="chart-tip" aria-live="polite">Нажмите на точку, чтобы увидеть тренировку.</p></div>`;
}

/* ---------- Views ---------- */
function records(progress) {
  const list = Object.entries(progress.records).sort((a, b) => b[1].day.localeCompare(a[1].day)).slice(0, 12);
  if (!list.length) return '';
  return `<section class="section"><div class="section-head"><h2>Мои рекорды</h2></div><div class="record-list">${list.map(([id, r]) => {
    const e = find(id) || { name: progress.history[id]?.name || id };
    const unit = progress.history[id]?.unit || 'reps';
    return `<button type="button" class="record" data-action="progress-exercise" data-id="${esc(id)}">${figure(e, { size: 'thumb', still: true })}
      <span class="grow"><strong>${esc(e.name)}</strong><span class="meta">${shortDay(r.day)}${r.kind === 'weight' ? ` · ≈${num(Math.round(r.value))} кг на 1 раз` : ''}</span></span>
      <b class="record-value">${esc(setText(r, unit))}</b></button>`;
  }).join('')}</div></section>`;
}

function journal(data) {
  const prs = data.progress?.prs || {};
  const workouts = data.records.workout.filter((w) => w.status === 'done');
  return `<section class="section"><div class="section-head"><h2>Журнал за 4 недели</h2></div>${workouts.map((w) => {
    const sets = w.exercises.flatMap((e) => e.sets.filter((s) => s.done));
    const volume = w.exercises.filter((e) => (e.unit || 'reps') === 'reps').flatMap((e) => e.sets.filter((s) => s.done))
      .reduce((v, s) => v + (s.weight || 0) * (s.reps || 0), 0);
    const minutes = Math.max(0, Math.round((Date.parse(w.ended) - Date.parse(w.started)) / 60000));
    const best = prs[w.id] || [];
    return `<article class="card"><div class="row"><h3 class="grow">${esc(w.name)}</h3>
      <button type="button" class="icon-btn small ghost" data-action="gym-delete" data-kind="workout" data-id="${esc(w.id)}" aria-label="Удалить тренировку">${icon('trash', 18)}</button></div>
      <p class="meta">${shortDay(w.day)} · ${minutes} мин · ${sets.length} подх.${volume ? ' · ' + kg(volume) : ''}</p>
      ${best.length ? `<p class="pr-line">${icon('trophy', 14)} Рекорд: ${best.map((id) => esc(find(id)?.name || id)).join(', ')}</p>` : ''}
      <details><summary>Упражнения и подходы</summary>${w.exercises.map((e) => `<div class="section"><strong>${esc(e.name)}</strong>
        <p class="meta">${e.sets.filter((s) => s.done).map((s) => esc(setText(s, e.unit || 'reps'))).join(' · ') || 'Нет выполненных подходов'}</p></div>`).join('')}</details></article>`;
  }).join('') || empty('Здесь будет твой прогресс', 'Завершённые тренировки и рабочие веса останутся в истории.')}</section>`;
}

export function progressView() {
  const data = source();
  const p = data.progress;
  if (!p) return '';
  const week = p.weeks[p.weeks.length - 1];
  const goal = Number(data.settings?.workouts_week) || 0;
  const tiles = [
    [goal ? `${week.workouts} из ${goal}` : week.workouts, 'тренировок на этой неделе'],
    [p.streak, `${plural(p.streak, 'неделя', 'недели', 'недель')} подряд`],
    [kg(week.volume), 'объём за неделю'],
  ];
  return `<div class="stats wellness-stats section">${tiles.map(([v, label]) => `<div class="stat"><b>${esc(String(v))}</b><span>${label}</span></div>`).join('')}</div>
    <section class="section card"><div class="section-head"><h2>Тренировки по неделям</h2></div>${weeksChart(p.weeks)}</section>
    <section class="section card"><div class="section-head"><h2>Календарь</h2></div>${calendar(p.days, p.weeks)}</section>
    ${records(p)}${journal(data)}`;
}

export function exerciseProgress(id) {
  const data = source();
  const h = data.progress?.history?.[id];
  const e = find(id) || { name: h?.name || id };
  const r = data.progress?.records?.[id];
  const body = !h ? '<p class="meta">Это упражнение ещё не было в завершённых тренировках.</p>'
    : `${r ? `<div class="record-hero"><span class="meta">Рекорд · ${shortDay(r.day)}</span><b>${esc(setText(r, h.unit))}</b>
        ${r.kind === 'weight' ? `<span class="meta">≈${num(Math.round(r.value))} кг на 1 раз</span>` : ''}</div>` : ''}
      ${lineChart(h.points.slice(-24), h.unit, h.kind)}
      <details class="chart-table" open><summary>Тренировки</summary><table><thead><tr><th>Дата</th><th>Лучший подход</th><th>Подходы</th><th>Объём</th></tr></thead>
      <tbody>${h.points.slice().reverse().map((pt) => `<tr><td>${shortDay(pt.day)}</td><td>${esc(setText(pt, h.unit))}</td><td>${pt.sets}</td><td>${pt.volume ? kg(pt.volume) : '—'}</td></tr>`).join('')}</tbody></table></details>`;
  openSheet(`<div class="sheet-head"><h2>${esc(e.name)}</h2><button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    ${body}<button type="button" class="btn block" data-action="gym-exercise" data-id="${esc(id)}">${icon('book', 18)}Техника и мышцы</button>`);
  watchFigures();
}

/* ---------- Tooltips: hover on a computer, tap on a phone ---------- */
function showTip(target) {
  const box = target.closest('[data-chart]')?.querySelector('.chart-tip');
  if (!box) return;
  box.textContent = target.dataset.tip;
  target.closest('[data-chart]').querySelectorAll('.active').forEach((el) => el.classList.remove('active'));
  target.classList.add('active');
}
for (const type of ['pointerover', 'focusin', 'click']) {
  document.addEventListener(type, (event) => {
    const target = event.target.closest?.('[data-chart] [data-tip]');
    if (target) showTip(target);
  });
}

on('click', 'progress-exercise', (b) => exerciseProgress(b.dataset.id));
