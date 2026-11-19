"""Journal commands and buttons in the Telegram chat, usable without an external AI service.

/food, /sleep and /gym answer with the day's numbers and one-tap buttons: frequent meals,
water, «как в прошлый раз» for sleep, the next workout of a program. Buttons carry only
short keys; the callback looks everything up again, so a stale button cannot write stale data.
"""
from datetime import datetime, timedelta
import hashlib

from . import activity_chat, food_chat, recipes_chat
from .wellness import Wellness

FREQUENT_BUTTONS = 4


def meal_key(name):
    return hashlib.sha1(' '.join(name.lower().split()).encode()).hexdigest()[:10]


def app_button(bot, label, section):
    url = bot.mini_app_url()
    if not url.startswith('https://'):
        return None
    return {'text': label, 'web_app': {'url': url + ('' if url.endswith('/') else '/') + '?tab=gym&section=' + section}}


def markup(rows):
    rows = [[b for b in row if b] for row in rows]
    rows = [row for row in rows if row]
    return {'reply_markup': {'inline_keyboard': rows}} if rows else {}


def program_key(program):
    """A short, stable key of a program for button data (ids are «program-<12 hex>»)."""
    return program['id'][-12:]


def next_program_day(journal):
    """(program key, day index, title) of the next workout: the day after the last one done from a program."""
    programs = journal.rows('program')
    if not programs:
        return None
    done = sorted((w for w in journal.recent_workouts() if w['status'] == 'done'), key=lambda w: w.get('ended') or w['day'], reverse=True)
    for w in done:
        for p in programs:
            for di, d in enumerate(p['days']):
                if w['name'] == f"{p['name']} · {d['name']}":
                    nxt = (di + 1) % len(p['days'])
                    return program_key(p), nxt, f"{p['name']} · {p['days'][nxt]['name']}"
    return program_key(programs[0]), 0, f"{programs[0]['name']} · {programs[0]['days'][0]['name']}"


def last_sleep(journal):
    rows = journal.rows('sleep')
    return max(rows, key=lambda r: r['end']) if rows else None


def food_view(bot, journal, now):
    data = journal.overview(now=now)
    s, goals = data['summary'], data['settings']
    calories = f'{s["calories"]:g}' + (f' из {goals["calories"]:g}' if goals.get('calories') else '')
    water = f'{s["water_ml"]:g}' + (f' из {goals["water_ml"]:g}' if goals.get('water_ml') else '')
    text = f'🍽 ПИТАНИЕ · {now:%d.%m}\n\n{calories} ккал · Б {s["protein"]:g} / Ж {s["fat"]:g} / У {s["carbs"]:g} г\n💧 {water} мл воды'
    if s['missing_calories']:
        text += f'\nБез калорийности: {s["missing_calories"]} записей.'
    a = data['activity']
    if a['burned'] is not None and (a['steps'] or a['items']):
        moves = [f'шаги {a["steps"]}'] if a['steps'] else []
        moves += [f'{i["name"].lower()} {i["minutes"]} мин' for i in a['items']]
        text += (f'\n🔥 Потрачено {a["burned"]} ккал: ' + ', '.join(moves)
                 + f'\nСъедено − потрачено: {s["calories"] - a["burned"]:g} ккал')
    elif a['steps'] or a['items']:
        text += '\n🔥 Укажите вес, чтобы считать расход: /weight 105 178'
    text += ('\n\nНапишите, что съели: «съел 200 г гречки и 2 яйца» — посчитаю калории и БЖУ.'
             '\nСвои цифры: /food Смузи | 250 | 5 | 3 | 45 · вода: /food вода 250'
             '\nАктивность: /steps 10000 · /activity бег 5 км 30 мин')
    meals = [{'text': '＋ ' + m['name'][:22], 'callback_data': 'w:meal:' + meal_key(m['name'])} for m in data['frequent'][:FREQUENT_BUTTONS]]
    rows = [[{'text': '🧮 Посчитать КБЖУ', 'callback_data': 'w:count'}, {'text': '📖 Рецепты', 'callback_data': 'w:recipes'}]]
    rows += [meals[i:i + 2] for i in range(0, len(meals), 2)]
    rows.append([{'text': '💧 +250 мл', 'callback_data': 'w:water:250'}, {'text': '💧 +500 мл', 'callback_data': 'w:water:500'}])
    rows.append([app_button(bot, 'Открыть питание', 'food')])
    return text, markup(rows)


