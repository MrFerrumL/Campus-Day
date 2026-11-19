from datetime import date, datetime

from .models import WEEKDAYS, overlaps
from .daily_plan import task_when


def event_line(event):
    prefix = "❌ " if event.cancelled else ""
    result = f"{prefix}{event.time_label} · {event.title}"
    return result + ("\n  " + event.details if event.details else "")


def agenda(day, events, note, store, weather="", outlook=""):
    anchor = date.fromisoformat(store.get("cycle_anchor", "2026-01-05"))
    cycle = "A" if ((day - anchor).days // 7) % 2 == 0 else "B"
    parts = [f"📅 {day:%d.%m.%Y} · {WEEKDAYS[day.weekday()]} · неделя {cycle}"]
    if weather:
        parts.append(weather)
    for source, label in [("university", "🎓 Вуз" + (" · " + store.get("group_name") if store.get("group_name") else "")),
                          ("personal", "📚 Занятия"), ("plan", "🗓 Мои планы"), ("hackathon", "🏆 Хакатоны")]:
        selected = [e for e in events if e.source == source]
        if source in ("plan", "hackathon") and not selected:
            continue
        text = "\n".join(('✅ ' if store.checked(e.uid+'|'+e.start.date().isoformat()) else '')
                         + event_line(e) for e in selected)
        if not text:
            text = "Данные не получены — проверьте сайт." if source == "university" and note else "Занятий нет."
        parts.append(label + "\n" + text)
    if note:
        parts.append(note)
    projects = {p["id"]: p for p in store.projects()}
    tasks = [t for t in store.items("task") if datetime.fromisoformat(t["due"]).date() <= day and (
        not t["project"] or projects.get(t["project"], {}).get("status") not in (None, "done", "dropped"))]
    if tasks:
        parts.append("🎯 Дела и дедлайны\n" + "\n".join(
            ('  ↳ ' if t['parent_id'] else '')+('🚨 ' if t['priority'] else '')+f"#{t['id']} · "+task_when(t)+" · "
            + (projects[t["project"]]["title"] + " — " if t["project"] else "") + t["title"] for t in tasks))
    if outlook:
        parts.append("🏆 Скоро по хакатонам\n" + outlook)
    conflicts = overlaps(events)
    if conflicts:
        parts.append("⚠️ Пересечения\n" + "\n".join(
            f"{a.time_label} {a.title} ↔ {b.time_label} {b.title}" for a, b in conflicts))
    active = [e for e in events if not e.cancelled and not e.all_day]
    minutes = sum(int((e.end - e.start).total_seconds() / 60) for e in active)
    unknown = sum(e.start == e.end for e in active)
    duration_label = 'известная длительность' if unknown else 'суммарно'
    parts.append(f"📊 {len(active)} занятий/планов · {duration_label} {minutes // 60} ч {minutes % 60:02} мин"
                 + (f"; у {unknown} окончание не указано" if unknown else "")
                 + (" (пересечения посчитаны отдельно)" if conflicts else ""))
    return "\n\n".join(parts)


MENU = {"keyboard": [["📱 Приложение", "👤 Мой профиль"], ["📅 Сегодня", "🗓 Расписание", "🌅 Завтра"],
                     ["➕ Задача", "🎯 Задачи", "🗓 План"], ["📋 План дня", "📊 Аналитика", "🍅 Фокус"],
                     ["👥 Ученики и оплата", "💼 Зарплата"], ["🏋️ Зал", "🍽 Питание", "🌙 Сон"],
                     ["🏆 Хакатоны", "🤖 Помощник", "🌤 Погода"], ["⚙️ Настройки", "🆔 Мой ID"]],
        "resize_keyboard": True, "is_persistent": True}

HELP = """📔 Campus Day — команды

БЫСТРО В ЧАТЕ
/menu — кнопки главного меню
/accounts — управление подключёнными аккаунтами
/students — ученик → месяц → даты занятий, количество и сумма
/pay Иванов — краткая оплата за текущий месяц; можно просто написать имя или фамилию
/pay Иванов 12.2026 — оплата за выбранный месяц
/reconcile — сверить Reollity; платформа только читается
/students 11.2026 — выбрать месяц; цена меняется отдельно для ученика
/lesson — примеры добавления и переноса занятий в чате
«05.11 12:00 — Фамилия Имя/Фамилия Имя» — добавить один раз
«05.11 — Фамилия Имя/Фамилия Имя вместо 10.11» — перенос с 10-го на 5-е
Галочки проведённых занятий общие с приложением; отмены в сумму не входят.
К внесению = занятия месяца + старый долг − старый аванс − внесённые за месяц деньги.
/dayplan 30.10 — план с подпунктами, галочками и крестиками
/report 30.10 — тот же план как отчёт
/stats day · /stats week · /stats month — аналитика задач
Можно прислать список: «План на завтра:» и пункты с новой строки.
«Важно: название» — важная задача на сегодня без придуманного времени.
✅ сделано · ❌ не сделал · ▫️ в работе; группы отмечают подпункты.
/calendar — сразу полное расписание недели без задач
/month — календарь любого месяца
/day пятница · /day 02.11 — ближайшая пятница / дата
/add — выбрать день → название → время
/plan — добавить блок времени без длинной команды
/tasks — выполнить, вернуть, переименовать и перенести задачу
/stats — галочки и задачи недели
/focus — таймер на 15 / 25 / 50 минут
/cancel — отменить текущий ввод

РАСПИСАНИЕ
/today — весь сегодняшний день + погода
/tomorrow — завтра
/day 2026-11-02 — произвольная дата
/week — все пары и занятия недели, без задач
/import — импорт из Google и Apple Calendar
/next — текущее и следующее занятие
/free завтра 60 — свободные окна от 60 минут, 08:00–23:00
/weather — прогноз погоды
/sync — обновить расписание сейчас

ПЛАНЫ И ДЕДЛАЙНЫ
/add 2026-11-02 23:59 Сдать лабораторную
/plan 2026-11-02 15:00 60 Подготовка к зачёту
/tasks — список, кнопки «Готово» и «+1 час»
/done 3 — завершить задачу / отменить план или напоминание
/move 3 2026-11-03 18:00 — перенести
/focus 25 Математический анализ — таймер фокуса

ХАКАТОНЫ
/hack — все хакатоны, ближайшие этапы и пересечения
/hack hackchange — карточка: этапы, ссылки, кнопки статуса
/hack new alfa Alfa-Hack 2026 — новый хакатон (ID латиницей)
/hack alfa task 2026-11-16 14:00 Сдать решение — дедлайн
/hack alfa event 2026-11-09 14:00 120 Старт кейса — событие
/hack alfa day 2026-11-22 Финал — на весь день
/hack alfa link https://example.com Кабинет — ссылка
/hack alfa status final — registration, review, accepted,
  active, submitted, final, done, dropped
Дедлайны хакатонов напоминают за 3 дня, сутки, 2 часа и в срок.

ПОЧТА
/mail — статус и настройка: важные письма приходят в чат
/mail all — все новые входящие, включая рассылки
/mail important — только важные письма
/mail check — проверить сейчас
/mail vip example.com · /mail mute example.com
/mail off · /mail on · /set mail 5 — проверка раз в 5 минут

НАПОМИНАНИЯ
/remind 2026-11-02 18:00 Купить тетради
/remind daily 09:00 Выпить воды
/remind weekly mon 10:00 Проверить дедлайны
/reminders — список; /done ID — отключить

РЕГУЛЯРНЫЕ ЗАНЯТИЯ
/lesson list — правила и их ID
/lesson add mon,wed 17:00 120 all Моё занятие
/lesson add fri 16:00 120 a Мигалка
/lesson delete ID — удалить правило
/skip 2026-11-02 mon18 — отменить одно занятие
/unskip 2026-11-02 mon18 — вернуть его
Дни: mon tue wed thu fri sat sun. Цикл: all / a / b.

НАСТРОЙКИ
/set digest 07:30,13:00 — сводки на сегодня
/set weather 08:00,16:00 — погода отдельно
/set evening 21:00 — сводка на завтра
/set alerts 30,10 — за сколько минут до занятия
/set sync 180 — обновление сайта раз в N минут
/set anchor 2026-01-05 — понедельник начала цикла A
Вместо времени/интервалов можно off, кроме sync.
/group 1 или /group 2 — подгруппа
/pause — выключить все автоматические сообщения
/resume — включить
/stop — отписаться; /start — снова подписаться
/id или кнопка «🆔 Мой ID» — ID текущего аккаунта
/zp — зарплата по отчёту Reollity, проведённые занятия и прогноз
/zp + 3 5400 отработки — добавить 5400 ₽ чистыми за 3 занятия
/zp время 21:00 — ежедневная сводка зарплаты; выключается кнопкой в /zp

🏋️ Зал и восстановление
/gym — программы, тренировки и подходы
/food — питание и вода; /food вода 250 — записать воду
/food Обед | 550 | 35 | 15 | 60 — еда, ккал, белки, жиры, углеводы
/sleep 23:30 07:30 — сон до сегодняшнего утра
/ai — подключение ИИ-помощника; /ai off — выключить
После подключения API: «добавь завтра задачу», «перенеси отчёт на пятницу».
У изменений ИИ есть кнопка отмены.

Часовой пояс задаётся при установке. Бот работает, пока запущен процесс.
"""
