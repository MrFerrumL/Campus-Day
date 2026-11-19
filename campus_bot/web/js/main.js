// Entry point: draws the shell, wires navigation and keeps the data fresh.
import { api, applyTheme, bindSheet, inTelegram, load, on, render, setRenderer, sheetIsOpen, state, switchTab, tg, toast, useTelegramSdk } from './core.js';
import { openAddChooser, openEditor } from './editor.js';
import { brandMark, icon } from './icons.js';
import { $, esc } from './util.js';
import * as calendar from './views/calendar.js';
import * as more from './views/more.js';
import * as students from './views/students.js';
import * as tasks from './views/tasks.js';
import * as todayView from './views/today.js';
import * as gym from './views/gym.js';
import {loadAssistant} from './assistant.js';

const TABS = [
  ['today', 'Сегодня', 'sun', todayView],
  ['calendar', 'Календарь', 'calendar', calendar],
  ['tasks', 'Задачи', 'tasks', tasks],
  ['students', 'Ученики', 'people', students],
  ['gym', 'Зал', 'dumbbell', gym],
  ['more', 'Ещё', 'more', more],
];
const FAB = { today: ['task', 'event', 'rule'], calendar: ['event', 'task', 'rule'], tasks: 'task', more: ['hack', 'rule'] };

function shell() {
  $('#brand').innerHTML = `день${brandMark(17)}`;
  $('#refresh').innerHTML = icon('refresh', 20);
  $('#fab').innerHTML = icon('plus', 26);
  $('#nav').innerHTML = TABS.map(([id, label, glyph]) => `<button type="button" data-action="tab" data-tab="${id}">
    <span class="pill">${icon(glyph, 22)}</span>${label}</button>`).join('');
}

function draw() {
  const view = TABS.find(([id]) => id === state.tab)[3];
  const group = state.data?.group;
  $('#group').textContent = group || '';
  $('#group').hidden = !group;
  $('#refresh').classList.toggle('spin', state.loading);
  $('#fab').hidden = !FAB[state.tab];
  for (const button of document.querySelectorAll('#nav [data-tab]')) {
    if (button.dataset.tab === state.tab) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (state.error && !state.data) {
    $('#fab').hidden = true;
    $('#view').innerHTML = state.authError && !inTelegram ? signInHelp() : loadError();
    return;
  }
  const status = state.status && state.tab !== 'students'
    ? `<p class="status-line ${state.error ? 'error' : ''}" role="status">${esc(state.status)}</p>` : '';
  // Keep the focused field (search) and its caret across a re-render.
  const active = document.activeElement?.dataset?.input;
  const name = active ? document.activeElement.name : '';
  let caret = null;
  try { caret = active ? document.activeElement.selectionStart : null; } catch { /* number fields have no caret */ }
  const scroll = window.scrollY;
  $('#view').innerHTML = status + view.view();
  if (state.tab === 'gym') gym.afterRender();
  window.scrollTo(0, scroll);
  if (active) {
    // Several fields can share a handler (workout sets), so the name picks the exact one.
    const field = document.querySelector(`#view [data-input="${active}"]${name ? `[name="${CSS.escape(name)}"]` : ''}`);
    if (field) {
      field.focus({ preventScroll: true });
      try { if (caret != null) field.setSelectionRange(caret, caret); } catch { /* not a text field */ }
    }
  }
}

function signInHelp() {
  return `<div class="page-head"><h1>Вход в календарь</h1><p>${esc(state.status)}</p></div>
    <div class="card stack">
      <div class="row">${icon('tasks', 22)}<span>Откройте бота в Telegram и отправьте команду <b>/web</b>.</span></div>
      <div class="row">${icon('link', 22)}<span>Нажмите «Открыть в браузере» — ссылка одноразовая, действует 10 минут.</span></div>
      <div class="row">${icon('check', 22)}<span>Вход сохранится в этом браузере; срок указан в сообщении бота.</span></div>
    </div>
    <p class="muted small-text section">В Telegram приложение открывается кнопкой «Календарь» без всякого входа.</p>`;
}

function loadError() {
  const title = state.authError ? 'Нужно снова открыть календарь' : 'Календарь пока недоступен';
  const hint = state.authError ? '<p>Закройте это окно и снова нажмите «Календарь» в чате с ботом.</p>' : '';
  return `<div class="page-head"><h1>${title}</h1><p>${esc(state.status)}</p></div>
    ${hint}<button type="button" class="btn primary" data-action="refresh" ${state.loading ? 'disabled' : ''}>${state.loading ? 'Загрузка…' : 'Повторить'}</button>`;
}

/** A one-time link from /web: drop the token from the address bar first, then exchange it. */
async function redeemLink() {
  const match = location.hash.match(/(?:^#|&)login=([\w-]{20,100})/);
  if (!match) return;
  history.replaceState(null, '', location.pathname + location.search);
  try {
    await api('login', { token: match[1] });
    toast('Вход выполнен');
  } catch (error) {
    state.status = error.message;
    state.error = true;
  }
}

on('click', 'tab', (button) => { if(button.dataset.tab==='more')loadAssistant(); return switchTab(button.dataset.tab); });
async function refreshCurrent() {
  if (!state.data) await load();
  else if (state.tab === 'students') await students.loadBilling();
  else if (state.tab === 'gym') await gym.loadWellness();
  else await load();
}
on('click', 'refresh', refreshCurrent);
on('click', 'fab', () => {
  const kinds = FAB[state.tab];
  if (typeof kinds === 'string') openEditor(kinds); else openAddChooser(kinds);
});

// Coming back to the app (another tab, the phone screen, the network) refreshes the
// data unless the person is in the middle of editing something.
let resumeTimer;
function resume() {
  if (document.visibilityState === 'hidden') return;
  clearTimeout(resumeTimer);
  resumeTimer = setTimeout(() => {
    if (state.loading || sheetIsOpen() || document.activeElement?.matches('input, textarea, select')) return;
    refreshCurrent();
  }, 300);
}

function start() {
  const params=new URLSearchParams(location.search);
  if(params.get('tab')==='gym'){state.tab='gym';gym.setSection(params.get('section'))}
  function connectTelegram() {
    useTelegramSdk();
    tg?.ready?.();
    tg?.expand?.();
    tg?.onEvent?.('themeChanged', applyTheme);
    tg?.onEvent?.('activated', resume);
    applyTheme();
  }
  window.addEventListener('campus-telegram-sdk', () => {
    const recover = state.authError;
    connectTelegram();
    if (recover) refreshCurrent();
  }, { once: true });
  connectTelegram();
  if (inTelegram) window.campusTelegram.ready();
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', applyTheme);
  shell();
  bindSheet();
  setRenderer(draw);
  document.addEventListener('visibilitychange', resume);
  // The first pageshow comes with the initial load; only a page restored from cache needs a refresh.
  window.addEventListener('pageshow', (event) => { if (event.persisted) resume(); });
  // «Сейчас · ещё N мин» moves on by itself.
  setInterval(() => {
    if (state.tab === 'today' && state.data && !sheetIsOpen() && !document.activeElement?.matches('input, textarea, select')) render();
  }, 60000);
  window.addEventListener('online', resume);
  window.addEventListener('focus', resume);
  render();
  // The assistant status also shows the chat button in the top bar.
redeemLink().then(async()=>{await load();loadAssistant();if(state.tab==='gym')gym.loadWellness()});
  // A link opened in a tab that already shows the app only changes the fragment.
  window.addEventListener('hashchange', () => { if (/login=/.test(location.hash)) redeemLink().then(load); });
  if (!inTelegram && 'serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(() => { /* the app works without it */ });
  }
}
start();
