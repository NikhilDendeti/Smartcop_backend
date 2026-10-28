FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=Smartcop_backend.settings.prod

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files with throwaway values; real ones come from the environment at runtime.
RUN SECRET_KEY=build-only ALLOWED_HOSTS=build CORS_ALLOWED_ORIGINS=https://build.invalid \
    DATABASE_URL=postgres://build:build@localhost/build \
    FIELD_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
    python manage.py collectstatic --noinput

RUN useradd --create-home appuser && mkdir -p /app/evidence_store && chown appuser /app/evidence_store
USER appuser

EXPOSE 8000

# Liveness only (does not touch the database); /ready/ checks dependencies.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=4).status == 200 else 1)" || exit 1

# The web process. Run the background worker from the same image with:
#   celery -A Smartcop_backend worker --loglevel=info
CMD ["gunicorn", "Smartcop_backend.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