def sleep_view(bot, journal, now):
    today = [r for r in journal.rows('sleep') if r['day'] == now.date().isoformat()]
    minutes = sum(r['minutes'] for r in today)
    text = f'🌙 СОН · {now:%d.%m}\n\n' + (f'{minutes // 60} ч {minutes % 60} мин записано.' if today else 'Сон сегодня ещё не записан.')
    text += '\n\n/sleep 23:30 07:30 — записать сон до сегодняшнего утра.'
    prev = last_sleep(journal)
    again = None
    if prev and not any(r['minutes'] >= 180 for r in today):
        again = {'text': f'↺ Как в прошлый раз: {prev["start"][11:16]}–{prev["end"][11:16]}', 'callback_data': 'w:sleep:again'}
    return text, markup([[again], [app_button(bot, 'Открыть сон', 'sleep')]])


def gym_view(bot, journal, now):
    data = journal.overview(now=now)
    s, active = data['summary'], data['active']
    goal = data['settings'].get('workouts_week')
    text = f'🏋️ ЗАЛ\n\nЗа 7 дней: {s["workouts_week"]}' + (f' из {goal:g}' if goal else '') + ' тренировок.'
    rows = []
    if active:
        sets = [x for e in active['exercises'] for x in e['sets']]
        text += f'\nИдёт: {active["name"]} · {sum(1 for x in sets if x["done"])} из {len(sets)} подходов.'
        rows.append([{'text': '🏁 Завершить тренировку', 'callback_data': 'w:finish'}])
        rows.append([app_button(bot, 'Продолжить в приложении', 'workout')])
    else:
        nxt = next_program_day(journal)
        if nxt:
            text += f'\nСледующая по программе: {nxt[2]}.'
            rows.append([{'text': '▶ ' + nxt[2][:40], 'callback_data': f'w:start:{nxt[0]}:{nxt[1]}'}])
        rows.append([{'text': '▶ Свободная тренировка', 'callback_data': 'w:start:free'}])
        rows.append([app_button(bot, 'Открыть зал', 'train')])
    text += '\n\nПодходы, таймер отдыха и прогресс — в приложении.'
    return text, markup(rows)


VIEWS = {'/food': food_view, '/sleep': sleep_view, '/gym': gym_view}


async def command(bot, cmd, args):
    now = bot.now()
    journal = Wellness(bot.store, bot.config.timezone)
    try:
        if cmd == '/kcal':
            await (food_chat.offer(bot, args) if args else food_chat.ask(bot))
            return
        if cmd == '/food' and args and '|' not in args and not args.lower().startswith(('вода ', 'water ')):
            await food_chat.offer(bot, args)
            return
        if cmd == '/food' and args:
            if args.lower().startswith(('вода ', 'water ')):
                journal.mutate('wellness-water', dict(ml=args.split(' ', 1)[1]), now)
                await bot.reply('💧 Вода записана.')
                return
            parts = [p.strip() for p in args.split('|')]
            if len(parts) > 5:
                raise ValueError('Еда | ккал | белки | жиры | углеводы')
            body = dict(name=parts[0])
            body.update(dict(zip(('calories', 'protein', 'fat', 'carbs'), parts[1:])))
            journal.mutate('wellness-meal', body, now)
            await bot.reply('🍽 Приём пищи записан. /food — итог дня.')
            return
        if cmd == '/sleep' and args:
            parts = args.split()
            if len(parts) != 2:
                raise ValueError('Пример: /sleep 23:30 07:30 — сон до сегодняшнего утра.')
            end = datetime.combine(now.date(), datetime.strptime(parts[1], '%H:%M').time(), bot.config.timezone)
            start = datetime.combine(now.date(), datetime.strptime(parts[0], '%H:%M').time(), bot.config.timezone)
            if start >= end:
                start -= timedelta(days=1)
            row = journal.mutate('wellness-sleep', dict(day=now.date().isoformat(), start=start.isoformat(), end=end.isoformat()), now)
            await bot.reply(f'🌙 Сон записан: {row["minutes"] // 60} ч {row["minutes"] % 60} мин.')
            return
        if cmd == '/gym' and args.lower() in ('старт', 'start'):
            await start_workout(bot, journal, now, 'free')
            return
        if cmd == '/gym' and args.lower() in ('завершить', 'finish'):
            await finish_workout(bot, journal, now)
            return
        text, extra = VIEWS[cmd](bot, journal, now)
        await bot.reply(text, **extra)
    except (ValueError, KeyError, TypeError) as exc:
        await bot.reply(str(exc))


async def start_workout(bot, journal, now, which):
    already = journal.overview(now=now)['active']
    extra = markup([[app_button(bot, 'Открыть тренировку', 'workout')]])
    if already:  # starting again would only return the running one
        await bot.reply(f'🏋️ Уже идёт тренировка: {already["name"]}. /gym завершить — закончить.', **extra)
        return
    if which == 'free':
        row = journal.mutate('workout-start', {}, now)
    else:
        key, _, day = which.partition(':')
        program = next((p for p in journal.rows('program') if program_key(p) == key), None)
        if not program:
            raise ValueError('Этой программы больше нет. /gym — свежие кнопки.')
        row = journal.mutate('workout-start', dict(program=program['id'], program_day=program['days'][int(day)]['id']), now)
    await bot.reply(f'🏋️ Тренировка началась: {row["name"]}.\nПодходы и таймер отдыха — в приложении. /gym завершить — закончить.', **extra)


