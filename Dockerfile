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
    python manage.py collectstatic --noinput

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

CMD ["gunicorn", "Smartcop_backend.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "30"]
