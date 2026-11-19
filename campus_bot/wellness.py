"""Private fitness, nutrition and sleep journal, shared by the owner's linked accounts."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import math
from uuid import uuid4
import json
from .progress import progress as training_progress
from . import activity, daily
from .fitness_catalog import EXERCISES, GEAR, GROUPS, KINDS, MUSCLES, OLD_MOTIONS, PROGRAMS

PHOTOS = {e['id'] for e in EXERCISES}


def muscle_list(value, limit):
    """Validated list of muscle keys from the catalog."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(m, str) or m not in MUSCLES for m in value):
        raise ValueError('Выберите мышцы из списка')
    return list(dict.fromkeys(value))


def with_photo(row):
    """A custom exercise saved before photos existed gets the photo of its old drawn motion."""
    row = dict(row)
    row.setdefault('photo', OLD_MOTIONS.get(row.get('motion'), 'squat'))
    row.setdefault('primary', [])
    row.setdefault('secondary', [])
    row.setdefault('kind', 'strength')
    row['custom'] = True
    return row


def workout_entry(ex, target='', rest=90, sets=3):
    return dict(id=uuid4().hex[:10], exercise_id=ex['id'], name=ex['name'], photo=ex['photo'], unit=ex.get('unit', 'reps'),
                target=target, rest_seconds=rest, sets=[dict(weight=None, reps=None, done=False) for _ in range(sets)])


def text(value,limit=300,required=True):
    if not isinstance(value,str) or len(value.strip())>limit or (required and not value.strip()):
        raise ValueError('Проверьте название или заметку')
    return value.strip()


def number(value,low,high,optional=False):
    if optional and (value is None or value==''):return None
    if isinstance(value,bool):raise ValueError('Введите число')
    try:n=float(str(value).replace(',','.'))
    except (ValueError,TypeError):raise ValueError('Введите число') from None
    if not math.isfinite(n) or not low<=n<=high:raise ValueError('Число вне допустимого диапазона')
    return round(n,2)


