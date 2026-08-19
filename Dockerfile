FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data ./data
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

FROM base AS test
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY n8n ./n8n
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q"]

FROM base AS runtime
ENV XDG_DATA_HOME=/app/.local/share CREWAI_TRACING_ENABLED=false
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN addgroup --system app && adduser --system --home /home/app --ingroup app app \
    && mkdir -p /home/app /app/.local/share \
    && chown -R app:app /home/app /app \
    && chmod 755 /usr/local/bin/docker-entrypoint.sh
USER app
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
