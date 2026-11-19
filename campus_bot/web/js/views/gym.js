import { api,ask,closeSheet,haptic,load,on,onEnter,openSheet,render,state,switchTab,toast } from '../core.js';
import { icon } from '../icons.js';
import { empty,skeleton } from '../parts.js';
import { esc,iso,parseDay,plus,todayIso } from '../util.js';
import { photoId } from '../fitness.js';
import { figure, watchFigures } from '../figure.js';
import * as library from './gym-library.js';
import * as workout from './gym-workout.js';
import { connectPrograms } from './gym-programs.js';
import { connectPicker } from './gym-picker.js';
import * as progress from './gym-progress.js';
import * as journal from './gym-journal.js';
import * as recipeBook from './gym-recipes.js';

let data=null,section='train',day=todayIso();
const SECTIONS=[['train','Тренировки'],['exercises','Упражнения'],['food','Питание'],['recipes','Рецепты'],['sleep','Сон'],['history','Прогресс']];
const closeButton=`<button type="button" class="icon-btn" data-action="close-sheet" aria-label="Закрыть">${icon('x',20)}</button>`;
const field=(label,name,value='',type='text',extra='')=>`<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value??'')}" ${extra}></label>`;
const num=(label,name,value='',extra='')=>field(label,name,value,'number',`${/\bmin=/.test(extra)?'':'min="0"'} ${/\bstep=/.test(extra)?'':'step="any"'} inputmode="decimal" ${extra}`);
const exercises=()=>data?.exercises||[],exercise=id=>exercises().find(e=>e.id===id);
const shortHours=m=>m==null?'—':(m/60).toFixed(1).replace('.',',')+' ч';

export async function loadWellness(){
 try{data=await api('wellness?day='+day);state.error=false;render()}
 catch(e){toast(e.message);if(!data)render()}
}
onEnter('gym',loadWellness);
export function setSection(value){if(value==='workout'||SECTIONS.some(([id])=>id===value))section=value}
export function afterRender(){workout.afterRender()}
export function view(){
 const head=`<div class="page-head"><h1>Спортивный кабинет</h1></div><div class="wellness-tabs" role="group" aria-label="Разделы спортивного кабинета">${SECTIONS.map(([id,name])=>`<button class="chip" data-action="gym-section" data-section="${id}" aria-pressed="${section===id}">${name}</button>`).join('')}</div>`;
 if(!data)return head+skeleton(3);
 if(section==='workout')return workout.workoutView();
 return head+(section==='train'?trainView():section==='exercises'?library.libraryView():section==='food'?journal.foodView():section==='recipes'?recipeBook.recipesView():section==='sleep'?journal.sleepView():progress.progressView());
}
const LEVEL={beginner:'Новичок'};
const uniqueIds=days=>[...new Set(days.flatMap(d=>d.exercises.map(e=>e.exercise_id)))];
function strip(day,limit=6){const ids=uniqueIds([day]);return `<div class="thumb-strip" aria-hidden="true">${ids.slice(0,limit).map(id=>figure(exercise(id),{size:'thumb',still:true})).join('')}${ids.length>limit?`<span class="more">+${ids.length-limit}</span>`:''}</div>`}
function templateCard(p){const ids=uniqueIds(p.days);return `<article class="card template-card"><div class="badges"><span class="badge">${esc(p.level||'')}</span><span class="badge">${p.per_week} раз в неделю</span></div><h3>${esc(p.name)}</h3><p class="meta">${esc(p.goal||'')} · ${p.days.length} ${p.days.length===1?'тренировка':'тренировки'} · ${ids.length} упражнений</p><div class="thumb-strip" aria-hidden="true">${ids.slice(0,8).map(id=>figure(exercise(id),{size:'thumb',still:true})).join('')}</div><p class="source">Источник: ${esc(p.source||'')}</p><div class="row"><button type="button" class="btn small grow" data-action="gym-template-view" data-id="${esc(p.id)}">Подробнее</button><button type="button" class="btn small primary grow" data-action="gym-template" data-id="${esc(p.id)}">В мои программы</button></div></article>`}
function stats(items){return `<div class="stats wellness-stats section">${items.map(([v,label])=>`<div class="stat"><b>${esc(v)}</b><span>${label}</span></div>`).join('')}</div>`}
function datePicker(){return `<div class="wellness-date section"><button class="icon-btn small" data-action="gym-day" data-shift="-1" aria-label="Предыдущий день">${icon('left',18)}</button><label class="sr-only" for="wellness-date">Дата дневника</label><input id="wellness-date" type="date" data-change="gym-day-input" value="${day}" max="${todayIso()}"><button class="icon-btn small" data-action="gym-day" data-shift="1" ${day>=todayIso()?'disabled':''} aria-label="Следующий день">${icon('right',18)}</button></div>`}
function trainView(){
 const active=data.active;
 return `${active?workout.activeCard():`<div class="card wellness-hero"><h2>Тренировки</h2><p>Записывайте вес, подходы и повторения. Результаты появятся в «Прогрессе».</p><button class="btn primary" data-action="gym-start-free">${icon('plus',18)}Свободная тренировка</button></div>`}
 ${stats([[data.summary.workouts_week,'тренировок за 7 дней'],[data.programs.length,'моих программ'],[shortHours(data.summary.sleep_average),'сон · среднее за 7 дней']])}
 <section class="section"><div class="section-head"><h2>Мои программы</h2><button class="btn small" data-action="gym-new-program">${icon('plus',16)}Своя</button></div>
 ${data.programs.map(p=>`<article class="card gym-program"><div class="row"><h3 class="grow">${esc(p.name)}</h3><button class="icon-btn small ghost" data-action="gym-edit-program" data-id="${esc(p.id)}" aria-label="Изменить программу">${icon('edit',18)}</button></div><p class="meta">${esc(p.note)}</p>${p.days.map(d=>`<div class="program-day"><div class="grow"><strong>${esc(d.name)}</strong><div class="meta">${d.exercises.length} упражнений</div>${strip(d)}</div><button class="btn small" data-action="gym-plan" data-id="${esc(p.id)}" data-day="${esc(d.id)}">В план</button><button class="btn small primary" data-action="gym-start" data-id="${esc(p.id)}" data-day="${esc(d.id)}">Начать</button></div>`).join('')}</article>`).join('')||empty('Программа под тебя','Возьмите шаблон ниже или создайте собственную программу.')}</section>
 <section class="section"><div class="section-head"><h2>Готовые программы</h2></div><div class="template-grid">${data.templates.map(templateCard).join('')}</div><p class="muted small-text">Программы по известным схемам — источник указан в карточке. Начните с комфортного веса, разомнитесь и сохраняйте контроль движения. Боль — повод остановить упражнение.</p></section>
 <button type="button" class="card library-link section" data-action="gym-section" data-section="exercises">${figure(exercise('barbell_squat'),{size:'thumb'})}<span class="grow"><strong>Все упражнения</strong><span class="meta">${exercises().length} упражнений с анимацией, техникой и картой мышц</span></span>${icon('right',20)}</button>`;
}

