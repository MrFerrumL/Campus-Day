// «Ещё»: hackathons with their stages, recurring lessons and notification settings.
import { api, ask, ensureLoaded, inTelegram, on, onEnter, render, save, state, toast } from '../core.js';
import { openEditor, openHack, stageById } from '../editor.js';
import { icon } from '../icons.js';
import { empty, skeleton } from '../parts.js';
import { WEEKDAYS, esc } from '../util.js';
import {assistantCard} from '../assistant.js';

const REPEAT = { once: 'Один раз', all: 'Каждую неделю', daily: 'Каждый день', weekdays: 'По будням', a: 'Недели A', b: 'Недели B' };

function stage(s, next) {
  const late = !s.done && s.countdown === 'срок прошёл';
  return `<li class="stage ${s.done ? 'done' : ''} ${late ? 'late' : ''}">
    <button type="button" class="check" data-action="stage-check" data-id="${s.id}" aria-pressed="${!!s.done}" aria-label="Отметить этап">${icon('check', 18)}</button>
    <div class="body"><strong>${next?.id === s.id ? '→ ' : ''}${esc(s.title)}</strong>
      <small>${s.kind === 'task' ? 'Дедлайн' : 'Событие'} · ${esc(s.when)}${s.done ? '' : ' · ' + esc(s.countdown)}</small></div>
    <button type="button" class="icon-btn small ghost" data-action="edit-stage" data-id="${s.id}" aria-label="Изменить этап">${icon('edit', 18)}</button>
  </li>`;
}

function hackCard(h) {
  const n = h.next, total = h.stages.length, pct = total ? Math.round(h.done_count / total * 100) : 0;
  const statuses = Object.entries(state.data.statuses).map(([k, v]) => `<option value="${esc(k)}" ${k === h.status ? 'selected' : ''}>${esc(v)}</option>`).join('');
  return `<article class="card hack src-hackathon">
    <span class="badge">${icon('trophy', 12)} ${esc(h.kind_label)}${h.organizer ? ' · ' + esc(h.organizer) : ''}</span>
    <h3>${esc(h.title)}</h3>
    <div class="row" style="flex-wrap:wrap"><select class="select" data-change="hack-status" data-id="${esc(h.id)}" aria-label="Статус участия">${statuses}</select>
      ${h.role ? `<span class="badge">${esc(h.role)}</span>` : ''}</div>
    ${h.summary ? `<p class="summary">${esc(h.summary)}</p>` : ''}
    ${n && !h.closed ? `<div class="next ${n.countdown === 'срок прошёл' ? 'late' : ''}"><small>${n.kind === 'task' ? 'Ближайший дедлайн' : 'Ближайшее событие'}</small>
      <strong>${esc(n.title)}</strong><span class="small-text">${esc(n.when)} · ${esc(n.countdown)}</span></div>` : ''}
    <div class="section"><div class="progress" aria-hidden="true"><i style="width:${pct}%"></i></div>
      <span class="small-text muted">${h.done_count} из ${total} этапов</span></div>
    <details data-remember="stages-${esc(h.id)}" ${state.openDetails.has('stages-' + h.id) ? 'open' : ''}><summary>Этапы · ${total}</summary><ol class="stages">${h.stages.map((s) => stage(s, n)).join('')}</ol></details>
    ${h.links.length ? `<div class="links">${h.links.map((l) => (/^https?:\/\//i.test(l.url)
      ? `<a href="${esc(l.url)}" data-action="open-link" data-url="${esc(l.url)}" rel="noopener">${esc(l.title)} ${icon('link', 12)}</a>`
      : `<span class="badge">${esc(l.title)}</span>`)).join('')}</div>` : ''}
    <div class="row section"><button type="button" class="btn small" data-action="new-stage" data-id="${esc(h.id)}">${icon('plus', 16)}Этап</button>
      <button type="button" class="btn small" data-action="edit-hack" data-id="${esc(h.id)}">${icon('edit', 16)}Изменить</button></div>
  </article>`;
}

