// «Ученики»: what each pupil owes this month. Reollity is only read; prices for
// future lessons can be set here and stay in the bot.
import { api, ask, closeSheet, ensureLoaded, on, onEnter, openSheet, render, state, toast, updateSheet } from '../core.js';
import { icon } from '../icons.js';
import { empty, skeleton } from '../parts.js';
import { count, esc, fmt, initials, parseDay, rub } from '../util.js';

let request = 0, poll = null, openId = '', mode = 'pay';
const monthLabel = (month) => {
  const text = fmt(parseDay(month + '-01'), { month: 'long', year: 'numeric' });
  return text[0].toUpperCase() + text.slice(1);
};
const shortDay = (day) => fmt(parseDay(day), { day: 'numeric', month: 'short' });

export async function loadBilling() {
  const id = ++request;
  state.billingStatus = 'Загружаем расчёт…';
  render();
  try {
    const result = await api('billing?month=' + state.billingMonth);
    if (id !== request) return;
    state.billing = result;
    state.billingStatus = '';
    if (openId) refreshDetail();
  } catch (error) {
    if (id === request) state.billingStatus = error.message;
  }
  if (id === request) render();
}
onEnter('students', () => { ensureLoaded(); return loadBilling(); });

function syncLine(b) {
  const sync = b.sync || {};
  const when = sync.fetched ? 'Сверено ' + new Date(sync.fetched).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Moscow' })
    : 'Сверки с Reollity ещё не было';
  return `${when}${sync.error ? ' · ' + sync.error : ''}${b.refresh_requested ? ' · обновление запрошено' : ''}`;
}

function personRow(s) {
  const sub = [count(s.count, 'занятие', 'занятия', 'занятий')];
  if (s.debt) sub.push('долг ' + rub(s.debt));
  if (!s.linked) sub.push('нет сверки');
  const amount = s.due == null ? '<span class="amount muted">—</span>'
    : s.due > 0 ? `<span class="amount due">${esc(rub(s.due))}</span>` : `<span class="amount clear">${icon('check', 14)} оплачено</span>`;
  return `<button type="button" class="person" data-action="open-student" data-id="${esc(s.id)}">
    <span class="avatar" aria-hidden="true">${esc(initials(s.name))}</span>
    <span class="grow"><span class="name">${esc(s.name)}</span><br><span class="sub">${esc(sub.join(' · '))}</span></span>
    ${amount}</button>`;
}

function peopleHtml(b) {
  const query = state.billingQuery.trim().toLocaleLowerCase('ru');
  const rows = b.students.filter((s) => (!query || s.name.toLocaleLowerCase('ru').includes(query)) && (!state.billingOnlyDue || s.due > 0));
  return rows.map(personRow).join('') || empty('Никого не нашли', 'Измените поиск или фильтр.');
}