async function mutate(action,body){await api(action,body);haptic();await loadWellness()}
function sheet(title,body){openSheet(`<div class="sheet-head"><h2>${esc(title)}</h2>${closeButton}</div>${body}`)}
on('click','gym-section',b=>{section=b.dataset.section;render();afterRender()});
on('change','gym-day-input',async b=>{day=b.value;await loadWellness()});
on('click','gym-day',async b=>{day=iso(plus(parseDay(day),+b.dataset.shift));await loadWellness()});
on('click','gym-start-free',async()=>{section='workout';await mutate('workout-start',{});toast('Тренировка началась')});
on('click','gym-start',async b=>{section='workout';await mutate('workout-start',{program:b.dataset.id,program_day:b.dataset.day});toast('Тренировка открыта')});
on('click','gym-template',async b=>{await mutate('wellness-program',{template:b.dataset.id});closeSheet();toast('Шаблон добавлен — его можно менять')});
on('click','gym-delete',async b=>{if(await ask('Удалить эту запись?'))await mutate('wellness-delete',{id:b.dataset.id,kind:b.dataset.kind})});
on('click','gym-water',async b=>{await mutate('wellness-water',{day,ml:+b.dataset.ml});toast('Вода записана')});
on('click','gym-water-custom',()=>sheet('Записать воду',`<form class="form" data-submit="gym-water-custom">
 ${num('Объём, мл','ml',250,'min="1" max="5000" step="1" required')}
 <button class="btn primary block">Записать</button></form>`));
on('submit','gym-water-custom',async f=>{await mutate('wellness-water',{day,ml:+f.elements.ml.value});closeSheet();toast('Вода записана')});


