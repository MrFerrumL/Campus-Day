FROM python:3.12-slim
ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/runtime APP_VERSION=$APP_VERSION
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 bot \
    && mkdir -p /app/runtime \
    && chown bot:bot /app/runtime
COPY campus_bot ./campus_bot
COPY data ./data
COPY connect_miniapp.py .
USER bot
# Liveness only: the Mini App answers and the database opens. Telegram reachability
# is reported in the body and handled by the host watchdog, not by restarts here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request as u; u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:%s/health' % os.getenv('MINI_APP_PORT', '8765'), timeout=4)"]
CMD ["python", "-m", "campus_bot"]