function ruleRow(r) {
  const days = ['all', 'a', 'b'].includes(r.cycle) ? r.weekdays.map((d) => WEEKDAYS[d]).join(', ') + ' · ' : '';
  const once = r.cycle === 'once' ? ' · ' + (r.date || '') : '';
  const limits = r.cycle !== 'once' ? (r.start_date ? ' · с ' + r.start_date : '') + (r.end_date ? ' · до ' + r.end_date : '') : '';
  return `<div class="rule"><div class="grow"><div class="title">${esc(r.title)}</div>
    <div class="meta">${esc(REPEAT[r.cycle] || r.cycle)}${esc(once)} · ${esc(days)}${esc(r.time)} · ${r.duration_minutes} мин${esc(limits)}</div></div>
    <button type="button" class="icon-btn small ghost" data-action="edit-rule" data-id="${esc(r.id)}" aria-label="Изменить «${esc(r.title)}»">${icon('edit', 18)}</button></div>`;
}

function settings(d) {
  const m = d.mail;
  const mailHint = !m.configured ? 'Почта не подключена: адрес и пароль приложения задаются в .env на сервере, подробнее — /mail в боте.'
    : m.error || `${m.address} · письма остаются непрочитанными${m.checked ? ' · проверено ' + m.checked.slice(11, 16) : ''}`;
  return `<form class="card form" data-submit="save-settings">
    <label class="switch">${icon('bell', 18)}<span class="grow">Уведомления</span><input type="checkbox" name="notifications" ${d.settings.notifications ? 'checked' : ''}></label>
    <label class="switch">${icon('mail', 18)}<span class="grow">Важные письма в чат</span><input type="checkbox" name="mail" ${m.configured && m.enabled ? 'checked' : ''} ${m.configured ? '' : 'disabled'}></label>
    <p class="muted small-text">${esc(mailHint)}</p>
    <label class="field">План дня — время через запятую<input name="digest" value="${esc(d.settings.digest_times.join(', '))}" placeholder="07:30, 13:00"></label>
    <label class="field">Погода — время через запятую<input name="weather" value="${esc(d.settings.weather_times.join(', '))}" placeholder="08:00"></label>
    <button class="btn primary block">Сохранить настройки</button>
    <p class="muted small-text">Время берётся из настроек сервера. Остальное настраивается в боте: /settings.</p>
  </form>`;
}

/* ---------- Browser sign-in: devices ---------- */
/** After signing out, nothing of the app stays in this browser: cached shell and the worker go too. */
async function forgetShell() {
  try {
    for (const key of await caches.keys()) await caches.delete(key);
    for (const registration of await navigator.serviceWorker.getRegistrations()) await registration.unregister();
  } catch { /* storage not available */ }
}
let devices = null;
async function loadDevices(body = {}, action = 'web-sessions') {
  const result = await api(action, body);
  devices = result.sessions;
  render();
  return result;
}
let study = null;
const loadStudy = () => api('study').then((result) => { study = result; render(); }).catch(() => { study = false; render(); });
onEnter('more', () => { ensureLoaded(); loadStudy(); loadDevices().catch(() => { devices = []; render(); }); });

