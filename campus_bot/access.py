"""Explicit, single-use invitations to the owner's shared calendar."""
from datetime import datetime, timedelta
import hashlib
import json
import re
import secrets


def accounts(store):
    return [a for a in store.get('authorized_accounts', []) if a.get('active', True)]


def allowed_ids(store, primary):
    return {primary} | {int(a['id']) for a in accounts(store)}


class AccountAccess:
    def __init__(self, store):
        self.store = store

    def issue(self, username, now):
        username = username.strip().lstrip('@')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', username):
            raise ValueError('Укажите Telegram username')
        token = secrets.token_urlsafe(24)
        pending = [r for r in self.store.get('account_invites', [])
                   if datetime.fromisoformat(r['expires']) > now and not r.get('claimed_by')]
        pending = [r for r in pending if r['username'].casefold() != username.casefold()]
        pending.append(dict(digest=hashlib.sha256(token.encode()).hexdigest(), username=username,
                            expires=(now+timedelta(hours=24)).isoformat()))
        self.store.set('account_invites', pending)
        return token

    def claim(self, token, user, now):
        if not isinstance(user.get('id'), int) or user['id']<=0 or user.get('is_bot'):
            raise ValueError('Откройте ссылку из личного Telegram-аккаунта')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            invites = self.store.get('account_invites', [])
            invite = next((r for r in invites if secrets.compare_digest(r['digest'],digest)), None)
            if not invite:
                raise ValueError('Ссылка недействительна. Запросите новое приглашение.')
            records = self.store.get('authorized_accounts', [])
            existing = next((a for a in records if a['id']==user['id'] and a.get('active',True)), None)
            if invite.get('claimed_by'):
                if invite['claimed_by']==user['id'] and existing:
                    return existing, False
                raise ValueError('Приглашение уже использовано')
            if datetime.fromisoformat(invite['expires']) <= now:
                raise ValueError('Ссылка истекла. Запросите новое приглашение.')
            if invite['username'].casefold() != user.get('username','').casefold():
                raise ValueError('Откройте ссылку именно из аккаунта @'+invite['username'])
            record = dict(id=user['id'],username=user['username'],role='full',active=True,
                          notifications=True,linked_at=now.isoformat())
            records = [a for a in records if a['id']!=user['id']]+[record]
            invite['claimed_by']=user['id']
            for key,value in (('authorized_accounts',records),('account_invites',invites)):
                self.store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key,json.dumps(value,ensure_ascii=False)))
        return record, True

    def revoke(self, uid):
        records = self.store.get('authorized_accounts', [])
        for record in records:
            if record['id']==int(uid):
                record['active']=False
        self.store.set('authorized_accounts',records)
        from .web_login import revoke
        revoke(self.store, int(uid), everywhere=True)

    def stop_notifications(self, uid):
        records = self.store.get('authorized_accounts', [])
        for record in records:
            if record['id']==uid:
                record['notifications']=False
        self.store.set('authorized_accounts',records)


class AccountStore:
    """Shared calendar and data; each account keeps its own unfinished chat input."""
    LOCAL = {'chat_pending','tutoring_pending','tutoring_search','assistant_history'}

    def __init__(self, store, uid):
        self.base, self.uid = store, uid

    def key(self, key):
        return f'account:{self.uid}:{key}' if key in self.LOCAL else key

    def get(self, key, default=None):
        return self.base.get(self.key(key),default)

    def set(self, key, value):
        return self.base.set(self.key(key),value)

    def __getattr__(self, name):
        return getattr(self.base,name)