on('click','gym-plan',b=>{const p=data.programs.find(p=>p.id===b.dataset.id),d=p.days.find(d=>d.id===b.dataset.day);sheet('Тренировка в календаре',`<form class="form" data-submit="gym-plan-save">${field('Название','title','Зал · '+p.name+' · '+d.name)}${field('Дата','date',todayIso(),'date','required')}${field('Время','time','18:00','time','required')}${num('Длительность, мин','duration',60,'min="5" max="1440" required')}<button class="btn primary block">Добавить в календарь</button></form>`)});
on('submit','gym-plan-save',async f=>{await api('event',{title:f.title.value,start:f.date.value+'T'+f.time.value,duration:+f.duration.value});closeSheet();toast('Тренировка в календаре');await load()});

on('click','gym-meal',b=>{const m=data.records.meal.find(r=>r.id===b.dataset.id)||{};sheet('Приём пищи',`<form class="form" data-submit="gym-meal-save" data-id="${m.id||''}">${field('Что ел и сколько','name',m.name,'text','required maxlength="150" placeholder="Овсянка 60 г, молоко 200 мл, банан"')}<button type="button" class="btn block" data-action="gym-meal-count">${icon('calc',18)}Посчитать КБЖУ</button><div class="meal-count" aria-live="polite"></div>${field('Время','time',m.time||'12:00','time')}${num('Калории, ккал','calories',m.calories,'max="10000"')}<div class="form-row">${num('Белки, г','protein',m.protein)}${num('Жиры, г','fat',m.fat)}${num('Углеводы, г','carbs',m.carbs)}</div>${field('Заметка','note',m.note)}<p class="meta">«Посчитать КБЖУ» оценит по таблице продуктов, цифры можно поправить. Неизвестное оставьте пустым.</p><button class="btn primary block">Записать</button></form>`)});
let counting=false;
on('click','gym-meal-count',async b=>{const f=b.closest('form'),text=f.elements.name.value.trim(),out=f.querySelector('.meal-count');if(!text){toast('Напишите, что съели и сколько');return}if(counting)return;counting=true;b.disabled=true;
  try{const r=await api('food-count',{text});if(!r.items.length){out.innerHTML=`<p class="meta">Не нашёл продуктов в таблице. Напишите проще: «гречка 200 г, 2 яйца» — или впишите цифры сами.</p>`;return}
    for(const k of ['calories','protein','fat','carbs'])f.elements[k].value=r.total[k];
    f.elements.note.value=r.items.map(i=>`${i.name} ${i.amount}: ${i.calories} ккал`).join('; ').slice(0,500);
    out.innerHTML=`<ul class="count-list">${r.items.map(i=>`<li><span>${esc(i.name)} <span class="meta">${esc(i.amount)}</span></span><b>${i.calories} ккал</b></li>`).join('')}</ul>${r.unknown.length?`<p class="meta">Не нашёл: ${r.unknown.map(u=>'«'+esc(u)+'»').join(', ')} — добавьте их калории вручную.</p>`:''}<p class="meta">Итого ${r.total.calories} ккал · Б ${r.total.protein} · Ж ${r.total.fat} · У ${r.total.carbs} г. Цифры примерные.</p>`;haptic()}
  catch(e){toast(e.message||'Не получилось посчитать')}finally{counting=false;b.disabled=false}});
