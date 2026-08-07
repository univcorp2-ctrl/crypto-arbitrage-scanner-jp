FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARB_HOST=0.0.0.0 \
    ARB_PORT=8000 \
    ARB_DB_PATH=/data/arbscanner.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir '.[web]' \
    && useradd --create-home --uid 10001 arbuser \
    && mkdir -p /data \
    && chown -R arbuser:arbuser /data /app

USER arbuser
VOLUME ["/data"]
EXPOSE 8000
CMD ["arbweb"]
