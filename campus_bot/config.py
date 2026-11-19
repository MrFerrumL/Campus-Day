from dataclasses import dataclass
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    """Small .env reader; the process environment always has priority."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip().isidentifier():
            raise ValueError("Неверная строка .env")
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


LESSONS_FILE = "personal_schedule.json"


def lessons_file(data_dir: Path) -> Path:
    """The lesson rules with pupils' names live outside git: LESSONS_PATH, then the
    data folder. The tracked data/personal_schedule.json only has invented names."""
    explicit = os.getenv("LESSONS_PATH", "").strip()
    if explicit:
        return Path(explicit).resolve()
    private = data_dir / LESSONS_FILE
    return private if private.is_file() else ROOT / "data" / LESSONS_FILE


@dataclass(frozen=True)
class Config:
    token: str
    owner_id: int
    timezone: ZoneInfo
    data_dir: Path
    lessons_path: Path
    mail_user: str = ""
    mail_password: str = ""
    mail_host: str = "imap.gmail.com"
    public_mode: bool = False

    @classmethod
    def load(cls, require_token: bool = True):
        load_env(ROOT / ".env")
        token = os.getenv("BOT_TOKEN", "").strip()
        if require_token and (not token or ":" not in token):
            raise ValueError("Заполните BOT_TOKEN в .env (см. .env.example)")
        data_dir = Path(os.getenv("DATA_DIR", str(ROOT / "runtime"))).resolve()
        public_mode = os.getenv("BOT_MODE", "private") == "public"
        if public_mode:
            if os.getenv("OWNER_ID", "") not in ("", "0") or any(os.getenv(key) for key in (
                "MAIL_USER", "MAIL_PASSWORD", "REOLLITY_USER", "REOLLITY_PASSWORD", "OPENAI_API_KEY"
            )):
                raise ValueError("Для BOT_MODE=public используйте отдельный .env без личных интеграций")
            data_dir /= "public"
        return cls(
            token, int(os.getenv("OWNER_ID", "0") or 0),
            ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow")),
            data_dir,
            lessons_file(data_dir),
            os.getenv("MAIL_USER", "").strip(),
            # Google shows app passwords in groups of four; IMAP expects them without spaces.
            os.getenv("MAIL_PASSWORD", "").replace(" ", ""),
            os.getenv("MAIL_IMAP_HOST", "imap.gmail.com").strip(),
            public_mode,
        )
