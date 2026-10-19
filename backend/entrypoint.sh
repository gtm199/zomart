#!/bin/sh
set -e

if [ "${AUTO_MAKEMIGRATIONS:-0}" = "1" ]; then
  # Development only: writes new migration files into ./backend/apps/*/migrations. Commit them.
  python manage.py makemigrations --noinput
elif [ "${DJANGO_SETTINGS_MODULE}" = "config.settings.production" ]; then
  # Live server: stop if a model changed but its migration was never committed.
  python manage.py makemigrations --check --dry-run
fi

python manage.py migrate --noinput
python manage.py seed_plans

if [ "${DJANGO_SETTINGS_MODULE}" = "config.settings.production" ]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