export function view() {
  const b = state.billing;
  const head = `<div class="page-head"><h1>${mode==='income'?'Моя зарплата':'Ученики'}</h1><p>${mode==='income'?'Начислено в Reollity, чистые доплаты и прогноз':'Оплата за месяц с учётом долгов и авансов'}</p></div>
    <div class="month-switch">
      <button type="button" class="icon-btn" data-action="billing-month" data-step="-1" aria-label="Предыдущий месяц">${icon('left', 20)}</button>
      <strong>${esc(monthLabel(state.billingMonth))}</strong>
      <button type="button" class="icon-btn" data-action="billing-month" data-step="1" aria-label="Следующий месяц">${icon('right', 20)}</button>
    </div>`;
  const switcher = `<div class="segmented" role="group" aria-label="Что показать">
      <button type="button" data-action="students-mode" data-mode="pay" aria-pressed="${mode === 'pay'}">Оплата</button>
      <button type="button" data-action="students-mode" data-mode="income" aria-pressed="${mode === 'income'}">Зарплата</button></div>`;
  if (b && mode === 'income') return head + switcher + incomeView(b);
  if (!b) return head + (state.billingStatus && !state.billingStatus.startsWith('Загружаем') ? `<p class="status-line error">${esc(state.billingStatus)}</p>` : skeleton(4));
  const dueCount = b.students.filter((s) => s.due > 0).length;
  return `${head}${switcher}
    <div class="hero section">
      <small>К внесению по всем ученикам</small>
      <div class="sum">${esc(rub(b.total_due))}</div>
      <div class="sub">${dueCount ? esc(count(dueCount, 'ученик должен', 'ученика должны', 'учеников должны')) + ' внести оплату'
        : b.unknown === b.students.length ? 'Суммы появятся после сверки с Reollity' : 'Всё оплачено'}${b.unknown && b.unknown < b.students.length ? ` · ${b.unknown} без расчёта` : ''}</div>
      <div class="sync">${icon('refresh', 16)}<span>${esc(syncLine(b))}</span>
        <button type="button" class="btn small" data-action="billing-refresh">Сверить</button></div>
    </div>
    ${state.billingStatus ? `<p class="status-line">${esc(state.billingStatus)}</p>` : ''}
    <div class="section stack">
      <label class="search">${icon('search', 18)}<span class="sr-only">Поиск ученика</span>
        <input type="search" placeholder="Имя или фамилия" value="${esc(state.billingQuery)}" data-input="billing-search"></label>
      <div class="chips"><button type="button" class="chip" data-action="billing-due" aria-pressed="${state.billingOnlyDue}">Только с оплатой <span class="count">${dueCount}</span></button></div>
    </div>
    <div class="people section" id="people">${peopleHtml(b)}</div>
    <p class="muted small-text">Reollity только читается. Сумма = занятия месяца + старый долг − аванс − уже внесённое.</p>`;
}

/* ---------- «Мой доход» ---------- */
function incomeView(b) {
  if(b.salary)return salaryView(b)+`<details class="section"><summary>Календарный расчёт по ученикам · без корректировок и доплат</summary>${incomeView({...b,salary:null})}</details>`;
  const inc = b.income, d = b.defaults || {};
  const peak = Math.max(1, ...inc.weeks.map((w) => w.amount));
  const weeks = inc.weeks.map((w) => `<div class="bar-row"><span>${esc(shortDay(w.start))}</span>
      <span class="bar"><i style="width:${Math.round(w.amount / peak * 100)}%"></i></span><strong>${esc(rub(w.amount))}</strong></div>`).join('');
  const pupils = inc.pupils.map((p) => `<button type="button" class="person" data-action="open-student" data-id="${esc(p.id)}">
      <span class="avatar" aria-hidden="true">${esc(initials(p.name))}</span>
      <span class="grow"><span class="name">${esc(p.name)}</span><br><span class="sub">${esc(count(p.lessons, 'занятие', 'занятия', 'занятий'))} · доля ${Number(p.share)}%</span></span>
      <span class="amount due">${esc(rub(p.income))}</span></button>`).join('');
  return `
    <div class="hero section">
      <small>Ваш доход · ${esc(monthLabel(b.month))}</small>
      <div class="sum">${esc(rub(inc.forecast))}</div>
      <div class="sub">прогноз по календарю, если все занятия пройдут${inc.unknown ? ` · ${inc.unknown} без цены` : ''}</div>
    </div>
    <div class="stats section">
      <div class="stat"><b>${esc(rub(inc.conducted))}</b><span>за проведённые</span></div>
      <div class="stat"><b>${esc(rub(inc.received))}</b><span>ваша часть оплат</span></div>
      <div class="stat"><b>${esc(rub(inc.forecast - inc.conducted))}</b><span>впереди</span></div>
    </div>
    ${weeks ? `<section class="card section"><div class="section-head"><h2>По неделям</h2></div><div class="bars">${weeks}</div></section>` : ''}
    <section class="section"><div class="section-head"><h2>По ученикам</h2></div>
      <div class="people">${pupils || empty('Занятий нет', 'В этом месяце занятий в календаре нет.')}</div></section>
    <form class="card form section" data-submit="billing-defaults">
      <div class="section-head"><h2>По умолчанию</h2></div>
      <div class="form-row">
        <label class="field">Цена занятия, ₽<input name="rate" type="number" min="0" max="1000000" step="0.01" value="${d.rate == null ? '' : d.rate / 100}" required></label>
        <label class="field">Ваша доля, %<input name="share" type="number" min="0" max="100" step="1" value="${Number(d.share ?? 50)}" required></label>
      </div>
      <button class="btn primary block">Сохранить</button>
      <p class="muted small-text">У ученика можно задать свою цену и долю в его карточке. Проведённые занятия считаются по ценам Reollity.</p>
    </form>`;
}