function studyCard() {
  if (study === null) return '<div class="card"><p class="muted small-text">Загружаем учёбу…</p></div>';
  if (study === false) return '<div class="card"><p class="muted small-text">Не удалось загрузить. Нажмите обновить.</p></div>';
  const since = new Date(study.since + 'T12:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
  const subjects = study.subjects.map((s) => {
    const marked = s.present + s.absent, pct = marked ? Math.round(s.present / marked * 100) : null;
    return `<div class="rule"><div class="grow"><div class="title">${esc(s.subject)}</div>
      <div class="meta">был ${Number(s.present)} · не был ${Number(s.absent)}${s.unmarked ? ` · без отметки ${Number(s.unmarked)}` : ''}</div></div>
      <span class="badge ${s.absent >= 3 ? 'src-hackathon' : 'src-personal'}">${pct == null ? '—' : pct + '%'}</span></div>`;
  }).join('');
  const coming = study.upcoming.map((u) => `<div class="rule"><div class="grow"><div class="title">${esc(u.title)}</div>
      <div class="meta">${esc(new Date(u.start).toLocaleString('ru-RU', { weekday: 'short', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' }))}${u.details ? ' · ' + esc(u.details) : ''}</div></div></div>`).join('');
  return `
    <div class="card" style="padding:0"><div style="padding:12px 14px 0" class="section-head"><h2>Посещаемость с ${esc(since)}</h2></div>
      ${subjects || '<p class="muted" style="padding:0 14px 14px">Отметок пока нет: отмечайте пары в календаре.</p>'}</div>
    ${coming ? `<div class="card section" style="padding:0"><div style="padding:12px 14px 0" class="section-head"><h2>Коллоквиумы и объявления</h2></div>${coming}</div>` : ''}
    <form class="card form section" data-submit="save-study">
      <div class="form-row">
        ${study.public_mode
          ? `<label class="field">ID группы Cube<input name="group_id" type="number" min="0" max="999999999" value="${study.group_id || 0}" required></label>
             <label class="field">Название группы<input name="group_name" maxlength="80" value="${esc(study.group)}"></label>`
          : `<label class="field">Подгруппа<select name="subgroup">${[1, 2].map((n) => `<option value="${n}" ${study.subgroup === n ? 'selected' : ''}>Группа ${n}</option>`).join('')}</select></label>`}
        <label class="field">Неделя A начинается<input type="date" name="anchor" value="${esc(study.anchor)}" required></label>
      </div>
      <button class="btn primary block">Сохранить</button>
      <p class="muted small-text">${study.public_mode?'ID 0 отключает загрузку из Cube. ':''}Дата начала недели A — любой понедельник недели A.</p>
    </form>`;
}
on('submit', 'save-study', async (form) => {
  const group = study.public_mode
    ? { group_id: form.group_id.value, group_name: form.group_name.value }
    : { subgroup: form.subgroup.value };
  await save('settings', { ...group, cycle_anchor: form.anchor.value }, 'Учёба сохранена');
  await loadStudy();
});

function deviceName(agent) {
  const a = String(agent);
  const browser = /YaBrowser/.test(a) ? 'Яндекс Браузер' : /Edg\//.test(a) ? 'Edge' : /OPR\//.test(a) ? 'Opera'
    : /Firefox\//.test(a) ? 'Firefox' : /Chrome\//.test(a) ? 'Chrome' : /Safari\//.test(a) ? 'Safari' : 'Браузер';
  const system = /iPhone|iPad/.test(a) ? 'iPhone' : /Android/.test(a) ? 'Android' : /Windows/.test(a) ? 'Windows'
    : /Mac OS X/.test(a) ? 'Mac' : /Linux/.test(a) ? 'Linux' : '';
  return system ? `${browser} · ${system}` : browser;
}
const when = (seconds) => new Date(seconds * 1000).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' });

function devicesCard() {
  const help = '<p class="muted small-text">Ссылку для входа с телефона или компьютера присылает бот по команде /web. Срок входа указан в сообщении бота.</p>';
  if (devices === null) return `<div class="card">${help}<p class="muted small-text">Загружаем устройства…</p></div>`;
  const rows = devices.map((d) => `<div class="rule"><div class="grow"><div class="title">${esc(deviceName(d.agent))}${d.current ? ' <span class="badge src-personal">это устройство</span>' : ''}</div>
      <div class="meta">вход ${esc(when(d.created))} · активность ${esc(when(d.seen))}</div></div>
      <button type="button" class="icon-btn small ghost" data-action="device-revoke" data-id="${esc(d.id)}" aria-label="Выйти на устройстве ${esc(deviceName(d.agent))}">${icon('x', 18)}</button></div>`).join('');
  return `<div class="card" style="padding:0">${rows || '<p class="muted" style="padding:14px 14px 0">Входов из браузера нет.</p>'}
    <div style="padding:0 14px 14px">${help}
      ${devices.length ? '<button type="button" class="btn danger block" data-action="device-revoke-all">Выйти на всех устройствах</button>' : ''}</div></div>`;
}

export function view() {
  const d = state.data;
  if (!d) return `<div class="page-head"><h1>Ещё</h1></div>${skeleton(3)}`;
  const open = d.hackathons.filter((h) => !h.closed), closed = d.hackathons.filter((h) => h.closed);
  return `
    <div class="page-head"><h1>Ещё</h1><p>Учёба, хакатоны, занятия и настройки</p></div>
    ${assistantCard()}
    <section aria-labelledby="study-title">
      <div class="section-head"><h2 id="study-title">Учёба</h2></div>
      ${studyCard()}
    </section>
    <section class="section" aria-labelledby="hacks-title">
      <div class="section-head"><h2 id="hacks-title">Хакатоны</h2>
        <button type="button" class="btn small" data-action="new-hack">${icon('plus', 16)}Добавить</button></div>
      ${d.clashes.length ? `<div class="notice danger">${icon('alert', 18)}<span>${d.clashes.map(esc).join('<br>')}</span></div>` : ''}
      <div class="stack">${open.map(hackCard).join('') || empty('Здесь будут хакатоны', 'Этапы сами появятся в календаре и задачах.')}</div>
      ${closed.length ? `<details class="section" data-remember="closed-hacks" ${state.openDetails.has('closed-hacks') ? 'open' : ''}><summary>Завершённые и отменённые · ${closed.length}</summary><div class="stack">${closed.map(hackCard).join('')}</div></details>` : ''}
    </section>
    <section class="section" aria-labelledby="rules-title">
      <div class="section-head"><h2 id="rules-title">Мои занятия</h2>
        <button type="button" class="btn small" data-action="new-rule">${icon('plus', 16)}Добавить</button></div>
      <div class="card" style="padding:0">${d.rules.map(ruleRow).join('') || '<p class="muted" style="padding:14px">Пока пусто.</p>'}</div>
      <p class="muted small-text">Разовые занятия и повторения. Недели A и B чередуются, точка отсчёта — /set anchor в боте.</p>
    </section>
    ${d.public_mode ? '' : `<section class="section" aria-labelledby="devices-title">
      <div class="section-head"><h2 id="devices-title">Вход из браузера</h2></div>
      ${devicesCard()}
    </section>`}
    <section class="section" aria-labelledby="settings-title">
      <div class="section-head"><h2 id="settings-title">Настройки</h2></div>
      ${settings(d)}
    </section>`;
}

on('click', 'device-revoke', async (b) => {
  const device = devices?.find((d) => d.id === b.dataset.id);
  if (!await ask(device?.current ? 'Выйти в этом браузере?' : 'Выйти на этом устройстве?')) return;
  if (device?.current) { await api('web-logout', {}); await forgetShell(); location.reload(); return; }
  await loadDevices({ revoke: b.dataset.id });
  toast('Устройство отключено');
});
on('click', 'device-revoke-all', async () => {
  if (!await ask('Выйти из календаря во всех браузерах? В Telegram приложение продолжит работать.')) return;
  await loadDevices({}, 'web-logout-all');
  toast('Выход выполнен на всех устройствах');
  if (!inTelegram) { await forgetShell(); location.reload(); }
});

on('click', 'new-hack', () => openHack());
on('click', 'edit-hack', (b) => openHack(state.data.hackathons.find((h) => h.id === b.dataset.id)));
on('click', 'new-stage', (b) => openEditor('stage', null, b.dataset.id));
on('click', 'edit-stage', (b) => openEditor('stage', stageById(b.dataset.id)));
on('click', 'stage-check', async (b) => {
  const s = stageById(b.dataset.id);
  b.disabled = true;
  await save('stage-check', { id: s.id, done: !s.done }, s.done ? 'Этап снова открыт' : 'Этап выполнен');
});
on('change', 'hack-status', async (select) => {
  select.disabled = true;
  await save('hack-status', { id: select.dataset.id, status: select.value }, 'Статус обновлён');
});
on('click', 'new-rule', () => openEditor('rule'));
on('click', 'edit-rule', (b) => openEditor('rule', state.data.rules.find((r) => r.id === b.dataset.id)));
on('submit', 'save-settings', async (form) => {
  const times = (value) => value.split(',').map((x) => x.trim()).filter(Boolean);
  await save('settings', { notifications: form.notifications.checked,
    ...(state.data.mail.configured ? { mail_enabled: form.mail.checked } : {}),
    digest_times: times(form.digest.value), weather_times: times(form.weather.value) }, 'Настройки сохранены');
});
