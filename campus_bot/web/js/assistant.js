// The AI assistant: a chat sheet that first shows the planned changes, saves them only
// after «Сохранить» and can undo them; plus the key settings. The API key goes straight
// to our authenticated server, never to Telegram or localStorage.
import { api, closeSheet, haptic, load, on, openSheet, render, sheetIsOpen, toast, updateSheet } from './core.js';
import { icon } from './icons.js';
import { esc } from './util.js';

let info = null;
const chat = { history: [], pending: null, saved: null, busy: false, error: '' };
const EXAMPLES = [
  'Запиши обед: гречка с курицей, 550 ккал',
  'Выпил 500 мл воды',
  'Спал с 23:30 до 7:15, самочувствие 4',
  'Добавь завтра в 18:00 подготовку к коллоквиуму',
  'Сколько я сегодня съел и сколько осталось до цели?',
];

export async function loadAssistant() {
  try {
    info = await api('assistant');
    // A sparkle in the top bar opens the chat from any screen once a key is connected.
    const button = document.getElementById('ai-open');
    if (button) { button.innerHTML = icon('sparkles', 20); button.hidden = !info?.configured; }
    render();
  } catch { /* the calendar works without it */ }
}

export function assistantCard() {
  return `<section class="section"><div class="section-head"><h2>ИИ-помощник</h2><span class="badge">${info?.enabled ? 'Подключён' : info?.configured ? 'Выключен' : 'Нужен API-ключ'}</span></div>
    <div class="card"><p>Пишите обычными словами: записать еду, воду или сон, добавить задачу, перенести срок, спросить, сколько осталось до цели.
      Помощник сначала покажет, что сделает, и сохранит только после вашего «Сохранить».</p>
    ${info?.configured ? `<button type="button" class="btn primary block" data-action="ai-open">${icon('sparkles', 18)}Открыть чат</button>` : ''}
    <p class="meta">${info?.configured ? 'Модель: ' + esc(info.model) + '. В Telegram помощник тоже отвечает на обычные сообщения.' : 'Подключите свой ключ OpenAI API. Доступ и оплата API настраиваются в вашем проекте OpenAI.'}</p>
    <button type="button" class="btn block" data-action="ai-settings">${icon('edit', 18)}${info?.configured ? 'Настроить помощника' : 'Подключить ИИ'}</button></div></section>`;
}

/* ---------- Chat ---------- */
function bubble(m) {
  return `<div class="ai-bubble ${m.role === 'user' ? 'user' : ''}">${esc(m.text)}</div>`;
}

function chatHtml() {
  const pending = chat.pending ? `<div class="ai-plan card"><strong>${esc(chat.pending.message || 'Сделаю так:')}</strong>
      <ul>${chat.pending.preview.map((line) => `<li>${esc(line)}</li>`).join('')}</ul>
      <div class="row"><button type="button" class="btn primary grow" data-action="ai-confirm" ${chat.busy ? 'disabled' : ''}>${icon('check', 18)}Сохранить</button>
        <button type="button" class="btn grow" data-action="ai-cancel" ${chat.busy ? 'disabled' : ''}>Не надо</button></div></div>` : '';
  const saved = chat.saved ? `<div class="ai-saved"><span>${esc(chat.saved.message)}</span>
      <button type="button" class="btn small" data-action="ai-undo" ${chat.busy ? 'disabled' : ''}>${icon('undo', 16)}Отменить</button></div>` : '';
  const empty = !chat.history.length && !chat.pending ? `<div class="ai-examples">${EXAMPLES.map((t) => `<button type="button" data-action="ai-example" data-text="${esc(t)}">${esc(t)}</button>`).join('')}</div>` : '';
  return `<div class="sheet-head"><h2>${icon('sparkles', 20)} Помощник</h2>
      <button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <div class="ai-messages" id="ai-messages">${chat.history.map(bubble).join('')}${pending}${saved}
      ${chat.busy ? '<div class="ai-status" role="status">Думаю… это занимает до минуты</div>' : ''}
      ${chat.error ? `<div class="ai-error" role="alert">${esc(chat.error)}</div>` : ''}${empty}</div>
    <form class="ai-form" data-submit="ai-send"><label class="sr-only" for="ai-text">Сообщение помощнику</label>
      <textarea id="ai-text" name="text" rows="2" maxlength="4000" placeholder="Например: съел творог 200 г, 240 ккал" ${chat.busy ? 'disabled' : ''}></textarea>
      <button class="btn primary" aria-label="Отправить" ${chat.busy ? 'disabled' : ''}>${icon('right', 20)}</button></form>
    ${chat.history.length ? '<button type="button" class="link-btn" data-action="ai-forget">Очистить переписку</button>' : ''}`;
}

