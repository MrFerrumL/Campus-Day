"""The assistant inside the app: ask → see the planned changes → save or cancel → undo.

Nothing is written when the model answers: its operations wait as a proposal for
`PENDING_MINUTES`, tied to the account that asked, and are applied only on confirm,
with the same optimistic checks as in Telegram (if a task changed meanwhile, nothing is saved).
"""
from datetime import datetime, timedelta
import re
import threading
from uuid import uuid4

from . import assistant as core
from . import assistant_journal as journal

PENDING_MINUTES = 10
HISTORY = 8
_busy = set()
_lock = threading.Lock()


def _history(store):
    return store.get('assistant_history', []) or []


def _remember(store, text, answer):
    history = (_history(store) + [dict(role='user', text=text[:1000]), dict(role='assistant', text=answer[:1500])])[-HISTORY:]
    store.set('assistant_history', history)
    return history


def _when(value):
    try:
        return datetime.fromisoformat(value).strftime('%d.%m %H:%M')
    except (TypeError, ValueError):
        return ''


def describe(op, expected, now):
    """A line saying what an operation will do, before anything is saved."""
    action = op.get('action')
    if action in journal.OPS:
        return journal.describe(journal.validate(op, now))
    row = expected.get(op.get('id')) or {}
    title = (op.get('title') or row.get('title') or '').strip()
    if action == 'add_task':
        return f'＋ Задача «{title}» · {_when(op.get("due"))}'
    if action == 'add_event':
        return f'＋ План «{title}» · {_when(op.get("due"))}, {op.get("duration") or 0} мин'
    if action in ('edit_task', 'edit_event'):
        moved = f' → {_when(op["due"])}' if op.get('due') else ''
        renamed = f' → «{op["title"]}»' if op.get('title') and op.get('title') != row.get('title') else ''
        return f'✎ «{row.get("title", "")}»{renamed}{moved}'
    if action == 'task_status':
        return {'done': '✓ ', 'pending': '○ ', 'failed': '✕ '}.get(op.get('status'), '') + f'«{title}»'
    return f'🗑 Удалить «{title}»'


def _pending(store):
    return store.get('assistant_pending', {}) or {}


def ask(store, config, schedule, actor, text, now):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        raise ValueError('Напишите просьбу — до 4000 символов.')
    if re.search(r'\bsk-[A-Za-z0-9_-]{15,}', text):
        raise ValueError('API-ключ вводится только в настройках помощника, не в чате.')
    with _lock:
        if actor in _busy:
            raise ValueError('Предыдущая просьба ещё обрабатывается.')
        _busy.add(actor)
    try:
        context, expected = core.context_for(store, schedule, now)
        result = core.propose(config, text.strip(), context, _history(store))
        return proposal(store, actor, text, result, expected, now)
    finally:
        with _lock:
            _busy.discard(actor)


def proposal(store, actor, text, result, expected, now):
    """Keep the model's operations as a proposal (or just answer when there are none)."""
    if not isinstance(result, dict) or not isinstance(result.get('operations'), list) or not isinstance(result.get('message'), str):
        raise ValueError('Не удалось разобрать ответ ИИ. Ничего не изменено.')
    operations = result['operations'][:15]
    if not operations:
        history = _remember(store, text, result['message'])
        return dict(message=result['message'], pending=None, preview=[], history=history)
    preview = [describe(op, expected, now) for op in operations]
    used = {op.get('id') for op in operations if isinstance(op, dict) and op.get('id') in expected}
    pending = {k: v for k, v in _pending(store).items() if v['actor'] != actor
               and now - datetime.fromisoformat(v['created']) < timedelta(minutes=PENDING_MINUTES)}
    uid = uuid4().hex[:16]
    pending[uid] = dict(actor=actor, created=now.isoformat(), text=text.strip()[:4000], result=dict(result, operations=operations),
                        expected={str(i): expected[i] for i in used}, preview=preview)
    store.set('assistant_pending', pending)
    return dict(message=result['message'], pending=uid, preview=preview, history=_history(store))


def _take(store, actor, uid, now):
    pending = _pending(store)
    item = pending.get(uid) if isinstance(uid, str) else None
    if not item or item['actor'] != actor:  # another account's proposal stays untouched
        raise ValueError('Предложение не найдено. Повторите просьбу.')
    pending.pop(uid)
    store.set('assistant_pending', pending)
    if now - datetime.fromisoformat(item['created']) >= timedelta(minutes=PENDING_MINUTES):
        raise ValueError('Предложение устарело. Повторите просьбу — я возьму свежие данные.')
    return item


def confirm(store, actor, uid, now):
    item = _take(store, actor, uid, now)
    expected = {int(k): v for k, v in item['expected'].items()}
    output = core.apply(store, item['result'], expected, actor, 'web:' + uid, now)
    history = _remember(store, item['text'], output['message'])
    return dict(message=output['message'], run=output.get('run'), changes=output.get('changes', []), history=history)


def cancel(store, actor, uid, now):
    item = _take(store, actor, uid, now)
    history = _remember(store, item['text'], 'Отменено — ничего не изменено.')
    return dict(message='Отменено — ничего не изменено.', history=history)


def undo(store, actor, run):
    if not isinstance(run, str) or not re.fullmatch(r'[0-9a-f]{16}', run):
        raise ValueError('Это изменение недоступно')
    message = core.undo(store, run, actor)
    # The chat keeps the undo too, so the next answer does not hide it.
    store.set('assistant_history', (_history(store) + [dict(role='assistant', text=message)])[-HISTORY:])
    return dict(message=message)


def chat(store, config):
    return dict(core.status(store, config), history=_history(store))


def forget(store):
    store.set('assistant_history', [])
    store.set('assistant_pending', {})
    return dict(history=[])
