FROM python:3.14.7-alpine3.24@sha256:3f818d6811ff5f3f2b5e5d836df3d25c2dd2e588d3b4981338a8ba17e422f74f AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt ./
RUN python -m pip install \
    --no-compile \
    --require-hashes \
    --target=/opt/python \
    --requirement=requirements.txt

FROM python:3.14.7-alpine3.24@sha256:3f818d6811ff5f3f2b5e5d836df3d25c2dd2e588d3b4981338a8ba17e422f74f AS runtime

ARG VERSION=dev
ARG VCS_REF=unknown
ARG SOURCE_URL=https://github.com/rserag/bloti-bot

LABEL org.opencontainers.image.title="Bloti Bot" \
      org.opencontainers.image.description="Telegram group moderation and member-mention bot" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV PYTHONPATH=/opt/python:/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SESSION_PATH=/var/lib/blotibot/blotibot \
    HEARTBEAT_PATH=/run/blotibot/heartbeat \
    HEARTBEAT_INTERVAL_SECONDS=15 \
    HEARTBEAT_MAX_AGE_SECONDS=60

RUN apk upgrade --no-cache libcrypto3 libssl3 \
    && addgroup -S -g 1000 blotibot \
    && adduser -S -D -H -u 1000 -h /nonexistent -s /sbin/nologin -G blotibot blotibot \
    && mkdir -p /app/src /var/lib/blotibot /run/blotibot \
    && chown -R 1000:1000 /app /var/lib/blotibot /run/blotibot

COPY --from=dependencies /opt/python /opt/python
COPY --chown=1000:1000 src/ /app/src/

WORKDIR /app
USER 1000:1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD ["python", "-m", "blotibot.healthcheck"]

ENTRYPOINT ["python", "-m", "blotibot"]
