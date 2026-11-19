"""An isolated SQLite profile per Telegram account in the shared edition."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import logging
import re

from .bot import Bot
from .config import ROOT
from .schedule import Schedule
from .storage import Store
from .weather import Weather

log = logging.getLogger(__name__)


class Profiles:
    def __init__(self, config):
        self.config = config
        self.directory = config.data_dir / "profiles"

    def scope(self, actor):
        if type(actor) is not int or not 0 < actor < 2**52:
            raise PermissionError("Войдите через Telegram.")
        return replace(
            self.config,
            owner_id=actor,
            data_dir=self.directory / str(actor),
            lessons_path=ROOT / "data" / "empty_schedule.json",
            mail_user="",
            mail_password="",
        )

    def open(self, actor, *, register=False):
        cfg = self.scope(actor)
        path = cfg.data_dir / "bot.sqlite3"
        if not register and not path.is_file():
            raise PermissionError("Сначала отправьте /start боту в Telegram.")
        store = Store(path)
        # The transaction also handles two first requests arriving at once.
        try:
            if not store.get("public_profile"):
                if not register:
                    raise PermissionError("Сначала отправьте /start боту в Telegram.")
                with store.db:
                    store.db.execute("BEGIN IMMEDIATE")
                    store.db.executemany("INSERT OR IGNORE INTO settings VALUES (?, ?)", [
                        ("group_id", "0"), ("group_name", '""'),
                        ("weather_times", "[]"), ("subscribed", "false"),
                        ("notifications", "true"), ("public_profile", "true"),
                    ])
        except BaseException:
            store.close()
            raise
        return cfg, store

    def actors(self):
        for path in self.directory.glob("*/bot.sqlite3"):
            value = path.parent.name
            if re.fullmatch(r"[1-9][0-9]{0,15}", value) and int(value) < 2**52:
                yield int(value)


def set_group(store, group_id, name):
    if not re.fullmatch(r"[0-9]{1,9}", str(group_id)):
        raise ValueError("Укажите числовой ID группы или 0 для отключения.")
    group_id = int(group_id)
    name = " ".join(str(name or "").split())[:80]
    store.set("group_id", group_id)
    store.set("group_name", (name or f"Группа {group_id}") if group_id else "")
    store.set("pending_change", None)


class ProfileBot(Bot):
    async def command(self, cmd, args):
        if cmd in ("/accounts", "/invite", "/web", "/reconcile", "/mail"):
            await self.reply("У каждого аккаунта свой кабинет. Откройте приложение командой /app.")
        elif cmd == "/group":
            group_id, _, name = args.partition(" ")
            if not group_id:
                await self.reply("Расписание Cube — /group ID Название. Отключить — /group 0.")
                return
            set_group(self.store, group_id, name)
            await self.reply("Группа сохранена." if self.store.get("group_id") else "Расписание вуза отключено.")
        elif cmd == "/help":
            await self.reply(
                "✳️ День · команды\n\n"
                "/menu — главное меню\n/app — приложение\n/profile — ваш профиль\n"
                "/week — неделя\n/month — месяц\n/import — импорт из Google и Apple Calendar\n"
                "/group ID Название — подключить расписание Cube\n"
                "/add завтра 18:00 Сдать работу — задача\n/dayplan — задачи дня\n"
                "/stats — аналитика\n/gym — тренировки\n/food — питание\n/sleep — сон\n"
                "/students — занятия и оплаты\n/zp — доход\n"
                "/settings — настройки\n/weather — прогноз и настройка города\n"
                "/resume — включить сводки\n/pause — поставить на паузу"
            )
        elif cmd == "/weather":
            if args == "off":
                self.store.set("weather_location", None)
                await self.reply("Прогноз выключен.")
            elif args:
                latitude, longitude, name = args.split(maxsplit=2)
                latitude, longitude = float(latitude), float(longitude)
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or len(name) > 80:
                    raise ValueError("Проверьте координаты и название города.")
                self.store.set("weather_location", {
                    "latitude": round(latitude, 4), "longitude": round(longitude, 4), "name": name,
                })
                await self.reply(await self.weather.today())
            else:
                forecast = await self.weather.today()
                await self.reply(forecast or "Укажите город: /weather 52.52 13.405 Берлин. Отключить — /weather off.")
        elif cmd == "/start":
            self.background(self.bind_app_menu(self.config.owner_id))
            await self.chat.home()
        else:
            await super().command(cmd, args)


class PublicBot(Bot):
    """One Telegram poller and a bounded notification batch for all profiles."""
    def __init__(self, config, store, schedule, weather, telegram):
        super().__init__(config, store, schedule, weather, telegram)
        self.profiles = Profiles(config)

    def startup_accounts(self):
        return ()

    def profile_bot(self, actor, register=False):
        config, store = self.profiles.open(actor, register=register)
        try:
            bot = ProfileBot(config, store, Schedule(store, config), Weather(store, config.timezone), self.telegram)
        except BaseException:
            store.close()
            raise
        bot.assistant.busy = self.assistant.busy
        return bot

    async def handle(self, update):
        callback = update.get("callback_query")
        message = callback.get("message") if callback else update.get("message")
        sender = (callback or message or {}).get("from", {}).get("id")
        chat = (message or {}).get("chat", {})
        if type(sender) is not int or chat.get("type") != "private" or chat.get("id") != sender:
            return
        command = (message.get("text") or "").strip().partition(" ")[0].split("@")[0].lower()
        if not callback and command == "/id":
            await self.telegram.send(sender, f"Ваш Telegram ID: {sender}")
            return
        try:
            bot = self.profile_bot(sender, register=not callback and command == "/start")
        except PermissionError as exc:
            if callback:
                await self.telegram.call("answerCallbackQuery", callback_query_id=callback["id"], text=str(exc))
            else:
                await self.telegram.send(sender, str(exc))
            return
        try:
            await bot._handle_owner(update)
        finally:
            if bot._background_tasks:
                self.background(self.close_after_background(bot))
            else:
                bot.store.close()

    @staticmethod
    async def close_after_background(bot):
        try:
            while bot._background_tasks:
                await asyncio.gather(*tuple(bot._background_tasks), return_exceptions=True)
        finally:
            bot.store.close()

    async def tick_profile(self, actor):
        try:
            bot = self.profile_bot(actor)
        except PermissionError:
            return
        except Exception:
            log.exception("Не удалось открыть профиль для рассылки")
            return
        try:
            if bot.store.get("subscribed"):
                # On-demand cache expiry handles public schedule refreshes.
                # Avoid one forced upstream warm-up for each profile per tick.
                until = bot.now() + timedelta(days=1)
                bot.scheduler.next_sync = bot.scheduler.next_weather = until
                bot.scheduler.weather_day = bot.now().date()
                await asyncio.wait_for(bot.scheduler.tick(), timeout=30)
        except Exception:
            log.exception("Не удалось обновить профиль для рассылки")
        finally:
            await self.close_after_background(bot)

    async def run_notifications(self):
        from itertools import islice
        while True:
            actors = iter(self.profiles.actors())
            while batch := tuple(islice(actors, 12)):
                await asyncio.gather(*(self.tick_profile(actor) for actor in batch))
            await asyncio.sleep(20)
