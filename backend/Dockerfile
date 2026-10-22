FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Windows checkouts may convert line endings; make the script safe either way.
RUN sed -i 's/\r$//' entrypoint.sh && mkdir -p /app/media /app/staticfiles

# Collect static files at build time so the admin CSS/JS is always in the image.
# The dummy values only let the production settings import during the build.
RUN DJANGO_SETTINGS_MODULE=config.settings.production \
    DJANGO_SECRET_KEY=build-only-key \
    POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
    POSTGRES_DB=build POSTGRES_USER=build POSTGRES_PASSWORD=build \
    python manage.py collectstatic --noinput

EXPOSE 8000
ENTRYPOINT ["sh", "./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60"]