const salaryLessons=n=>esc(count(n,'занятие','занятия','занятий'));
function salaryView(b){
 const s=b.salary,r=s.reported,u=s.upcoming,e=s.extras,p=s.payroll;
 return `<div class="hero section"><small>Ваша зарплата · ${esc(monthLabel(s.month))}</small><div class="sum">${esc(rub(s.forecast))}</div><div class="sub">Прогноз за месяц · ${salaryLessons(s.forecast_count)} с отработками</div><div class="sync">${icon('refresh',16)}<span>${esc(s.refreshed?'Сверено '+new Date(s.refreshed).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'Сверки зарплатного отчёта ещё нет')}</span><button class="btn small" data-action="billing-refresh">Сверить</button></div></div>
 <div class="salary-grid section"><div class="card"><span class="meta">Уже заработано</span><strong>${esc(rub(s.earned))}</strong><small>${salaryLessons(s.conducted_count)}, включая доплаты</small></div><div class="card"><span class="meta">Осталось по графику</span><strong>${esc(rub(u.amount))}</strong><small>${salaryLessons(u.count)} · ${u.participations} ученико-занятий</small></div></div>
 <section class="card section"><div class="section-head"><h2>Из чего складывается</h2></div><div class="line"><span>${s.source==='payroll'?'Зарплатный отчёт Reollity':'Оценка по занятиям'}<small>${salaryLessons(r.count)} · ${r.participations} ученико-занятий</small></span><strong>${esc(rub(r.amount))}</strong></div>
 ${e.items.map(item=>`<div class="line"><span>${esc(item.note)}<small>${salaryLessons(item.count)} · чистая доплата</small></span><strong>+ ${esc(rub(item.amount))}</strong><button class="icon-btn small ghost" data-action="salary-delete-extra" data-id="${esc(item.id)}" aria-label="Удалить доплату">${icon('trash',16)}</button></div>`).join('')}
 <div class="line"><span>Будущие занятия<small>Ваша доля по ставкам учеников</small></span><strong>+ ${esc(rub(u.amount))}</strong></div><p class="muted small-text">Парное занятие считается одним. В сумме учтена оплата каждого ученика.</p>
 ${p?`<details><summary>Корректировки Reollity уже учтены</summary><p class="meta">Общая сумма отчётов: ${esc(rub(p.total_all))}<br>Учтено платформой: ${esc(rub(p.income_counted))}<br>Вычет за переводы (поле отчёта): ${esc(rub(p.bank_transfer_deduction))}<br>Ваша зарплата из отчёта: ${esc(rub(p.salary))}</p><p class="meta">Вычет повторно не применяется.</p></details>`:'<p class="notice danger">Зарплатный отчёт не получен: расчёт по занятиям не учитывает корректировки платформы.</p>'}</section>
 ${s.waiting.count?`<p class="notice danger">Прошедшие без отчёта: ${s.waiting.count} занятий · ${esc(rub(s.waiting.amount))}. Требуют проверки и не включены в итог.</p>`:''}
 ${s.unknown?`<p class="notice danger">У ${s.unknown} будущих ученико-занятий нет цены: прогноз неполный.</p>`:''}
 ${s.counts_mismatch?'<p class="notice danger">Количество оплат в зарплатном отчёте отличается от истории занятий. Сумма взята из самого отчёта.</p>':''}
 ${s.sync_error||s.payroll_error?'<p class="notice danger">Сверка с ошибкой. Показаны последние сохранённые данные.</p>':''}
 <form class="card form section" data-submit="salary-extra" data-reference="${crypto.randomUUID()}"><div class="section-head"><h2>Добавить отработку / доплату</h2></div><div class="form-row"><label class="field">Количество занятий<input name="count" type="number" min="1" max="100" value="1" required></label><label class="field">Мне чистыми, ₽<input name="rub" type="number" min="0" max="1000000" step="0.01" required></label></div><label class="field">За что<input name="note" maxlength="100" placeholder="Отработки"></label><button class="btn primary block">Прибавить к зарплате</button><p class="meta">Сумма прибавляется целиком. Повторно на 50% не делится.</p></form>
 <form class="card form section" data-submit="salary-settings"><div class="section-head"><h2>Автоматическая сводка в чат</h2></div><label class="switch"><span>Ежедневно присылать зарплату</span><input type="checkbox" name="enabled" ${s.daily_report?'checked':''}></label><label class="field">Время, Москва<input name="time" type="time" value="${esc(s.report_time)}" required></label><button class="btn block">Сохранить сводку</button><p class="meta">Reollity читается примерно раз в час; перед сводкой запрашиваются свежие данные. Будущие занятия и записи платформы не меняются.</p></form>`;
}

