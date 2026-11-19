"""Logs with tracebacks but without secrets.

Unexpected errors are logged with the full traceback so they can be fixed, and every
record — message and traceback — passes through a filter that cuts out the bot token,
API keys, bearer headers and any secret value handed to `install`.
"""
import logging
import os
import re
from urllib.parse import quote

# Read when a record is written: .env is loaded after logging is set up.
SECRET_ENV = ('BOT_TOKEN', 'MAIL_PASSWORD', 'OPENAI_API_KEY', 'TELEGRAM_PROXY_URL', 'AI_PROXY_URL')

PATTERNS = [
    # Telegram bot token, also right after "bot" inside api URLs (so no \b before the digits).
    (re.compile(r'(?<!\d)\d{6,12}(?::|%3[Aa])[A-Za-z0-9_-]{30,}'), '<bot-token>'),
    (re.compile(r'\bsk-[A-Za-z0-9_-]{15,}'), '<api-key>'),
    (re.compile(r'(?i)(bearer\s+)[^\s\'"]+'), r'\1<secret>'),
]


class Redact(logging.Filter):
    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def clean(self, text):
        for pattern, replacement in PATTERNS:
            text = pattern.sub(replacement, text)
        for secret in self.secrets + [os.getenv(k, '') for k in SECRET_ENV]:
            if secret and len(secret) >= 6:
                # Longest form first, so the plain value inside it is not cut in half.
                for form in sorted({secret, quote(secret, safe='')}, key=len, reverse=True):
                    text = text.replace(form, '<secret>')
        return text

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:  # mismatched %-arguments: still log something, never break the caller
            message = f'{record.msg} {record.args!r}'
        record.msg = self.clean(str(message))
        record.args = ()
        if record.exc_info:
            # Format the traceback once here, clean it, and let the handler print the cleaned text.
            record.exc_text = self.clean(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self.clean(record.exc_text)
        if record.stack_info:
            record.stack_info = self.clean(record.stack_info)
        return True


def install(secrets=(), logger=None):
    """Attach the filter to every handler of `logger` (the root logger by default), once."""
    logger = logger or logging.getLogger()
    for handler in logger.handlers:
        if not any(isinstance(f, Redact) for f in handler.filters):
            handler.addFilter(Redact(secrets))
