// «Задачи»: grouped by when they are due, with the same filters as the bot's /tasks.
import { api, haptic, load, on, render, state, toast } from '../core.js';
import { icon } from '../icons.js';
import { empty, skeleton, taskRow } from '../parts.js';
import { esc, fmt, humanDay, isOpen, iso, nowIso, parseDay, plus, taskBuckets, taskTree } from '../util.js';

let mode = 'list';
const FILTERS = [['active', 'В работе'], ['overdue', 'Просрочено'], ['important', 'Важные'], ['done', 'Сделано'], ['failed', 'Не сделано'], ['all', 'Все']];
const GROUPS = [['overdue', 'Просрочено'], ['today', 'Сегодня'], ['tomorrow', 'Завтра'], ['week', 'На неделе'], ['later', 'Позже']];

/** Keep groups whole: a parent stays visible while any of its subtasks matches. */
function withParents(all, matching) {
  const byId = new Map(all.map((t) => [t.id, t])), keep = new Set(matching.map((t) => t.id));
  for (const t of matching) {
    let parent = byId.get(t.parent_id);
    while (parent) { keep.add(parent.id); parent = byId.get(parent.parent_id); }
  }
  return all.filter((t) => keep.has(t.id));
}

function block(tasks, all, now) {
  return `<div class="tasks">${taskTree(withParents(all, tasks)).map((t) => taskRow(t, { now })).join('')}</div>`;
}

export function view() {
  if (!state.data) return `<div class="page-head"><h1>Задачи</h1></div>${skeleton(4)}`;
  const now = nowIso(), all = state.data.tasks, leaves = all.filter((t) => !t.is_group);
  const open = leaves.filter(isOpen), buckets = taskBuckets(open, now);
  const weekAgo = iso(plus(parseDay(now.slice(0, 10)), -6));
  const doneWeek = leaves.filter((t) => t.done && (t.done_at || t.due).slice(0, 10) >= weekAgo).length;
  const counts = { active: open.length, overdue: buckets.overdue.length, important: open.filter((t) => t.priority).length,
    done: leaves.filter((t) => t.done).length, failed: leaves.filter((t) => t.skipped).length, all: leaves.length };
  let body;
  if (state.taskFilter === 'active') {
    body = GROUPS.filter(([k]) => buckets[k].length).map(([k, label]) => `<section class="task-group ${k}">
      <h3>${label} · ${buckets[k].length}</h3>${block(buckets[k], all, now)}</section>`).join('')
      || empty('Всё сделано', 'Новая задача — кнопкой «+» или сообщением боту «План на завтра».');
  } else {
    const pick = { overdue: buckets.overdue, important: open.filter((t) => t.priority), done: leaves.filter((t) => t.done),
      failed: leaves.filter((t) => t.skipped), all: leaves }[state.taskFilter] || [];
    const sorted = state.taskFilter === 'done' ? [...pick].sort((a, b) => b.due.localeCompare(a.due)) : pick;
    body = sorted.length ? `<div class="section">${block(sorted, all, now)}</div>` : empty('Пусто', 'Здесь пока ничего нет.');
  }
  const head = `<div class="page-head"><h1>Задачи</h1><p>Дедлайны и планы синхронизируются с ботом</p></div>
    <form class="quick" data-submit="quick-task"><label class="sr-only" for="quick-task">Новая задача одной строкой</label>
      <input id="quick-task" name="text" maxlength="300" autocomplete="off" placeholder="Например: завтра 18:00 сдать лабу" required>
      <button class="icon-btn" aria-label="Добавить задачу">${icon('plus', 20)}</button></form>
    <div class="segmented section" role="group" aria-label="Вид">
      <button type="button" data-action="tasks-mode" data-mode="list" aria-pressed="${mode === 'list'}">Список</button>
      <button type="button" data-action="tasks-mode" data-mode="stats" aria-pressed="${mode === 'stats'}">Аналитика</button></div>`;
  if (mode === 'stats') return head + statsView(leaves, now);
  return `${head}
    <div class="stats section">
      <div class="stat"><b>${counts.active}</b><span>в работе</span></div>
      <div class="stat ${counts.overdue ? 'alert' : ''}"><b>${counts.overdue}</b><span>просрочено</span></div>
      <div class="stat"><b>${doneWeek}</b><span>сделано за неделю</span></div>
    </div>
    <div class="chips" role="group" aria-label="Фильтр задач">${FILTERS.map(([k, v]) => `<button type="button" class="chip" data-action="task-filter" data-filter="${k}"
      aria-pressed="${state.taskFilter === k}">${v}${counts[k] ? ` <span class="count">${counts[k]}</span>` : ''}</button>`).join('')}</div>
    ${body}`;
}

