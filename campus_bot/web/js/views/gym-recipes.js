// Recipes page of the gym tab: simple recipes with calories and macros per serving,
// a YouTube video search for each, one-tap «Записать порцию», and the person's own saved links.
import { api, ask, closeSheet, haptic, on, openSheet, render, toast } from '../core.js';
import { icon } from '../icons.js';
import { empty, skeleton } from '../parts.js';
import { esc, todayIso } from '../util.js';

const FILTERS = [['all', 'Все'], ['breakfast', 'Завтраки'], ['main', 'Обед и ужин'], ['snack', 'Перекусы'],
  ['quick', 'До 15 минут'], ['protein', 'Много белка'], ['light', 'До 400 ккал'], ['mine', 'Мои ссылки']];
const QUICK = 15;
const PROTEIN = 25;
const LIGHT = 400;

let data = null;
let loading = false;
let failed = false;
let filter = 'all';
let afterMeal = async () => {};

/** gym.js hands over how to refresh the diary after a portion is logged. */
export function connectRecipes(reloadJournal) {
  afterMeal = reloadJournal;
}

export async function loadRecipes(force = false) {
  if ((data && !force) || loading) return;
  loading = true;
  failed = false;
  try {
    data = await api('recipes');
  } catch (e) {
    failed = true;  // shown with a retry button; no automatic retry loop
    toast(e.message || 'Не удалось загрузить рецепты');
  } finally {
    loading = false;
    render();
  }
}

const kcal = (n) => `${Math.round(n)} ккал`;
const macros = (r) => `Б ${r.protein} · Ж ${r.fat} · У ${r.carbs}`;
const byId = (id) => data?.recipes.find((r) => r.id === id);

function chosen() {
  const all = data.recipes;
  if (filter === 'quick') return all.filter((r) => r.minutes <= QUICK);
  if (filter === 'protein') return all.filter((r) => r.protein >= PROTEIN);
  if (filter === 'light') return all.filter((r) => r.calories <= LIGHT);
  if (filter === 'all') return all;
  return all.filter((r) => r.meal === filter);
}

function card(r) {
  return `<button type="button" class="card recipe-card" data-action="rec-open" data-id="${esc(r.id)}">
    <span class="recipe-top"><span class="badge">${esc(r.tags[0])}</span><span class="meta">${icon('clock', 14)}${r.minutes} мин</span></span>
    <strong>${esc(r.name)}</strong>
    <span class="recipe-kcal"><b>${kcal(r.calories)}</b><span class="meta">${macros(r)} г на порцию</span></span></button>`;
}

function linksView() {
  const links = data.links || [];
  return `<form class="card form section" data-submit="rec-link-add">
      <h3>Сохранить ссылку на рецепт</h3>
      <label class="field">Ссылка<input name="url" type="url" required maxlength="500" placeholder="https://youtu.be/…" inputmode="url"></label>
      <label class="field">Название<input name="title" maxlength="120" placeholder="Например: паста с креветками"></label>
      <button class="btn primary block">${icon('plus', 18)}Сохранить</button>
      <p class="meta">Или пришлите боту ссылку со словом «рецепт».</p></form>
    <section class="section">${links.map((x) => `<article class="card journal-row">
        <button type="button" class="grow link-row" data-action="open-link" data-url="${esc(x.url)}"><strong>${esc(x.title)}</strong>
          <span class="meta">${esc(x.site)} · ${esc((x.added || '').slice(0, 10))}</span></button>
        <button type="button" class="icon-btn small ghost" data-action="rec-link-delete" data-id="${esc(x.id)}" aria-label="Удалить ссылку">${icon('trash', 18)}</button></article>`).join('')
      || empty('Пока пусто', 'Сохраняйте сюда рецепты из YouTube, VK, TikTok и с любых сайтов.')}</section>`;
}

export function recipesView() {
  if (!data) {
    if (failed) return empty('Рецепты не загрузились', 'Проверьте связь и попробуйте ещё раз.') +
      '<button type="button" class="btn block" data-action="rec-retry">Повторить</button>';
    loadRecipes();
    return skeleton(3);
  }
  const list = filter === 'mine' ? '' : chosen();
  return `<div class="chips section" role="group" aria-label="Фильтр рецептов">${FILTERS.map(([id, name]) =>
      `<button class="chip" data-action="rec-filter" data-filter="${id}" aria-pressed="${filter === id}">${name}${id === 'mine' && data.links.length ? ` · ${data.links.length}` : ''}</button>`).join('')}</div>
    ${filter === 'mine' ? linksView() : `<div class="recipe-grid section">${list.map(card).join('')}</div>
      <p class="muted small-text">Калории и БЖУ посчитаны по продуктам рецепта и примерные. «Видео» открывает поиск на YouTube по названию блюда.</p>`}`;
}

function detail(r) {
  return `<div class="sheet-head"><h2>${esc(r.name)}</h2><button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x', 20)}</button></div>
    <div class="badges">${r.tags.map((t) => `<span class="badge">${esc(t)}</span>`).join('')}<span class="badge">${r.minutes} мин</span><span class="badge">порций: ${r.servings}</span></div>
    <div class="stats section"><div class="stat"><b>${Math.round(r.calories)}</b><span>ккал</span></div><div class="stat"><b>${r.protein}</b><span>белки, г</span></div>
      <div class="stat"><b>${r.fat}</b><span>жиры, г</span></div><div class="stat"><b>${r.carbs}</b><span>углеводы, г</span></div></div>
    <p class="meta">На одну порцию.</p>
    <section class="section"><h3>Продукты</h3><ul class="count-list">${r.ingredients.map((i) => `<li><span>${esc(i)}</span></li>`).join('')}</ul></section>
    <section class="section"><h3>Как готовить</h3><ol class="recipe-steps">${r.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol></section>
    <div class="row section"><button type="button" class="btn grow" data-action="open-link" data-url="${esc(r.video)}">${icon('play', 18)}Видео на YouTube</button>
      <button type="button" class="btn primary grow" data-action="rec-eat" data-id="${esc(r.id)}">${icon('plus', 18)}Записать порцию</button></div>`;
}

on('click', 'rec-retry', () => loadRecipes(true));
on('click', 'rec-filter', (b) => { filter = b.dataset.filter; render(); });
on('click', 'rec-open', (b) => { const r = byId(b.dataset.id); if (r) openSheet(detail(r)); });

let busy = false;
async function once(work) {
  if (busy) return;
  busy = true;
  try { await work(); } catch (e) { toast(e.message || 'Не получилось'); } finally { busy = false; }
}

on('click', 'rec-eat', (b) => once(async () => {
  const r = byId(b.dataset.id);
  if (!r) return;
  await api('wellness-meal', { name: `${r.name} · 1 порция`, calories: r.calories, protein: r.protein, fat: r.fat,
    carbs: r.carbs, note: 'Рецепт из каталога', day: todayIso() });
  closeSheet();
  haptic();
  toast(`Записано: ${Math.round(r.calories)} ккал`);
  await afterMeal();
}));

on('submit', 'rec-link-add', (f) => once(async () => {
  const body = Object.fromEntries(new FormData(f));
  await api('wellness-recipe-link', body);
  haptic();
  toast('Ссылка сохранена');
  await loadRecipes(true);
}));

on('click', 'rec-link-delete', (b) => once(async () => {
  if (!(await ask('Удалить эту ссылку?'))) return;
  await api('wellness-recipe-link-delete', { id: b.dataset.id });
  await loadRecipes(true);
}));
