import json
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone

DEFAULTS = {
    "group_id": 0, "group_name": "", "subscribed": False,
    "digest_times": ["07:30"], "weather_times": ["08:00"], "evening_time": "21:00",
    "alert_minutes": [30, 10], "sync_minutes": 180, "notifications": True,
}


TASK_REPEATS = {'daily', 'weekdays', 'weekly'}


def next_due(due, recurrence, moment):
    """The next date of a repeating task after `due`, and not in the past."""
    step = timedelta(days=7 if recurrence == 'weekly' else 1)
    result = due + step
    while (recurrence == 'weekdays' and result.weekday() > 4) or result <= moment:
        result += step if recurrence != 'weekdays' else timedelta(days=1)
    return result


# The streak looks at most this many completions back.
DONE_DAYS_LIMIT = 2000


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rules (id TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS skips (rule_id TEXT, day TEXT, PRIMARY KEY(rule_id, day));
            CREATE TABLE IF NOT EXISTS items (
              id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL,
              due TEXT NOT NULL, duration INTEGER NOT NULL DEFAULT 0,
              recurrence TEXT NOT NULL DEFAULT 'once', done INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS deliveries (key TEXT PRIMARY KEY, sent TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS imported_calendar (
                source TEXT NOT NULL, occurrence TEXT NOT NULL, item INTEGER NOT NULL,
                fingerprint TEXT NOT NULL, PRIMARY KEY(source, occurrence));
            CREATE TABLE IF NOT EXISTS checks (key TEXT PRIMARY KEY, done INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS attendance (key TEXT PRIMARY KEY, status TEXT NOT NULL
                CHECK(status IN ('present','absent')));
            CREATE TABLE IF NOT EXISTS wellness (id TEXT PRIMARY KEY, kind TEXT NOT NULL, day TEXT NOT NULL, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS wellness_kind_day ON wellness(kind,day);
            CREATE TABLE IF NOT EXISTS assistant_runs (id TEXT PRIMARY KEY, actor INTEGER NOT NULL, created TEXT NOT NULL,
                request_key TEXT UNIQUE NOT NULL, before_items TEXT NOT NULL, after_items TEXT NOT NULL,
                summary TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS overrides (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tutoring_students (id TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lesson_changes (id TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reollity_accounts (id TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reollity_calendar (id TEXT PRIMARY KEY, day TEXT NOT NULL, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS reollity_calendar_day ON reollity_calendar(day);
        """)
        # Databases created before hackathons lack these columns; existing rows keep their meaning.
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(items)")}
        for name, kind in (("project", "TEXT"), ("note", "TEXT NOT NULL DEFAULT ''"),
                           ("all_day", "INTEGER NOT NULL DEFAULT 0"), ("priority", "INTEGER NOT NULL DEFAULT 0"),
                           ("parent_id", "INTEGER"), ("plan_id", "TEXT"),
                           ("is_group", "INTEGER NOT NULL DEFAULT 0"), ("done_at", "TEXT"),
                           ("skipped", "INTEGER NOT NULL DEFAULT 0"), ("skipped_at", "TEXT")):
            if name not in columns:
                self.db.execute(f"ALTER TABLE items ADD COLUMN {name} {kind}")
        self.db.commit()
        self.db.execute('CREATE TABLE IF NOT EXISTS mail_actions (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS daily_plans (id TEXT PRIMARY KEY, day TEXT NOT NULL, fingerprint TEXT UNIQUE NOT NULL, value TEXT NOT NULL)')
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else DEFAULTS.get(key, default)

    def set(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))

    def cache_get(self, key):
        row = self.db.execute("SELECT value, fetched FROM cache WHERE key=?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def cache_put(self, key, value, fetched):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                            (key, json.dumps(value, ensure_ascii=False), fetched))

    def seed_rules(self, document):
        if self.get("rules_seeded", False):
            return
        with self.db:
            for rule in document["lessons"]:
                self.db.execute("INSERT OR IGNORE INTO rules VALUES (?, ?)",
                                (rule["id"], json.dumps(rule, ensure_ascii=False)))
            self.db.execute("INSERT INTO settings VALUES ('rules_seeded', 'true')")

    def rules(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT value FROM rules ORDER BY id")]

    def put_rule(self, rule):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO rules VALUES (?, ?)",
                            (rule["id"], json.dumps(rule, ensure_ascii=False)))

    def students(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT value FROM tutoring_students ORDER BY id')]

    def platform_accounts(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT value FROM reollity_accounts ORDER BY id')]

    def platform_events(self, day):
        return [json.loads(r[0]) for r in self.db.execute('SELECT value FROM reollity_calendar WHERE day=? ORDER BY id', (str(day),))]

    def platform_event(self, uid):
        row = self.db.execute('SELECT value FROM reollity_calendar WHERE id=?', (uid,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_student(self, student):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO tutoring_students VALUES (?,?)',
                            (student['id'], json.dumps(student, ensure_ascii=False)))

    def lesson_changes(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT value FROM lesson_changes ORDER BY id')]

    def put_lesson_change(self, change):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO lesson_changes VALUES (?,?)',
                            (change['id'], json.dumps(change, ensure_ascii=False)))

    def delete_rule(self, uid):
        with self.db:
            return self.db.execute("DELETE FROM rules WHERE id=?", (uid,)).rowcount > 0

    def skip(self, uid, day, skip=True):
        with self.db:
            if skip:
                self.db.execute("INSERT OR IGNORE INTO skips VALUES (?, ?)", (uid, day))
            else:
                self.db.execute("DELETE FROM skips WHERE rule_id=? AND day=?", (uid, day))

    def skipped(self, uid, day):
        return self.db.execute("SELECT 1 FROM skips WHERE rule_id=? AND day=?", (uid, day)).fetchone() is not None

    def add_item(self, kind, title, due, duration=0, recurrence="once", project=None, note="", all_day=False, priority=0):
        with self.db:
            return self.db.execute(
                "INSERT INTO items(kind,title,due,duration,recurrence,project,note,all_day,priority) VALUES (?,?,?,?,?,?,?,?,?)",
                (kind, title, due, duration, recurrence, project, note, int(all_day), int(priority))).lastrowid

    def mail_action(self, key):
        row=self.db.execute('SELECT value FROM mail_actions WHERE id=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_mail_action(self, key, value):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO mail_actions VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))

    def accept_mail_task(self, key, index, due_override=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            offer=self.mail_action(key)
            candidate=offer['candidates'][index]
            if candidate.get('task_id'):
                return candidate['task_id']
            due=due_override or candidate['due']
            if not due:raise ValueError('Укажите время')
            uid=self.db.execute("INSERT INTO items(kind,title,due,note,priority) VALUES ('task',?,?,?,1)",
                (candidate['title'],due,candidate.get('context','')+'\n'+offer.get('url',''))).lastrowid
            candidate['task_id']=uid
            self.db.execute('UPDATE mail_actions SET value=? WHERE id=?',(json.dumps(offer,ensure_ascii=False),key))
            return uid

    def items(self, kind=None, include_done=False):
        # Filtering in SQL: the scheduler calls this every 20 s and finished tasks only pile up.
        where, args = [], []
        if kind is not None:
            where.append("kind=?")
            args.append(kind)
        if not include_done:
            where.append("done=0 AND skipped=0")
        sql = "SELECT * FROM items" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY due, id"
        return [dict(r) for r in self.db.execute(sql, args)]

    def app_tasks(self, since):
        """Tasks for the app: every open one, finished ones due or closed since `since`
        (enough for the 14-day analytics and the streak), and all subtasks of an open group."""
        rows = [dict(r) for r in self.db.execute(
            "SELECT * FROM items WHERE kind='task' AND (done=0 AND skipped=0 OR due>=? OR done_at>=? OR skipped_at>=?"
            " OR parent_id IN (SELECT id FROM items WHERE kind='task' AND done=0 AND skipped=0)) ORDER BY due, id",
            (since, since, since))]
        seen = {r['id'] for r in rows}
        # The latest important ones always come along for «Важное сделано».
        rows += [dict(r) for r in self.db.execute(
            "SELECT * FROM items WHERE kind='task' AND done=1 AND is_group=0 AND priority=1"
            " ORDER BY done_at DESC LIMIT 5").fetchall() if r['id'] not in seen]
        return rows

    def done_moments(self, limit=DONE_DAYS_LIMIT):
        """When finished tasks were closed, newest first: the app's streak counts over all of them."""
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT done_at FROM items WHERE kind='task' AND done=1 AND is_group=0 AND done_at IS NOT NULL"
            " ORDER BY done_at DESC LIMIT ?", (limit,))]

    def set_task_status(self, uid, status, now=None):
        if status not in ('pending', 'done', 'failed'):
            raise ValueError('Неизвестный статус задачи')
        moment = now or datetime.now(timezone.utc)
        now = moment.isoformat()
        row = self.db.execute("SELECT * FROM items WHERE id=? AND kind='task'", (int(uid),)).fetchone()
        if row is None:
            return False
        def update(item_id):
            self.db.execute('UPDATE items SET done=?,skipped=?,done_at=CASE WHEN done=1 AND ? IS NOT NULL THEN COALESCE(done_at,?) ELSE ? END,skipped_at=CASE WHEN skipped=1 AND ? IS NOT NULL THEN COALESCE(skipped_at,?) ELSE ? END WHERE id=?',
                            (int(status=='done'),int(status=='failed'),*[now if status=='done' else None]*3,
                             *[now if status=='failed' else None]*3,item_id))
            for child in self.db.execute('SELECT id FROM items WHERE parent_id=?', (item_id,)).fetchall():
                update(child[0])
        with self.db:
            update(int(uid))
            parent = row['parent_id']
            while parent:
                children = self.db.execute('SELECT done,skipped FROM items WHERE parent_id=?', (parent,)).fetchall()
                done = bool(children) and all(c['done'] for c in children)
                skipped = bool(children) and not done and all(c['done'] or c['skipped'] for c in children)
                self.db.execute('UPDATE items SET done=?,skipped=?,done_at=?,skipped_at=? WHERE id=?',
                                (int(done),int(skipped),now if done else None,now if skipped else None,parent))
                row = self.db.execute('SELECT parent_id FROM items WHERE id=?', (parent,)).fetchone()
                parent = row[0] if row else None
            if status != 'pending':
                self._repeat(int(uid), moment)
        return True

    def _repeat(self, uid, moment):
        """A closed repeating task brings its next occurrence (once, however often it is toggled)."""
        item = self.db.execute("SELECT * FROM items WHERE id=? AND kind='task'", (uid,)).fetchone()
        if not item or item['recurrence'] not in TASK_REPEATS or item['parent_id'] or item['project']:
            return
        due = next_due(datetime.fromisoformat(item['due']), item['recurrence'], moment)
        # One open copy at a time: reopening and closing again must not add another.
        twin = self.db.execute("SELECT 1 FROM items WHERE kind='task' AND title=? AND recurrence=? AND id<>? "
                               "AND due>? AND done=0 AND skipped=0",
                               (item['title'], item['recurrence'], uid, item['due'])).fetchone()
        if not twin:
            self.db.execute("INSERT INTO items(kind,title,due,duration,recurrence,note,all_day,priority) VALUES "
                            "('task',?,?,?,?,?,?,?)", (item['title'], due.isoformat(), item['duration'],
                                                       item['recurrence'], item['note'], item['all_day'], item['priority']))

    def delete_task(self, uid):
        def remove(item_id):
            children=self.db.execute('SELECT id FROM items WHERE parent_id=?',(item_id,)).fetchall()
            for child in children:
                remove(child[0])
            return self.db.execute("DELETE FROM items WHERE id=? AND kind='task'",(item_id,)).rowcount>0
        with self.db:
            return remove(int(uid))

    def set_priority(self,uid,value):
        if value not in (0,1):
            raise ValueError('Неверный приоритет')
        def update(item_id):
            self.db.execute('UPDATE items SET priority=? WHERE id=?',(value,item_id))
            for child in self.db.execute('SELECT id FROM items WHERE parent_id=?',(item_id,)).fetchall():
                update(child[0])
        with self.db:
            update(int(uid))

    def import_daily_plan(self, draft, now):
        import hashlib
        from uuid import uuid4
        fingerprint = hashlib.sha256(json.dumps(draft,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        existing = self.db.execute('SELECT id FROM daily_plans WHERE fingerprint=?', (fingerprint,)).fetchone()
        if existing:
            return existing[0], False
        uid = uuid4().hex[:12]
        ids, created, adopted = [], [], []
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            for node in draft['nodes']:
                parent = ids[node['parent']] if node.get('parent') is not None else None
                reusable = self.db.execute("SELECT id FROM items WHERE kind='task' AND plan_id IS NULL AND parent_id IS NULL AND title=? AND due=? AND duration=?",
                                          (node['title'],node['due'],node.get('duration',0))).fetchone() if parent is None else None
                if reusable:
                    item_id = reusable[0]
                    self.db.execute('UPDATE items SET plan_id=? WHERE id=?', (uid,item_id))
                    adopted.append(item_id)
                else:
                    done = bool(node.get('done'))
                    item_id = self.db.execute('INSERT INTO items(kind,title,due,duration,note,all_day,priority,parent_id,plan_id,is_group,done,done_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        ('task',node['title'],node['due'],node.get('duration',0),node.get('note',''),int(node['all_day']),
                         int(node.get('priority',0)),parent,uid,int(node.get('is_group',False)),int(done),
                         (now.isoformat() if draft['day']==now.date().isoformat() else draft['day']) if done else None)).lastrowid
                    created.append(item_id)
                ids.append(item_id)
            self.db.execute('INSERT INTO daily_plans VALUES (?,?,?,?)',
                            (uid,draft['day'],fingerprint,json.dumps(dict(item_ids=ids,created_ids=created,adopted_ids=adopted),ensure_ascii=False)))
        # Recompute groups using leaf statuses; no inferred completion of unfinished work.
        for item_id in ids:
            row = self.db.execute('SELECT done,is_group FROM items WHERE id=?', (item_id,)).fetchone()
            if row['done'] and not row['is_group']:
                self.set_task_status(item_id,'done',now)
        return uid, True

    def undo_daily_plan(self, uid):
        row = self.db.execute('SELECT value FROM daily_plans WHERE id=?', (uid,)).fetchone()
        if not row:
            return False
        value = json.loads(row[0])
        with self.db:
            for item_id in value['created_ids']:
                self.db.execute('DELETE FROM items WHERE id=? AND plan_id=?', (item_id,uid))
            for item_id in value['adopted_ids']:
                self.db.execute('UPDATE items SET plan_id=NULL WHERE id=? AND plan_id=?', (item_id,uid))
            self.db.execute('DELETE FROM daily_plans WHERE id=?', (uid,))
        return True

    def finish(self, uid):
        item = self.db.execute('SELECT kind,done FROM items WHERE id=?', (uid,)).fetchone()
        if item and item['kind']=='task':
            return False if item['done'] else self.set_task_status(uid,'done')
        with self.db:
            return self.db.execute("UPDATE items SET done=1 WHERE id=? AND done=0", (uid,)).rowcount > 0

    def move(self, uid, due):
        row=self.db.execute('SELECT due,all_day,is_group FROM items WHERE id=? AND done=0',(uid,)).fetchone()
        if not row:return False
        new=datetime.fromisoformat(due)
        if row['all_day']:
            new=new.replace(hour=23,minute=59,second=0,microsecond=0)
        delta=new.date()-datetime.fromisoformat(row['due']).date()
        def shift(parent):
            for child in self.db.execute('SELECT id,due FROM items WHERE parent_id=?',(parent,)).fetchall():
                self.db.execute('UPDATE items SET due=? WHERE id=?',((datetime.fromisoformat(child['due'])+delta).isoformat(),child['id']))
                shift(child['id'])
        with self.db:
            changed=self.db.execute("UPDATE items SET due=? WHERE id=? AND done=0", (new.isoformat(), uid)).rowcount > 0
            if changed and row['is_group'] and delta.days:
                shift(uid)
            return changed

    def projects(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT value FROM projects ORDER BY id")]

    def project(self, uid):
        row = self.db.execute("SELECT value FROM projects WHERE id=?", (uid,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_project(self, project):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO projects VALUES (?, ?)",
                            (project["id"], json.dumps(project, ensure_ascii=False)))

    def delete_project(self, uid):
        with self.db:
            self.db.execute("DELETE FROM items WHERE project=?", (uid,))
            return self.db.execute("DELETE FROM projects WHERE id=?", (uid,)).rowcount > 0

    def stages(self, uid):
        return [dict(r) for r in self.db.execute("SELECT * FROM items WHERE project=? ORDER BY due, id", (uid,))]

    def seed_projects(self, document, tz):
        """Adds hackathons from the JSON once; edits and deletions in the bot are never overwritten."""
        from datetime import date, datetime, time
        seeded = set(self.get("projects_seeded", []))
        with self.db:
            for source in document["hackathons"]:
                if source["id"] in seeded:
                    continue
                stages = source.get("stages", [])
                project = {k: v for k, v in source.items() if k != "stages"}
                self.db.execute("INSERT OR REPLACE INTO projects VALUES (?, ?)",
                                (project["id"], json.dumps(project, ensure_ascii=False)))
                for stage in stages:
                    if stage["kind"] == "allday":
                        due = datetime.combine(date.fromisoformat(stage["date"]), time(), tzinfo=tz)
                        kind, duration, all_day = "event", 1440 * stage.get("days", 1), 1
                    else:
                        due = datetime.fromisoformat(stage.get("due") or stage["start"]).replace(tzinfo=tz)
                        kind, duration, all_day = stage["kind"], stage.get("duration", 0), 0
                    self.db.execute(
                        "INSERT INTO items(kind,title,due,duration,project,note,all_day) VALUES (?,?,?,?,?,?,?)",
                        (kind, stage["title"], due.isoformat(), duration, project["id"], stage.get("note", ""), all_day))
                seeded.add(project["id"])
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('projects_seeded', ?)",
                            (json.dumps(sorted(seeded)),))

    def delivered(self, key):
        return self.db.execute("SELECT 1 FROM deliveries WHERE key=?", (key,)).fetchone() is not None

    def mark(self, key, sent):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO deliveries VALUES (?,?)", (key, sent))

    def close(self):
        self.db.close()

    def checked(self, key):
        row = self.db.execute('SELECT done FROM checks WHERE key=?', (key,)).fetchone()
        return bool(row[0]) if row else False

    def attendance(self, key):
        row = self.db.execute('SELECT status FROM attendance WHERE key=?', (key,)).fetchone()
        return row[0] if row else 'present' if self.checked(key) else 'pending'

    def set_attendance(self, key, status):
        if status not in ('present', 'absent', 'pending'):
            raise ValueError('Неверная отметка посещения')
        with self.db:
            if status == 'pending':
                self.db.execute('DELETE FROM attendance WHERE key=?', (key,))
            else:
                self.db.execute('INSERT OR REPLACE INTO attendance VALUES (?,?)', (key,status))
            self.db.execute('INSERT OR REPLACE INTO checks VALUES (?,?)', (key,int(status=='present')))

    def check(self, key, done):
        with self.db:
            if key.startswith(('uni:', 'uni-extra:')):
                self.db.execute('DELETE FROM attendance WHERE key=?', (key,))
            self.db.execute('INSERT OR REPLACE INTO checks VALUES (?,?)', (key, int(done)))

    def override(self, key):
        row = self.db.execute('SELECT value FROM overrides WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_override(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO overrides VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))