function redraw() {
  if (!sheetIsOpen() || !document.getElementById('ai-messages')) return;
  const typed = document.getElementById('ai-text')?.value || '';
  updateSheet(chatHtml());
  const area = document.getElementById('ai-text');
  if (area && typed) area.value = typed;
  const list = document.getElementById('ai-messages');
  if (list) list.scrollTop = list.scrollHeight;
}

async function openChat() {
  if (!info?.configured) return openSettings();
  chat.error = '';
  openSheet(chatHtml());
  redraw();
  try {
    const data = await api('assistant-chat', {});
    chat.history = data.history || [];
    redraw();
  } catch (error) { chat.error = error.message; redraw(); }
}

async function step(fn) {
  if (chat.busy) return;
  chat.busy = true;
  chat.error = '';
  redraw();
  try { await fn(); } catch (error) { chat.error = error.message || 'Не получилось. Ничего не изменено.'; } finally {
    chat.busy = false;
    redraw();
  }
}

async function send(text) {
  const clean = text.trim();
  if (!clean) return;
  chat.saved = null;
  chat.pending = null;
  chat.history = [...chat.history, { role: 'user', text: clean }];
  await step(async () => {
    const result = await api('assistant-ask', { text: clean });
    // A proposal is not in the saved history yet: keep the question on screen next to it.
    if (result.pending) chat.pending = { id: result.pending, preview: result.preview, message: result.message };
    else chat.history = result.history || [...chat.history, { role: 'assistant', text: result.message }];
  });
}

on('click', 'ai-open', () => openChat());
on('click', 'ai-example', (b) => { const area = document.getElementById('ai-text'); if (area) { area.value = b.dataset.text; area.focus(); } });
on('submit', 'ai-send', async (form) => {
  const text = form.elements.text.value;
  form.elements.text.value = '';
  await send(text);
});
on('click', 'ai-confirm', () => step(async () => {
  const result = await api('assistant-confirm', { pending: chat.pending.id });
  chat.pending = null;
  chat.history = result.history || chat.history;
  chat.saved = result.run ? { run: result.run, message: 'Сохранено' } : null;
  haptic('success');
  await load();
}));
on('click', 'ai-cancel', () => step(async () => {
  const result = await api('assistant-cancel', { pending: chat.pending.id });
  chat.pending = null;
  chat.history = result.history || chat.history;
}));
on('click', 'ai-undo', () => step(async () => {
  const result = await api('assistant-undo', { run: chat.saved.run });
  chat.saved = null;
  chat.history = [...chat.history, { role: 'assistant', text: result.message }];
  toast(result.message);
  await load();
}));
on('click', 'ai-forget', () => step(async () => {
  await api('assistant-forget', {});
  chat.history = [];
  chat.pending = null;
  chat.saved = null;
}));

/* ---------- Settings ---------- */
function openSettings() {
  const models = info?.models || ['gpt-5-mini', 'gpt-4.1-mini'];
  openSheet(`<div class="sheet-head"><h2>Подключение ИИ</h2><button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <form class="form" data-submit="ai-config"><label class="field">Модель<select name="model">${models.map((m) => `<option value="${esc(m)}" ${m === info?.model ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></label>
    <label class="field">${info?.configured ? 'Новый API-ключ · пусто, чтобы сохранить текущий' : 'API-ключ OpenAI'}<input type="password" name="api_key" autocomplete="new-password" autocapitalize="off" spellcheck="false" placeholder="sk-…" ${info?.configured ? '' : 'required'}></label>
    <label class="switch"><span>Отвечать на обычные сообщения в Telegram</span><input type="checkbox" name="enabled" ${info?.enabled || !info?.configured ? 'checked' : ''}></label>
    <p class="meta">Ключ хранится в закрытом файле на сервере и никогда не показывается после сохранения. Помощнику передаются ваши задачи, занятые интервалы и сегодняшний дневник питания и сна; платежи, ученики и письма не передаются.</p>
    <p class="meta"><a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener">Создать API-ключ в OpenAI ↗</a></p>
    <button class="btn primary block">Сохранить и проверить</button>${info?.configured ? '<button type="button" class="btn danger block" data-action="ai-disconnect">Удалить сохранённый ключ и отключить</button>' : ''}</form>`);
}
on('click', 'ai-settings', () => openSettings());
on('submit', 'ai-config', async (f) => {
  const b = f.querySelector('button.btn.primary');
  b.disabled = true;
  try {
    info = await api('assistant-config', { model: f.model.value, api_key: f.api_key.value, enabled: f.enabled.checked });
    f.api_key.value = '';
    closeSheet();
    render();
    toast(info.configured ? 'ИИ подключён. Откройте чат или напишите боту.' : 'Настройки сохранены');
  } finally { b.disabled = false; }
});
on('click', 'ai-disconnect', async () => {
  info = await api('assistant-config', { remove: true });
  closeSheet();
  render();
  toast('Сохранённый ключ удалён, помощник отключён');
});