/* ---------- Text for parents ---------- */
function parentText(s, b) {
  const month = monthLabel(b.month).toLowerCase();
  const genitive = s.dates.length ? fmt(parseDay(s.dates[0].day), { day: 'numeric', month: 'long' }).replace(/^\d+\s/, '') : '';
  const days = s.dates.map((d) => parseDay(d.day).getDate()).join(', ') + ' ' + genitive;
  const lines = [`${s.name} — ${month}`];
  if (s.dates.length) {
    const sameRate = s.dates.every((d) => d.amount === s.rate);
    const n = count(s.dates.length, 'занятие', 'занятия', 'занятий');
    lines.push(`Занятия: ${days} (${n}` + (s.total == null ? ', цена не задана)'
      : sameRate && s.rate != null ? ` × ${rub(s.rate)} = ${rub(s.total)})` : `, ${rub(s.total)})`));
  }
  const unpaid = (s.settlement?.previous_dates || []).filter((d) => d.status !== 'paid');
  if (s.debt) {
    lines.push(`Долг за прошлый месяц: ${rub(s.debt)}${unpaid.length ? ` (${unpaid.map((d) => shortDay(d.day)).join(', ')})` : ''}`);
  }
  if (s.credit) lines.push(`Аванс с прошлого месяца: ${rub(s.credit)}`);
  if (s.current?.paid) lines.push(`Уже внесено: ${rub(s.current.paid)}`);
  if (s.due != null) lines.push(`Итого к оплате: ${rub(s.due)}`);
  else if (s.total != null && s.dates.length) lines.push(`Итого за месяц: ${rub(s.total)}`);
  return lines.join('\n');
}

function chips(rows, cls) {
  return `<div class="date-chips">${rows.map((r) => `<span class="date-chip ${cls(r)}">${esc(shortDay(r.day))}${r.time ? ' · ' + esc(r.time) : ''}</span>`).join('')}</div>`;
}

