import asyncio
import http.client
import json
import logging
import os
import select
import socket
import ssl
import threading
import time
from collections import deque
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


class ServiceError(Exception):
    """Intentionally omits request URLs: Telegram URLs contain the bot secret."""

    def __init__(self, service, status=0, retry_after=0):
        self.status, self.retry_after = status, retry_after
        super().__init__(f"{service}: HTTP {status}" if status else f"{service}: сеть недоступна")


def request_json(url, payload=None, timeout=15, service="Источник", open_url=None):
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    request = Request(url, data=body, headers={"User-Agent": os.getenv(
        "HTTP_USER_AGENT", "CampusDayBot/1.0 (https://github.com)"),
                                              "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with (open_url or urlopen)(request, timeout=timeout) as response:
            result = json.load(response)
            if isinstance(result, dict) and response.headers.get("Expires"):
                result["_http_expires"] = response.headers["Expires"]
            return result
    except HTTPError as exc:
        retry_after = 0
        try:
            retry_after = int(json.load(exc).get("parameters", {}).get("retry_after", 0))
        except (ValueError, TypeError):
            pass
        raise ServiceError(service, exc.code, retry_after) from None
    except (URLError, OSError, socket.timeout, ValueError):
        raise ServiceError(service) from None


async def get_json(url, service="Источник"):
    return await asyncio.to_thread(request_json, url, service=service)


TELEGRAM_HOST = "api.telegram.org"
TELEGRAM_TIMEOUT = 45
# Servers drop idle keep-alive sockets; older ones are closed instead of reused.
IDLE_SECONDS = 30
POOL_SIZE = 3
# Repeating these cannot create a second message or a second side effect.
IDEMPOTENT = frozenset({"getUpdates", "getMe", "getWebhookInfo", "deleteWebhook", "setMyCommands",
                        "setChatMenuButton", "answerCallbackQuery"})
# Raised while writing the request to a socket the server has already closed:
# nothing reached Telegram, so any method may be sent again on a new connection.
SEND_FAILURES = (BrokenPipeError, ConnectionResetError, ssl.SSLError, http.client.CannotSendRequest)
# Raised instead of a status line when the server closed an idle socket; the
# request may still have been processed, so only idempotent methods are repeated.
NO_RESPONSE = (http.client.RemoteDisconnected, http.client.BadStatusLine)
LATENCY_SAMPLES = 200
LATENCY_LOG_EVERY = 50


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    username: str | None = None
    password: str | None = None


def proxy_settings(proxy_url):
    """Parse TELEGRAM_PROXY_URL; the error text never repeats credentials."""
    if not proxy_url:
        return None
    proxy = urlsplit(proxy_url)
    if proxy.scheme not in {"socks5", "socks5h"} or not proxy.hostname:
        raise ValueError("TELEGRAM_PROXY_URL: требуется socks5h://host:port")
    return Proxy(proxy.hostname, proxy.port or 9050,
                 unquote(proxy.username) if proxy.username else None,
                 unquote(proxy.password) if proxy.password else None)


class SocksHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS through SOCKS5 with remote DNS; certificate and hostname are still verified."""

    def __init__(self, host, proxy, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.proxy = proxy

    def connect(self):
        import socks
        raw = socks.socksocket()
        try:
            raw.set_proxy(socks.SOCKS5, self.proxy.host, self.proxy.port, rdns=True,
                          username=self.proxy.username, password=self.proxy.password)
            raw.settimeout(self.timeout)
            raw.connect((self.host, self.port))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def closed_by_peer(connection):
    """An idle keep-alive socket that became readable has received EOF or a TLS alert."""
    sock = connection.sock
    if sock is None:
        return True
    try:
        readable, _, _ = select.select([sock], [], [], 0)
    except (OSError, ValueError):
        return True
    return bool(readable)


class TelegramTransport:
    """Keeps HTTPS connections to the Bot API open between calls.

    Through Tor every new connection costs a circuit stream, a TCP and a TLS
    handshake, several seconds in total; reusing the connection removes that
    from every reply. Thread-safe: calls arrive via asyncio.to_thread.
    """

    def __init__(self, token, proxy_url="", connect=None, clock=time.monotonic, is_closed=closed_by_peer):
        self._path = "/bot" + token + "/"
        self._proxy = proxy_settings(proxy_url)
        if self._proxy:
            import socks  # noqa: F401  (fail at startup, not on the first message)
        self._connect = connect or self._open
        self._clock = clock
        self._is_closed = is_closed
        self._idle = []
        self._lock = threading.Lock()
        self._latency = deque(maxlen=LATENCY_SAMPLES)
        self._calls = 0

    def _open(self, timeout):
        if self._proxy:
            return SocksHTTPSConnection(TELEGRAM_HOST, self._proxy, timeout)
        return http.client.HTTPSConnection(TELEGRAM_HOST, timeout=timeout,
                                           context=ssl.create_default_context())

    def _take(self, timeout):
        now = self._clock()
        with self._lock:
            while self._idle:
                connection, used = self._idle.pop()
                if now - used < IDLE_SECONDS and not self._is_closed(connection):
                    return connection, True
                connection.close()
        return self._connect(timeout), False

    def _give(self, connection):
        with self._lock:
            if len(self._idle) < POOL_SIZE:
                self._idle.append((connection, self._clock()))
                return
        connection.close()

    def close(self):
        with self._lock:
            idle, self._idle = self._idle, []
        for connection, _ in idle:
            connection.close()

    def request(self, method, payload=None, timeout=TELEGRAM_TIMEOUT):
        body = json.dumps(payload or {}, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": os.getenv("HTTP_USER_AGENT", "CampusDayBot/1.0")}
        for attempt in (1, 2):
            connection, reused = self._take(timeout)
            started = self._clock()
            phase = "send"
            try:
                connection.timeout = timeout
                if connection.sock is not None:
                    connection.sock.settimeout(timeout)
                connection.request("POST", self._path + method, body, headers)
                phase = "status"
                response = connection.getresponse()
                phase = "body"
                data = response.read()
            except BaseException as exc:
                connection.close()
                retry = reused and attempt == 1 and (
                    (phase == "send" and isinstance(exc, SEND_FAILURES))
                    or (phase == "status" and isinstance(exc, NO_RESPONSE) and method in IDEMPOTENT))
                if retry:
                    continue
                if isinstance(exc, (OSError, http.client.HTTPException, ValueError)):
                    # Only the type: messages of some errors (InvalidURL) contain the URL with the token.
                    log.info("Telegram %s: %s на этапе %s", method, type(exc).__name__, phase)
                    raise ServiceError("Telegram") from None
                raise
            if response.will_close:
                connection.close()
            else:
                self._give(connection)
            if method != "getUpdates":
                self._record((self._clock() - started) * 1000)
            return self._result(response.status, data)
        raise ServiceError("Telegram")

    @staticmethod
    def _result(status, data):
        try:
            result = json.loads(data)
        except ValueError:
            raise ServiceError("Telegram", status) from None
        if not isinstance(result, dict):
            raise ServiceError("Telegram", status)
        if status != 200 or not result.get("ok"):
            parameters = result.get("parameters") or {}
            try:
                retry_after = int(parameters.get("retry_after", 0))
            except (TypeError, ValueError):
                retry_after = 0
            raise ServiceError("Telegram", result.get("error_code") or status, retry_after)
        return result["result"]

    def _record(self, milliseconds):
        with self._lock:
            self._latency.append(milliseconds)
            self._calls += 1
            report = self._calls % LATENCY_LOG_EVERY == 0
        if report:
            summary = self.latency()
            log.info("Telegram: p50 %s мс, p95 %s мс за %s запросов", summary["p50"], summary["p95"], summary["n"])

    def latency(self):
        with self._lock:
            samples = sorted(self._latency)
        if not samples:
            return None
        pick = lambda share: int(samples[min(len(samples) - 1, int(share * len(samples)))])
        return {"p50": pick(0.5), "p95": pick(0.95), "n": len(samples)}


class Telegram:
    def __init__(self, token, transport=None):
        self._transport = transport or TelegramTransport(token, os.getenv("TELEGRAM_PROXY_URL", ""))
        self._send_locks = {}
        self._next_send = {}

    def latency(self):
        return self._transport.latency()

    async def call(self, method, **payload):
        return await asyncio.to_thread(self._transport.request, method, payload, TELEGRAM_TIMEOUT)

    async def send(self, chat_id, text, **kwargs):
        # Plain text avoids HTML/Markdown injection from titles and timetable data.
        while text:
            units, end = 0, 0
            for char in text:
                width = 2 if ord(char) > 0xFFFF else 1
                if units + width > 3500:
                    break
                units += width
                end += 1
            chunk = text[:end]
            if len(text) > end:
                split = chunk.rfind("\n")
                if split > 0:
                    chunk = chunk[:split + 1]
            async with self._send_locks.setdefault(chat_id,asyncio.Lock()):
                loop = asyncio.get_running_loop()
                delay = self._next_send.get(chat_id, 0) - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    await self.call("sendMessage", chat_id=chat_id, text=chunk,
                                    link_preview_options={"is_disabled": True}, **kwargs)
                finally:
                    self._next_send[chat_id] = loop.time() + 1.05
            text = text[len(chunk):]
