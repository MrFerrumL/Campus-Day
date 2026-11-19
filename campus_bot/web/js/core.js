// Application state, server access and the pieces every view shares:
// Telegram integration, loading, toasts, the bottom sheet and event dispatch.
import { $, iso, mondayOf, plus, today } from './util.js';

export const tg = window.Telegram?.WebApp ?? null;
/** Opened from the bot inside Telegram (signed init data), not in an ordinary browser. */
export const inTelegram = !!tg?.initData;

export const state = {
  tab: 'today',
  mode: 'week',              // calendar: day | week | month
  selected: today(),         // calendar day in focus
  filter: 'all',             // calendar source filter
  taskFilter: 'active',
  openDetails: new Set(),    // <details data-remember> kept open across re-renders
  data: null,
  loadedRange: '',
  status: '',
  error: false,
  loading: false,
  billing: null,
  billingMonth: iso(today()).slice(0, 7),
  billingQuery: '',
  billingOnlyDue: false,
  billingStatus: '',
};

export const api = window.createCampusTransport({ initData: () => tg?.initData || '' });

/* ---------- Event dispatch: elements carry data-action / data-change / data-submit ---------- */
const handlers = { click: {}, change: {}, submit: {}, input: {} };
export function on(type, name, fn) { handlers[type][name] = fn; }

function dispatch(type, attribute) {
  document.addEventListener(type, async (event) => {
    const target = event.target.closest(`[${attribute}]`);
    if (!target) return;
    const fn = handlers[type][target.getAttribute(attribute)];
    if (!fn) return;
    if (type === 'submit') event.preventDefault();
    try { await fn(target, event); } catch (error) {
      toast(error.message || 'Не получилось');
      haptic('error');
      render(); // brings back controls a failed action left disabled
    }
  });
}
dispatch('click', 'data-action');
dispatch('change', 'data-change');
dispatch('input', 'data-input');
dispatch('submit', 'data-submit');
document.addEventListener('toggle', (event) => {
  const key = event.target.dataset?.remember;
  if (!key) return;
  if (event.target.open) state.openDetails.add(key); else state.openDetails.delete(key);
}, true);

/* ---------- Rendering is provided by main.js ---------- */
let renderer = () => {};
export function setRenderer(fn) { renderer = fn; }
export function render() { renderer(); }

/* ---------- Loading ---------- */
export function rangeFor(tab = state.tab) {
  if (tab === 'calendar' && state.mode === 'month') {
    const first = new Date(state.selected.getFullYear(), state.selected.getMonth(), 1, 12);
    const start = mondayOf(first);
    return [start, plus(start, 41)];
  }
  const anchor = tab === 'calendar' ? state.selected : today();
  const start = mondayOf(anchor);
  return [start, plus(start, 6)];
}
const rangeKey = ([a, b]) => `${iso(a)}..${iso(b)}`;

let requestId = 0;
export async function load() {
  const id = ++requestId, range = rangeFor();
  state.loading = true;
  render();
  try {
    const result = await api(`state?from=${iso(range[0])}&to=${iso(range[1])}`);
    if (id !== requestId) return;
    // The person switched to a screen that needs other dates meanwhile: fetch those instead.
    if (rangeKey(rangeFor()) !== rangeKey(range)) { setTimeout(load); return; }
    state.data = result;
    state.loadedRange = rangeKey(range);
    state.status = (result.notes || []).join(' ');
    state.error = false;
  } catch (error) {
    if (id !== requestId) return;
    state.status = error.message;
    state.error = true;
  } finally {
    if (id === requestId) { state.loading = false; render(); }
  }
}
export function ensureLoaded() {
  if (!state.data || state.loadedRange !== rangeKey(rangeFor())) return load();
  render();
  return Promise.resolve();
}

/* ---------- Tabs: a view may load its own data when it opens ---------- */
const enterHooks = {};
export function onEnter(tab, fn) { enterHooks[tab] = fn; }
export function switchTab(tab) {
  state.tab = tab;
  window.scrollTo(0, 0);
  return (enterHooks[tab] || ensureLoaded)();
}

/** Save through the API, confirm with a toast and reload the calendar. */
export async function save(action, body, message = 'Сохранено') {
  await api(action, body);
  haptic('success');
  toast(message);
  await load();
}

/* ---------- Feedback ---------- */
let toastTimer;
export function toast(text) {
  const el = $('#toast');
  // An open modal sheet lives in the browser's top layer: the toast must be inside it to be seen.
  const host = $('#sheet').open ? $('#sheet') : document.body;
  if (el.parentElement !== host) host.appendChild(el);
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}
export function haptic(kind = 'success') {
  try {
    if (kind === 'light') tg?.HapticFeedback?.impactOccurred('light');
    else tg?.HapticFeedback?.notificationOccurred(kind);
  } catch { /* older clients */ }
}
/** Telegram's own confirmation popup, the browser's outside Telegram. */
export function ask(message) {
  if (tg?.showConfirm && tg.isVersionAtLeast?.('6.2')) return new Promise((resolve) => tg.showConfirm(message, resolve));
  return Promise.resolve(window.confirm(message));
}
export function openLink(url) {
  if (!/^https?:\/\//.test(url)) return;
  if (tg?.openLink) tg.openLink(url); else window.open(url, '_blank', 'noopener');
}

/* ---------- Bottom sheet with Telegram's back button ---------- */
let sheetClose = null, backBound = false;
function onBack() { closeSheet(); }
export function openSheet(html, { onClose } = {}) {
  const dialog = $('#sheet');
  $('#sheet-body').innerHTML = html;
  sheetClose = onClose || null;
  dialog.setAttribute('aria-label', $('#sheet-body h2')?.textContent || 'Окно');
  if (!dialog.open) dialog.showModal();
  if (!backBound) {
    try { tg?.BackButton?.show(); tg?.BackButton?.onClick(onBack); backBound = true; } catch { /* not in Telegram */ }
  }
  const first = dialog.querySelector('[autofocus]');
  if (first) first.focus();
}
export function updateSheet(html) { $('#sheet-body').innerHTML = html; }
export function closeSheet() {
  const dialog = $('#sheet');
  if (dialog.open) dialog.close();
}
export function sheetIsOpen() { return $('#sheet').open; }
export function bindSheet() {
  const dialog = $('#sheet');
  dialog.addEventListener('close', () => {
    document.body.appendChild($('#toast'));
    try { tg?.BackButton?.offClick(onBack); tg?.BackButton?.hide(); } catch { /* not in Telegram */ }
    backBound = false;
    const fn = sheetClose; sheetClose = null;
    if (fn) fn();
  });
  // Tap on the dimmed backdrop closes the sheet.
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
}
on('click', 'close-sheet', () => closeSheet());

/* ---------- Theme: Telegram's colour scheme, else the system's ---------- */
export function applyTheme() {
  const media = window.matchMedia?.('(prefers-color-scheme: dark)');
  const dark = tg?.colorScheme ? tg.colorScheme === 'dark' : !!media?.matches;
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  try { tg?.setHeaderColor?.(bg); tg?.setBackgroundColor?.(bg); tg?.setBottomBarColor?.(bg); } catch { /* old clients */ }
}