function detail(s) {
  const b = state.billing, prev = s.previous, current = s.current, settle = s.settlement;
  const prevMonth = prev ? monthLabel(prev.month) : '';
  const payments = (item) => (item?.payments?.length
    ? `<div class="lines">${item.payments.slice().sort((x, y) => x.day.localeCompare(y.day)).map((p) => `<div class="line"><span>${esc(shortDay(p.day))}</span><strong>+ ${esc(rub(p.amount))}</strong></div>`).join('')}</div>`
    : '<p class="muted small-text">Поступлений нет.</p>');
  return `
    <div class="sheet-head"><span class="avatar" aria-hidden="true">${esc(initials(s.name))}</span><h2>${esc(s.name)}</h2>
      <button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <div class="hero">
      <small>К внесению · ${esc(monthLabel(b.month))}</small>
      <div class="sum">${esc(s.due == null ? 'нет данных' : rub(s.due))}</div>
      <div class="sub">${esc(count(s.count, 'занятие', 'занятия', 'занятий'))} по ${esc(rub(s.rate))}${s.leftover ? ' · останется аванс ' + esc(rub(s.leftover)) : ''}</div>
    </div>
    <section class="section card"><div class="section-head"><h2>Как получилась сумма</h2></div><div class="lines">
      <div class="line"><span>Занятия месяца · ${s.count}</span><strong>${esc(rub(s.total))}</strong></div>
      <div class="line"><span>Долг с прошлого месяца</span><strong>+ ${esc(rub(s.debt))}</strong></div>
      <div class="line"><span>Аванс с прошлого месяца</span><strong>− ${esc(rub(s.credit))}</strong></div>
      <div class="line"><span>Уже внесено в этом месяце</span><strong>− ${esc(rub(current?.paid))}</strong></div>
      <div class="line total"><span>К внесению</span><strong>${esc(rub(s.due))}</strong></div>
    </div>${s.linked ? '' : '<p class="muted small-text">Нет сверки с Reollity: долги и оплаты неизвестны.</p>'}</section>
    <section class="section card"><div class="section-head"><h2>Занятия · ${esc(monthLabel(b.month))}</h2><span class="meta">отмечено — проведено</span></div>
      ${s.dates.length ? chips(s.dates, (r) => (r.done ? 'done' : '')) : '<p class="muted small-text">В календаре занятий нет.</p>'}</section>
    ${settle?.previous_dates?.length ? `<section class="section card"><div class="section-head"><h2>${esc(prevMonth)}</h2>
      <span class="meta">долг ${esc(rub(settle.previous_due))}</span></div>
      ${chips(settle.previous_dates, (r) => r.status)}
      <p class="muted small-text">Зелёные — оплачены, жёлтые — частично, красные — не оплачены.</p></section>` : ''}
    ${prev ? `<section class="section card"><div class="section-head"><h2>Поступления</h2></div>
      <p class="small-text muted">${esc(prevMonth)}</p>${payments(prev)}
      <p class="small-text muted">${esc(monthLabel(b.month))}</p>${payments(current)}</section>` : ''}
    <section class="section card"><div class="section-head"><h2>Текст для родителя</h2></div>
      <textarea class="parent-text" readonly rows="6" id="parent-text">${esc(parentText(s, b))}</textarea>
      <button type="button" class="btn block" data-action="copy-parent">${icon('copy', 18)}Скопировать</button></section>
    <form class="section card form" data-submit="billing-student" data-id="${esc(s.id)}">
      <div class="section-head"><h2>Цена и доля</h2></div>
      <div class="form-row">
        <label class="field">Постоянная цена, ₽<input name="rate" type="number" min="0" max="1000000" step="0.01"
          value="${s.own_rate == null ? '' : s.own_rate / 100}" placeholder="${b.defaults?.rate == null ? '' : b.defaults.rate / 100}"></label>
        <label class="field">Ваша доля, %<input name="share" type="number" min="0" max="100" step="1"
          value="${s.own_share == null ? '' : Number(s.own_share)}" placeholder="${Number(b.defaults?.share ?? 50)}"></label>
      </div>
      <button class="btn block">Сохранить для ученика</button>
      <p class="muted small-text">Пустое поле — общее значение из «Мой доход».</p>
    </form>
    <form class="section card form" data-submit="billing-rate" data-id="${esc(s.id)}">
      <label class="field">Цена будущего занятия в этом месяце, ₽
        <input name="price" type="number" min="0" max="1000000" step="0.01" value="${s.rate == null ? '' : s.rate / 100}" required></label>
      <button class="btn primary block">Сохранить цену</button>
      <p class="muted small-text">Проведённые занятия считаются по Reollity. Цена хранится только в вашем боте.</p>
    </form>`;
}