on('submit','gym-meal-save',async f=>{const body=Object.fromEntries(new FormData(f));if(f.dataset.id)body.id=f.dataset.id;await mutate('wellness-meal',{...body,day});closeSheet();toast('Питание записано')});
on('click','gym-sleep',b=>{const r=data.records.sleep.find(r=>r.id===b.dataset.id)||{},before=iso(plus(parseDay(day),-1));sheet('Сон и восстановление',`<form class="form" data-submit="gym-sleep-save" data-id="${r.id||''}">${field('Заснул','start',r.start?.slice(0,16)||before+'T23:00','datetime-local','required')}${field('Проснулся','end',r.end?.slice(0,16)||day+'T07:00','datetime-local','required')}<label class="field">Как спалось<select name="quality">${[[1,'Очень плохо'],[2,'Не выспался'],[3,'Нормально'],[4,'Хорошо'],[5,'Отлично']].map(([v,t])=>`<option value="${v}" ${v===(r.quality||3)?'selected':''}>${v} · ${t}</option>`).join('')}</select></label>${field('Заметка','note',r.note)}<button class="btn primary block">Сохранить сон</button></form>`)});
on('submit','gym-sleep-save',async f=>{const body=Object.fromEntries(new FormData(f));if(f.dataset.id)body.id=f.dataset.id;await mutate('wellness-sleep',{...body,day:body.end.slice(0,10)});closeSheet();toast('Сон записан')});
on('click','gym-goals',()=>{const g=data.settings;sheet('Мои ориентиры',`<form class="form" data-submit="gym-goals-save">${field('Цель','goal',g.goal||'Снижение веса и сохранение мышц')}${num('Калорий в день','calories',g.calories)}${num('Белка, г в день','protein',g.protein)}${num('Воды, мл в день','water_ml',g.water_ml)}<div class="form-row">${num('Вес, кг','weight_kg',g.weight_kg,'min="30" max="300"')}${num('Рост, см','height_cm',g.height_cm,'min="100" max="250"')}</div>${num('Сон, часов','sleep_hours',g.sleep_hours)}${num('Тренировок в неделю','workouts_week',g.workouts_week)}<fieldset class="field"><legend>Напоминать о тренировке в Telegram</legend><div class="muscle-checks">${['пн','вт','ср','чт','пт','сб','вс'].map((d,i)=>`<label class="check-chip"><input type="checkbox" name="remind_days" value="${i}" ${(g.remind_days||[]).includes(i)?'checked':''}><span>${d}</span></label>`).join('')}</div></fieldset>${field('Во сколько','remind_time',g.remind_time||'18:00','time')}<p class="meta">Бот напомнит в выбранные дни, если тренировки ещё не было, и предложит следующую по программе.</p><p class="meta">Личные ориентиры, а не автоматически назначенная диета. Неизвестные поля оставьте пустыми.</p><button class="btn primary block">Сохранить</button></form>`)});
on('click','gym-activity',()=>{const types=Object.entries(data.activity_types||{});sheet('Активность',`<form class="form" data-submit="gym-activity-save"><label class="field">Что делали<select name="type">${types.map(([id,name])=>`<option value="${id}">${esc(name)}</option>`).join('')}</select></label><div class="form-row">${num('Минут','minutes',30,'min="1" max="600" required')}${num('Дистанция, км','distance_km','','max="300"')}</div>${field('Время','time',new Date().toTimeString().slice(0,5),'time')}${field('Заметка','note','','text','maxlength="300"')}<p class="meta">Для бега, ходьбы и велосипеда дистанция уточняет расход по скорости.</p><button class="btn primary block">Записать</button></form>`)});
on('submit','gym-activity-save',async f=>{const body=Object.fromEntries(new FormData(f));await mutate('wellness-activity',{...body,day});closeSheet();toast('Активность записана')});
on('submit','gym-steps-save',async f=>{const steps=f.elements.steps.value;if(steps==='')return;await mutate('wellness-steps',{steps,day});toast('Шаги сохранены')});
on('submit','gym-goals-save',async f=>{const form=new FormData(f),body=Object.fromEntries(form);body.remind_days=form.getAll('remind_days').map(Number);await mutate('wellness-settings',body);closeSheet();toast('Ориентиры сохранены')});

library.connect(()=>data,loadWellness,()=>watchFigures());
on('click','gym-template-view',b=>{const p=data.templates.find(t=>t.id===b.dataset.id);if(!p)return;sheet(p.name,`<div class="badges"><span class="badge">${esc(p.level||'')}</span><span class="badge">${p.per_week} раз в неделю</span><span class="badge">${esc(p.goal||'')}</span></div><p>${esc(p.note)}</p><p class="source">Источник: ${esc(p.source||'')}</p>${p.days.map(d=>`<section class="section"><h3>${esc(d.name)}</h3>${d.exercises.map(e=>{const x=exercise(e.exercise_id)||{};return `<button type="button" class="plan-row" data-action="gym-exercise" data-id="${esc(e.exercise_id)}">${figure(x,{size:'thumb',label:x.name})}<span class="grow"><strong>${esc(x.name||e.exercise_id)}</strong><span class="meta">${e.sets} × ${esc(e.reps)}${e.rest_seconds?` · отдых ${e.rest_seconds} сек`:''}</span></span>${icon('right',18)}</button>`}).join('')}</section>`).join('')}<button type="button" class="btn primary block" data-action="gym-template" data-id="${esc(p.id)}">В мои программы</button>`)});
workout.connect(()=>data,loadWellness,next=>{section=next;render();afterRender();window.scrollTo(0,0)});
connectPrograms(()=>data,loadWellness);
connectPicker(()=>data);
progress.connectProgress(()=>data);
recipeBook.connectRecipes(loadWellness);
journal.connectJournal(()=>data,()=>day,datePicker,mutate);
// Tiles on the Today screen open a page of this tab.
on('click','go-gym',b=>{section=b.dataset.section||'train';day=todayIso();return switchTab('gym')});