async def finish_workout(bot, journal, now):
    active = journal.overview(now=now)['active']
    if not active:
        raise ValueError('Сейчас нет активной тренировки.')
    journal.mutate('workout-finish', dict(id=active['id']), now)
    done = sum(1 for e in active['exercises'] for x in e['sets'] if x['done'])
    await bot.reply(f'✅ Тренировка сохранена: {active["name"]}, {done} подходов.')


async def callback(bot, data):
    """Buttons from /food, /sleep, /gym and the workout reminder."""
    now = bot.now()
    journal = Wellness(bot.store, bot.config.timezone)
    try:
        kind, _, value = data.removeprefix('w:').partition(':')
        if kind == 'water':
            ml = int(value)
            if ml not in (250, 500):
                raise ValueError('Неизвестная кнопка')
            journal.mutate('wellness-water', dict(ml=ml), now)
            total = journal.overview(now=now)['summary']['water_ml']
            await bot.reply(f'💧 +{ml} мл. За сегодня {total:g} мл.')
        elif kind == 'meal':
            meal = next((m for m in journal.overview(now=now)['frequent'] if meal_key(m['name']) == value), None)
            if not meal:
                raise ValueError('Это блюдо больше не в списке частых. /food — свежий список.')
            journal.mutate('wellness-meal', dict(name=meal['name'], time=now.strftime('%H:%M'),
                                                 **{k: meal[k] for k in ('calories', 'protein', 'fat', 'carbs')}), now)
            await bot.reply(f'🍽 Записано: {meal["name"]}' + (f', {meal["calories"]:g} ккал.' if meal['calories'] is not None else '.'))
        elif kind == 'sleep' and value == 'again':
            prev = last_sleep(journal)
            if not prev:
                raise ValueError('Ещё нет записей сна.')
            end = datetime.combine(now.date(), datetime.strptime(prev['end'][11:16], '%H:%M').time(), bot.config.timezone)
            start = datetime.combine(now.date(), datetime.strptime(prev['start'][11:16], '%H:%M').time(), bot.config.timezone)
            if start >= end:
                start -= timedelta(days=1)
            if end > now:
                raise ValueError('Время пробуждения ещё не наступило — запишите сон позже.')
            row = journal.mutate('wellness-sleep', dict(day=now.date().isoformat(), start=start.isoformat(),
                                                        end=end.isoformat(), quality=prev['quality']), now)
            await bot.reply(f'🌙 Сон записан: {row["minutes"] // 60} ч {row["minutes"] % 60} мин.')
        elif kind in ('eat', 'eatno'):
            await food_chat.button(bot, kind, value)
        elif kind == 'count':
            await food_chat.ask(bot)
        elif kind in ('act', 'actno'):
            await activity_chat.button(bot, kind, value)
        elif kind == 'recipes':
            await recipes_chat.menu(bot)
        elif kind in ('rcat', 'rec', 'receat', 'rdel', 'rsave', 'rno'):
            await recipes_chat.button(bot, kind, value)
        elif kind == 'start':
            await start_workout(bot, journal, now, value)
        elif kind == 'finish':
            await finish_workout(bot, journal, now)
        else:
            raise ValueError('Неизвестная кнопка')
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        await bot.reply(str(exc) if isinstance(exc, ValueError) else 'Кнопка устарела. Откройте команду ещё раз.')


def reminder(bot, now):
    """The workout reminder for today, or None when there is nothing to remind about."""
    journal = Wellness(bot.store, bot.config.timezone)
    settings = journal.store.get('wellness_settings', {}) or {}
    if now.weekday() not in (settings.get('remind_days') or []):
        return None
    recent = journal.recent_workouts()
    # Already trained today, or a workout is still open (even one started yesterday).
    if any(w['day'] == now.date().isoformat() or w['status'] == 'active' for w in recent):
        return None
    nxt = next_program_day(journal)
    text = '🏋️ Сегодня день тренировки.' + (f'\nПо программе: {nxt[2]}.' if nxt else '')
    rows = [[{'text': '▶ ' + nxt[2][:40], 'callback_data': f'w:start:{nxt[0]}:{nxt[1]}'}]] if nxt else []
    rows.append([{'text': '▶ Свободная тренировка', 'callback_data': 'w:start:free'}])
    rows.append([app_button(bot, 'Открыть зал', 'train')])
    return text, markup(rows)