function refreshDetail() {
  if (document.activeElement?.closest('#sheet input')) return; // keep a price being typed
  const s = state.billing?.students.find((x) => x.id === openId);
  if (s) updateSheet(detail(s)); else closeSheet();
}

on('click', 'open-student', (b) => {
  const s = state.billing.students.find((x) => x.id === b.dataset.id);
  openId = s.id;
  openSheet(detail(s), { onClose: () => { openId = ''; } });
});
on('click', 'billing-month', (b) => {
  const d = parseDay(state.billingMonth + '-01');
  d.setMonth(d.getMonth() + Number(b.dataset.step));
  state.billingMonth = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  state.billing = null;
  return loadBilling();
});
on('input', 'billing-search', (input) => {
  // Only the list changes: replacing the field mid-typing breaks keyboards with suggestions.
  state.billingQuery = input.value;
  const list = document.getElementById('people');
  if (list && state.billing) list.innerHTML = peopleHtml(state.billing);
});
on('click', 'students-mode', (b) => { mode = b.dataset.mode; render(); });
on('click', 'copy-parent', async () => {
  const area = document.getElementById('parent-text');
  try {
    await navigator.clipboard.writeText(area.value);
  } catch {
    area.focus();
    area.select();
    document.execCommand('copy');
  }
  toast('Текст скопирован');
});
const saveForm = async (form, action, body, message) => {
  const button = form.querySelector('button');
  if (button.disabled) return;
  button.disabled = true;
  try { await api(action, body); } finally { button.disabled = false; }
  toast(message);
  await loadBilling();
};
on('submit', 'billing-student', (form) => saveForm(form, 'billing-student',
  { id: form.dataset.id, rate: form.rate.value, share: form.share.value, month: state.billingMonth }, 'Сохранено для ученика'));
on('submit', 'billing-defaults', (form) => saveForm(form, 'billing-defaults',
  { rate: form.rate.value, share: form.share.value }, 'Общие цена и доля сохранены'));
on('click', 'billing-due', () => { state.billingOnlyDue = !state.billingOnlyDue; render(); });
on('click', 'billing-refresh', async (button) => {
  button.disabled = true;
  const before = state.billing?.sync?.fetched;
  await api('billing-refresh', {month:state.billingMonth});
  toast('Сверка запрошена. В Reollity ничего не меняется.');
  let tries = 0;
  clearTimeout(poll);
  const again = async () => {
    await loadBilling();
    if (state.billing?.sync?.fetched !== before || state.billing?.sync?.error || ++tries >= 10) return;
    poll = setTimeout(again, 6000);
  };
  poll = setTimeout(again, 1500);
});
on('submit', 'billing-rate', async (form) => {
  const button = form.querySelector('button');
  if (button.disabled) return;
  button.disabled = true;
  try {
  await api('billing-rate', { id: form.dataset.id, month: state.billingMonth, price: form.price.value });
  toast('Цена сохранена для выбранного месяца');
  } finally { button.disabled = false; }
  await loadBilling();
});
on('submit','salary-extra',form=>saveForm(form,'salary-extra',{month:state.billingMonth,count:form.count.value,rub:form.rub.value,note:form.note.value,reference:form.dataset.reference},'Доплата прибавлена к зарплате'));
on('submit','salary-settings',form=>saveForm(form,'salary-settings',{enabled:form.enabled.checked,time:form.time.value},'Сводка настроена'));
on('click','salary-delete-extra',async b=>{if(!await ask('Убрать эту доплату из зарплаты?'))return;await api('salary-extra-delete',{id:b.dataset.id});await loadBilling();toast('Доплата убрана')});