class Wellness:
    def __init__(self,store,tz):self.store,self.tz=store,tz

    def rows(self,kind):
        return [json.loads(r[0]) for r in self.store.db.execute('SELECT value FROM wellness WHERE kind=? ORDER BY day DESC,id',(kind,))]

    def get(self,uid,kind=None):
        row=self.store.db.execute('SELECT kind,value FROM wellness WHERE id=?',(uid,)).fetchone()
        if not row or (kind and row[0]!=kind):raise ValueError('Запись не найдена')
        return json.loads(row[1])

    def put(self,kind,row):
        self.store.db.execute('INSERT OR REPLACE INTO wellness VALUES (?,?,?,?)',
                              (row['id'],kind,row.get('day',''),json.dumps(row,ensure_ascii=False)))
        return row

    def exercises(self):return deepcopy(EXERCISES)+[with_photo(r) for r in self.rows('exercise')]

    def exercise(self,uid):
        row=next((e for e in self.exercises() if e['id']==uid),None)
        if not row:raise ValueError('Упражнение не найдено')
        return row

    def program_days(self,days):
        if not isinstance(days,list) or not 1<=len(days)<=10:raise ValueError('От 1 до 10 тренировочных дней')
        result=[]
        for day in days:
            entries=day['exercises']
            if not isinstance(entries,list) or len(entries)>30:raise ValueError('До 30 упражнений в тренировке')
            exercises=[]
            for entry in entries:
                self.exercise(entry['exercise_id'])
                sets=number(entry['sets'],1,20);rest=number(entry.get('rest_seconds',90),0,900)
                if sets!=int(sets) or rest!=int(rest):raise ValueError('Подходы и отдых — целые числа')
                exercises.append(dict(exercise_id=entry['exercise_id'],sets=int(sets),reps=text(entry.get('reps','8–12'),60),
                                      rest_seconds=int(rest),note=text(entry.get('note',''),500,False)))
            result.append(dict(id=str(day.get('id') or uuid4().hex[:8])[:60],name=text(day['name'],100),exercises=exercises))
        if len({d['id'] for d in result})!=len(result):raise ValueError('Повторяющиеся дни программы')
        return result

    def mutate(self,action,body,now=None):
        now=now or datetime.now(self.tz)
        with self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            return self._mutate(action,body,now)

    def _mutate(self,action,body,now):
        if action in ('wellness-steps','wellness-activity'):
            kind,row=activity.build(self,action,body,now)
            return self.put(kind,row)
        if action=='wellness-delete':
            kind=body['kind'];row=self.get(body['id'],kind)
            if kind not in ('meal','water','sleep','exercise','program','workout','activity','steps'):raise ValueError('Неверный тип')
            if kind=='exercise' and any(e['exercise_id']==row['id'] for p in self.rows('program') for d in p['days'] for e in d['exercises']):
                raise ValueError('Сначала уберите упражнение из программ')
            self.store.db.execute('DELETE FROM wellness WHERE id=?',(row['id'],));return dict(ok=True)
        if action=='wellness-settings':
            old=self.store.get('wellness_settings',{})
            for field,low,high in [('calories',0,15000),('protein',0,1000),('water_ml',0,10000),('sleep_hours',0,16),('workouts_week',0,14),('weight_kg',30,300),('height_cm',100,250)]:
                if field in body:old[field]=number(body[field],low,high,True)
            if 'goal' in body:old['goal']=text(body['goal'],150,False)
            if 'remind_days' in body:
                days=body['remind_days']
                if not isinstance(days,list) or any(type(d) is not int or not 0<=d<=6 for d in days):raise ValueError('Дни недели: от пн до вс')
                old['remind_days']=sorted(set(days))
            if 'remind_time' in body:
                try:old['remind_time']=datetime.strptime(str(body['remind_time']),'%H:%M').strftime('%H:%M')
                except ValueError:raise ValueError('Время напоминания: ЧЧ:ММ') from None
            self.store.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('wellness_settings',json.dumps(old,ensure_ascii=False)))
            return dict(ok=True)
        if action=='wellness-program':
            if body.get('template'):
                template=next((p for p in PROGRAMS if p['id']==body['template']),None)
                if not template:raise ValueError('Шаблон не найден')
                body=dict(deepcopy(template),id=None)
            uid=body.get('id') or 'program-'+uuid4().hex[:12]
            if body.get('id'):self.get(uid,'program')
            return self.put('program',dict(id=uid,name=text(body['name'],100),note=text(body.get('note',''),1000,False),days=self.program_days(body['days'])))
        if action=='wellness-exercise':
            uid=body.get('id') or 'exercise-'+uuid4().hex[:12]
            old=self.get(uid,'exercise') if body.get('id') else {}
            photo=body.get('photo') or OLD_MOTIONS.get(body.get('motion'),body.get('motion') or 'squat')
            if not isinstance(photo,str):raise ValueError('Неверный вид упражнения')
            unit=body.get('unit','reps');kind=body.get('kind','strength')
            if photo not in PHOTOS or unit not in ('reps','seconds','minutes') or kind not in KINDS:raise ValueError('Неверный вид упражнения')
            tips=body.get('tips',[])
            if not isinstance(tips,list) or len(tips)>8:raise ValueError('До 8 заметок')
            primary=muscle_list(body.get('primary'),4);secondary=[m for m in muscle_list(body.get('secondary'),6) if m not in primary]
            muscles=text(body.get('muscles',''),100,False) or ' · '.join(MUSCLES[m] for m in primary) or old.get('muscles','')
            return self.put('exercise',dict(id=uid,name=text(body['name'],100),muscles=muscles,primary=primary,secondary=secondary,
                equipment=text(body.get('equipment',''),100,False),photo=photo,kind=kind,unit=unit,tips=[text(t,300) for t in tips]))
        if action=='workout-start':
            active=next((w for w in self.rows('workout') if w['status']=='active'),None)
            if active:return active
            if body.get('program'):
                p=self.get(body['program'],'program');day=next((d for d in p['days'] if d['id']==body['program_day']),None)
                if not day:raise ValueError('День программы не найден')
                name=p['name']+' · '+day['name'];entries=day['exercises']
            else:name=text(body.get('name','Свободная тренировка'),150);entries=[]
            exercises=[]
            for e in entries:
                exercises.append(workout_entry(self.exercise(e['exercise_id']),e['reps'],e['rest_seconds'],e['sets']))
            return self.put('workout',dict(id='workout-'+uuid4().hex[:12],day=now.date().isoformat(),started=now.isoformat(),ended=None,
                name=name,status='active',note='',exercises=exercises))
        if action in ('workout-sets','workout-add','workout-finish','workout-remove','workout-move'):
            row=self.get(body['id'],'workout')
            if row['status']!='active':raise ValueError('Тренировка завершена')
            if action=='workout-add':
                if len(row['exercises'])>=30:raise ValueError('До 30 упражнений')
                row['exercises'].append(workout_entry(self.exercise(body['exercise_id'])))
            elif action in ('workout-remove','workout-move'):
                i=next((i for i,e in enumerate(row['exercises']) if e['id']==body.get('exercise')),None)
                if i is None:raise ValueError('Упражнение не найдено в тренировке')
                if action=='workout-remove':row['exercises'].pop(i)
                else:
                    step=body.get('step')
                    if type(step) is not int or step not in (-1,1):raise ValueError('Сдвиг на одну позицию')
                    j=i+step
                    if 0<=j<len(row['exercises']):row['exercises'][i],row['exercises'][j]=row['exercises'][j],row['exercises'][i]
            elif action=='workout-finish':
                row.update(status='done',ended=now.isoformat(),note=text(body.get('note',''),1000,False))
            else:
                ex=next((e for e in row['exercises'] if e['id']==body['exercise']),None)
                sets=body['sets']
                if not ex or not isinstance(sets,list) or not 1<=len(sets)<=30:raise ValueError('Проверьте подходы')
                cleaned=[]
                for item in sets:
                    if type(item.get('done')) is not bool:raise ValueError('Неверная отметка')
                    weight=number(item.get('weight'),0,1000,True);reps=number(item.get('reps'),0,10000,True)
                    if item['done'] and (reps is None or reps<=0):raise ValueError('Запишите повторения или длительность выполненного подхода')
                    cleaned.append(dict(weight=weight,reps=reps,done=item['done']))
                ex['sets']=cleaned
            return self.put('workout',row)
        if action in ('wellness-meal','wellness-water','wellness-sleep'):
            kind=action.removeprefix('wellness-');uid=body.get('id') or kind+'-'+uuid4().hex[:12]
            if body.get('id'):self.get(uid,kind)
            day=date.fromisoformat(body.get('day') or now.date().isoformat())
            if day>now.date():raise ValueError('Журнал — для сегодняшних и прошедших дней')
            row=dict(id=uid,day=day.isoformat())
            if kind=='meal':
                row.update(name=text(body['name'],150),time=datetime.strptime(body.get('time') or now.strftime('%H:%M'),'%H:%M').strftime('%H:%M'),
                    note=text(body.get('note',''),500,False))
                for field,upper in [('calories',10000),('protein',1000),('fat',1000),('carbs',2000)]:row[field]=number(body.get(field),0,upper,True)
            elif kind=='water':row['ml']=number(body['ml'],1,5000)
            else:
                start=datetime.fromisoformat(body['start']);end=datetime.fromisoformat(body['end'])
                start=start.replace(tzinfo=self.tz) if start.tzinfo is None else start.astimezone(self.tz)
                end=end.replace(tzinfo=self.tz) if end.tzinfo is None else end.astimezone(self.tz)
                minutes=round((end-start).total_seconds()/60)
                if end.date()!=day or not 1<=minutes<=1440 or end>now:raise ValueError('Проверьте время сна и пробуждения')
                for other in self.rows('sleep'):
                    if other['id']!=uid and datetime.fromisoformat(other['start'])<end and start<datetime.fromisoformat(other['end']):
                        raise ValueError('Этот период сна уже записан. Измените существующую запись.')
                quality=number(body.get('quality',3),1,5)
                if quality!=int(quality):raise ValueError('Оценка сна: от 1 до 5')
                row.update(start=start.isoformat(),end=end.isoformat(),minutes=minutes,quality=int(quality),note=text(body.get('note',''),500,False))
            return self.put(kind,row)
        raise ValueError('Неизвестное действие журнала')

    def recent_workouts(self):
        """The newest 400 workouts: years of training for one person, and each request stays light."""
        return [json.loads(r[0]) for r in self.store.db.execute(
            "SELECT value FROM wellness WHERE kind='workout' ORDER BY day DESC, id DESC LIMIT 400")]

    def last_results(self,recent=None):
        """Finished sets of the most recent workout that had each exercise: «в прошлый раз»."""
        recent=self.recent_workouts() if recent is None else recent
        done=sorted((w for w in recent if w['status']=='done'),key=lambda w:w.get('ended') or w['day'],reverse=True)
        last={}
        for w in done:
            for e in w['exercises']:
                sets=[dict(weight=s['weight'],reps=s['reps']) for s in e['sets'] if s['done']]
                if sets and e['exercise_id'] not in last:last[e['exercise_id']]=dict(day=w['day'],unit=e.get('unit','reps'),sets=sets)
        return last

    def today_card(self,now=None):
        """Today's food, water, sleep and training for the Today screen: one indexed day, nothing heavy."""
        now=now or datetime.now(self.tz);day=now.date()
        # One query per kind uses the (kind, day) index.
        rows={kind:[json.loads(r[0]) for r in self.store.db.execute('SELECT value FROM wellness WHERE kind=? AND day=?',(kind,day.isoformat()))]
              for kind in ('meal','water','sleep','workout')}
        active=next((json.loads(r[0]) for r in self.store.db.execute(
            "SELECT value FROM wellness WHERE kind='workout' ORDER BY day DESC LIMIT 20") if json.loads(r[0])['status']=='active'),None)
        return daily.card(rows,self.store.get('wellness_settings',{}),active,day)

    def overview(self,day=None,now=None):
        now=now or datetime.now(self.tz);day=day or now.date()
        first=day-timedelta(days=27)
        records={k:[r for r in self.rows(k) if first.isoformat()<=r['day']<=day.isoformat()] for k in ('meal','water','sleep','workout','activity','steps')}
        active=next((r for r in self.rows('workout') if r['status']=='active'),None)
        recent=self.recent_workouts()
        today=[r for r in records['meal'] if r['day']==day.isoformat()]
        week=day-timedelta(days=6);sleeps=[r for r in records['sleep'] if r['day']>=week.isoformat()]
        return dict(day=day.isoformat(),exercises=self.exercises(),templates=deepcopy(PROGRAMS),programs=self.rows('program'),active=active,
            last=self.last_results(recent),progress=training_progress(recent,day),muscles=dict(MUSCLES),groups={k:dict(name=v[0],muscles=list(v[1])) for k,v in GROUPS.items()},gear=dict(GEAR),
            records=records,settings=self.store.get('wellness_settings',{}),
            activity=activity.day_summary(records,self.store.get('wellness_settings',{}) or {},day.isoformat()),
            activity_types={k:v[0] for k,v in activity.TYPES.items()},
            week=daily.week(records,day),frequent=daily.frequent(records['meal']),
            summary=dict(calories=round(sum(r['calories'] or 0 for r in today),2),missing_calories=sum(r['calories'] is None for r in today),
                protein=round(sum(r['protein'] or 0 for r in today),2),fat=round(sum(r['fat'] or 0 for r in today),2),carbs=round(sum(r['carbs'] or 0 for r in today),2),
                water_ml=sum(r['ml'] for r in records['water'] if r['day']==day.isoformat()),
                sleep_average=round(sum(r['minutes'] for r in sleeps)/len({r['day'] for r in sleeps})) if sleeps else None,
                sleep_days=len({r['day'] for r in sleeps}),workouts_week=sum(r['status']=='done' and r['day']>=week.isoformat() for r in records['workout'])))
