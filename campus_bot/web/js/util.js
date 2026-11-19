// Small pure helpers shared by the views. Times from the server are ISO strings
// already in Moscow time, so their wall-clock parts are read by slicing.
export const TZ = 'Europe/Moscow';
export const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
export const SOURCE_LABEL = { university: 'Вуз', personal: 'Занятие', plan: 'План', hackathon: 'Хакатон' };

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const ENTITIES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ENTITIES[c]);

export const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
export const parseDay = (value) => new Date(value.slice(0, 10) + 'T12:00:00');
export const plus = (d, days) => { const x = new Date(d); x.setDate(x.getDate() + days); return x; };
export const mondayOf = (d) => plus(d, -((d.getDay() + 6) % 7));
export const fmt = (d, options) => d.toLocaleDateString('ru-RU', options);
export const clock = (value) => value.slice(11, 16);

/** Current Moscow wall-clock time as "YYYY-MM-DDTHH:MM". */
export function nowIso(date = new Date()) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false }).format(date).replace(' ', 'T');
}
export const todayIso = (date = new Date()) => nowIso(date).slice(0, 10);
export const today = () => parseDay(todayIso());

export function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}
export const count = (n, one, few, many) => `${n} ${plural(n, one, few, many)}`;

/** "Сегодня", "Завтра", "Вчера" or "пт, 14 нояб." */
export function humanDay(day, todayDay = todayIso()) {
  const diff = Math.round((parseDay(day) - parseDay(todayDay)) / 86400000);
  if (diff === 0) return 'Сегодня';
  if (diff === 1) return 'Завтра';
  if (diff === -1) return 'Вчера';
  return fmt(parseDay(day), { weekday: 'short', day: 'numeric', month: 'short' });
}

/** Minutes between two "YYYY-MM-DDTHH:MM" strings. */
export const minutesBetween = (a, b) => Math.round((Date.parse(b.slice(0, 16) + ':00Z') - Date.parse(a.slice(0, 16) + ':00Z')) / 60000);

export function duration(minutes) {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} мин`;
  const h = Math.floor(m / 60), rest = m % 60;
  return rest ? `${h} ч ${rest} мин` : `${h} ч`;
}

export const rub = (cents) => cents == null ? '—' : new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB',
  minimumFractionDigits: cents % 100 ? 2 : 0, maximumFractionDigits: cents % 100 ? 2 : 0 }).format(cents / 100);

export function initials(name) {
  return String(name).split(/[\s/]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
}

/** Events touching a day, sorted by start. */
export function eventsOn(events, day) {
  return events.filter((e) => e.start.slice(0, 10) <= day && e.end.slice(0, 19) > day + 'T00:00:00')
    .sort((a, b) => a.start.localeCompare(b.start) || a.title.localeCompare(b.title));
}

/** Pairs of overlapping timed events. */
export function conflicts(events) {
  const timed = events.filter((e) => !e.cancelled && !e.all_day && e.start !== e.end);
  return timed.filter((a, i) => timed.some((b, j) => j !== i && a.start < b.end && b.start < a.end));
}

/** The event running now, else the next one today. */
export function currentOrNext(events, now = nowIso()) {
  const active = events.filter((e) => !e.cancelled && !e.all_day);
  const current = active.find((e) => e.start.slice(0, 16) <= now && now < e.end.slice(0, 16));
  if (current) return { kind: 'now', event: current };
  const next = active.find((e) => e.start.slice(0, 16) > now && e.start.slice(0, 10) === now.slice(0, 10));
  return next ? { kind: 'next', event: next } : null;
}

export const isOpen = (t) => !t.done && !t.skipped;

/** Task buckets for the list: overdue, today, tomorrow, this week, later. */
export function taskBuckets(tasks, now = nowIso()) {
  const day = now.slice(0, 10), tomorrow = iso(plus(parseDay(day), 1)), week = iso(plus(parseDay(day), 7));
  const buckets = { overdue: [], today: [], tomorrow: [], week: [], later: [] };
  for (const t of tasks) {
    const due = t.due.slice(0, 10);
    const late = t.all_day ? due < day : t.due.slice(0, 16) < now;
    if (late) buckets.overdue.push(t);
    else if (due === day) buckets.today.push(t);
    else if (due === tomorrow) buckets.tomorrow.push(t);
    else if (due <= week) buckets.week.push(t);
    else buckets.later.push(t);
  }
  return buckets;
}

/** Tasks ordered as a tree: children right after their parent with a depth. */
export function taskTree(tasks) {
  const ids = new Set(tasks.map((t) => t.id)), children = new Map(), ordered = [];
  for (const t of tasks) {
    const parent = ids.has(t.parent_id) ? t.parent_id : null;
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(t);
  }
  const walk = (parent, depth) => {
    for (const t of children.get(parent) || []) { ordered.push({ ...t, depth }); walk(t.id, depth + 1); }
  };
  walk(null, 0);
  return ordered;
}
