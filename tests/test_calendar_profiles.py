from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from urllib.parse import urlencode

from campus_bot.calendar_import import apply, feed_url, occurrences
from campus_bot.config import Config
from campus_bot.miniapp import verify_init_data
from campus_bot.profiles import Profiles
from campus_bot.storage import Store


class CalendarImportTests(unittest.TestCase):
    ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example//Calendar//EN
BEGIN:VEVENT
UID:meeting
DTSTART;TZID=Europe/Berlin:20260322T120000
DTEND;TZID=Europe/Berlin:20260322T130000
RRULE:FREQ=WEEKLY;COUNT=4
EXDATE;TZID=Europe/Berlin:20260405T120000
SUMMARY:Practice
END:VEVENT
BEGIN:VEVENT
UID:all-day
DTSTART;VALUE=DATE:20260330
DTEND;VALUE=DATE:20260401
SUMMARY:Two days
END:VEVENT
END:VCALENDAR
"""

    def test_supported_and_invalid_links(self):
        self.assertEqual(feed_url("webcal://p34-caldav.icloud.com/published/2/sample"),
                         "https://p34-caldav.icloud.com/published/2/sample")
        self.assertEqual(feed_url("https://calendar.google.com/calendar/ical/demo%40gmail.com/private-sample/basic.ics"),
                         "https://calendar.google.com/calendar/ical/demo%40gmail.com/private-sample/basic.ics")
        for invalid in (
            "https://calendar.google.com.evil.test/calendar/ical/demo/public/basic.ics",
            "https://other@calendar.google.com/calendar/ical/demo/public/basic.ics",
            "https://calendar.google.com/calendar/ical/%2e%2e/public/basic.ics",
            "https://caldav.icloud.com:8443/published/2/demo",
            "webcal://localhost/published/2/demo",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                feed_url(invalid)

    def test_recurrence_timezones_all_day_and_reimport(self):
        now = datetime(2026, 3, 27, tzinfo=timezone.utc)
        rows = occurrences(self.ICS, now)
        self.assertEqual(len(rows), 4)
        meetings = sorted(row[1] for row in rows.values() if row[0] == "Practice")
        self.assertEqual(meetings, ["2026-03-22T11:00:00+00:00", "2026-03-29T10:00:00+00:00",
                                    "2026-04-12T10:00:00+00:00"])
        all_day = next(row for row in rows.values() if row[0] == "Two days")
        self.assertEqual(all_day[2:], (2880, "", 1))
        store = Store(":memory:")
        self.addCleanup(store.close)
        self.assertEqual(apply(store, "sample", rows)["added"], 4)
        self.assertEqual(apply(store, "sample", rows)["unchanged"], 4)
        edited = occurrences(self.ICS.replace(b"SUMMARY:Practice", b"SUMMARY:New title"), now)
        self.assertEqual(apply(store, "sample", edited)["updated"], 3)
        self.assertEqual(len(store.items("event")), 4)


class ProfileTests(unittest.TestCase):
    def test_calendar_and_settings_are_isolated(self):
        with TemporaryDirectory() as root:
            parent = Path(root)
            profiles = Profiles(Config("test:token", 0, timezone.utc, parent, parent / "empty.json", public_mode=True))
            root_store = Store(parent / "bot.sqlite3")
            root_store.add_item("task", "Private", "2026-09-30T09:30:00+00:00")
            with self.assertRaises(PermissionError):
                profiles.open(10)
            _, first = profiles.open(10, register=True)
            _, second = profiles.open(20, register=True)
            try:
                first.set("group_name", "One")
                first.add_item("task", "First", "2026-09-30T11:30:00+00:00")
                second.add_item("task", "Second", "2026-09-30T11:30:00+00:00")
                row = {"uid": ("First event", "2026-09-30T10:00:00+00:00", 60, "", 0)}
                apply(first, "source", row)
                self.assertEqual([r["title"] for r in second.items()], ["Second"])
                self.assertEqual(second.get("group_name"), "")
                self.assertEqual([r["title"] for r in root_store.items()], ["Private"])
                self.assertCountEqual(profiles.actors(), [10, 20])
            finally:
                first.close()
                second.close()
                root_store.close()

    def test_public_actor_is_derived_from_telegram_signature(self):
        token = "test:token"
        stamp = int(time.time())
        fields = {"auth_date": str(stamp), "user": json.dumps({"id": 20})}
        data = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.digest(b"WebAppData", token.encode(), sha256)
        fields["hash"] = hmac.new(secret, data.encode(), sha256).hexdigest()
        self.assertEqual(verify_init_data(urlencode(fields), token, 0, stamp, public_mode=True), 20)
        with self.assertRaises(PermissionError):
            verify_init_data(urlencode(fields), token, 0, stamp + timedelta(hours=2).total_seconds(), public_mode=True)
        fields["user"] = json.dumps({"id": 10})
        with self.assertRaises(PermissionError):
            verify_init_data(urlencode(fields), token, 0, stamp, public_mode=True)
