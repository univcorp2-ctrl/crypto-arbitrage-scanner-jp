FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARB_HOST=0.0.0.0 \
    ARB_PORT=8000 \
    ARB_DB_PATH=/app/data/arbscanner.db \
    ARB_CONFIG_PATH=/app/config.yml \
    ARB_AUTOSTART=true

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .
COPY config.example.yml ./config.yml
RUN mkdir -p /app/data

EXPOSE 8000
VOLUME ["/app/data"]
CMD ["arbweb", "--host", "0.0.0.0", "--port", "8000"]