/* ---------- Analytics: last 14 days by due date, streak by completion day ---------- */
const doneDay = (t) => (t.done_at && t.done_at.length > 10 ? nowIso(new Date(t.done_at)) : (t.done_at || '')).slice(0, 10);

function statsView(leaves, now) {
  const today = now.slice(0, 10), days = [];
  for (let n = 13; n >= 0; n -= 1) {
    const day = iso(plus(parseDay(today), -n)), due = leaves.filter((t) => t.due.slice(0, 10) === day);
    days.push({ day, total: due.length, done: due.filter((t) => t.done).length, failed: due.filter((t) => t.skipped).length });
  }
  // The server sends every day with a finished task, so the streak is not cut by the 60-day task window.
  const active = new Set([...(state.data.done_days || []), ...leaves.filter((t) => t.done).map(doneDay)]);
  let streak = 0;
  for (let d = active.has(today) ? parseDay(today) : plus(parseDay(today), -1); active.has(iso(d)); d = plus(d, -1)) streak += 1;
  const week = days.slice(-7), total = week.reduce((a, d) => a + d.total, 0), done = week.reduce((a, d) => a + d.done, 0);
  const important = leaves.filter((t) => t.done && t.priority).sort((a, b) => doneDay(b).localeCompare(doneDay(a))).slice(0, 5);
  const peak = Math.max(1, ...days.map((d) => d.total));
  const bars = days.map((d) => `<div class="col" title="${esc(fmt(parseDay(d.day), { day: 'numeric', month: 'short' }))}: ${d.done} из ${d.total}">
      <span class="stack-bar" style="height:${Math.round(d.total / peak * 100)}%"><i style="height:${d.total ? Math.round(d.done / d.total * 100) : 0}%"></i></span>
      <small>${parseDay(d.day).getDate()}</small></div>`).join('');
  return `
    <div class="stats section">
      <div class="stat"><b>${total ? Math.round(done / total * 100) : 0}%</b><span>сделано за неделю</span></div>
      <div class="stat"><b>${streak}</b><span>дней подряд</span></div>
      <div class="stat ${week.some((d) => d.failed) ? 'alert' : ''}"><b>${week.reduce((a, d) => a + d.failed, 0)}</b><span>не сделано</span></div>
    </div>
    <section class="card section"><div class="section-head"><h2>14 дней</h2><span class="meta">высота — задачи, заливка — сделано</span></div>
      <div class="columns" aria-label="Выполнение задач по дням">${bars}</div></section>
    <section class="section"><div class="section-head"><h2>Важное сделано</h2></div>
      ${important.length ? `<div class="tasks">${important.map((t) => `<div class="task"><span class="flag">${icon('flame', 16)}</span>
        <div class="body"><div class="title">${esc(t.title)}</div><div class="meta">${esc(humanDay(doneDay(t), today))}</div></div></div>`).join('')}</div>`
        : empty('Пока пусто', 'Отмеченные важными задачи появятся здесь, когда будут сделаны.')}</section>`;
}

on('click', 'tasks-mode', (b) => { mode = b.dataset.mode; render(); });
on('submit', 'quick-task', async (form) => {
  const button = form.querySelector('button');
  if (button.disabled) return;
  button.disabled = true;
  try {
    const { task } = await api('quick-task', { text: form.text.value });
    haptic('success');
    toast(`Добавлено: ${task.title} · ${humanDay(task.due.slice(0, 10))}${task.all_day ? '' : ', ' + task.due.slice(11, 16)}`);
    form.text.value = '';
    await load();
  } finally { button.disabled = false; }
});

on('click', 'task-filter', (b) => { state.taskFilter = b.dataset.filter; render(); });
