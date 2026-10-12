FROM python:3.12-slim AS assets
WORKDIR /build
COPY deploy/apk.json deploy/apk.json
COPY scripts/fetch-apk.py scripts/fetch-apk.py
RUN python scripts/fetch-apk.py

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 DATABASE_PATH=/data/hareer.sqlite3 SITE_DIR=/app/site
WORKDIR /app
RUN groupadd --gid 10001 hareer && useradd --uid 10001 --gid hareer --no-create-home hareer && mkdir /data && chown hareer:hareer /data
COPY --chown=hareer:hareer backend/ backend/
COPY --chown=hareer:hareer site/ site/
COPY --from=assets --chown=hareer:hareer /build/site/downloads/ site/downloads/
USER 10001:10001
EXPOSE 8080
CMD ["python", "backend/server.py"]
