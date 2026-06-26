FROM python:3.12-slim

ARG SLA_BUILD_SHA=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SLA_BUILD_SHA=${SLA_BUILD_SHA} \
    SLA_APP_HOME=/data \
    SLA_DB_PATH=/data/db/sla_app.db \
    SLA_WEB_HOST=0.0.0.0 \
    SLA_WEB_PORT=8000 \
    SLA_PROXY_HEADERS=true \
    SLA_FORWARDED_ALLOW_IPS=127.0.0.1 \
    SLA_ROOT_PATH=

WORKDIR /app

RUN addgroup --system sla && adduser --system --ingroup sla sla

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN mkdir -p /data/suites /data/artifacts /data/db && chown -R sla:sla /data

USER sla
EXPOSE 8000

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import os, urllib.request; port = os.getenv('SLA_WEB_PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/readyz', timeout=3).read()"

CMD ["python", "-m", "sla_app.web"]
