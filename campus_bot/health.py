"""Process health shared by the Telegram polling loop and the Mini App server.

Both run in one process, so a plain in-memory heartbeat is enough. Docker uses
GET /health as a liveness probe; the host watchdog reads the Telegram fields to
tell a stalled polling loop apart from a Tor outage.
"""
import os
import sqlite3
import time

# One long-poll lasts 30 s; several missed polls in a row mean the loop is stuck
# or Telegram is unreachable.
STALE_AFTER_SECONDS = 300


class Heartbeat:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.started = clock()
        self.last_poll = None

    def polled(self):
        self.last_poll = self._clock()

    def telegram(self):
        """Return (status, age in seconds) of the last successful getUpdates."""
        now = self._clock()
        if self.last_poll is None:
            age = now - self.started
            return ("waiting" if age < STALE_AFTER_SECONDS else "stale"), None
        age = now - self.last_poll
        return ("ok" if age < STALE_AFTER_SECONDS else "stale"), int(age)


HEARTBEAT = Heartbeat()


def database_ok(path):
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        try:
            connection.execute("SELECT 1 FROM settings LIMIT 1").fetchall()
        finally:
            connection.close()
        return True
    except sqlite3.Error:
        return False


def report(database_path, heartbeat=HEARTBEAT, latency=None):
    telegram, age = heartbeat.telegram()
    result = {
        "status": "ok" if database_ok(database_path) else "error",
        "telegram": telegram,
        "telegram_age_s": age,
        "uptime_s": int(heartbeat._clock() - heartbeat.started),
        "version": os.getenv("APP_VERSION", "dev"),
    }
    if latency:
        result["telegram_latency_ms"] = latency
    return result
