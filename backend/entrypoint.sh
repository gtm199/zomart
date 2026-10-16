#!/bin/sh
set -e

# Development convenience: generate migrations when AUTO_MAKEMIGRATIONS=1.
# They are written into ./backend/apps/*/migrations (bind-mounted) - commit them, then switch this off in production.
if [ "${AUTO_MAKEMIGRATIONS:-0}" = "1" ]; then
  python manage.py makemigrations --noinput
fi

python manage.py migrate --noinput
python manage.py seed_plans

if [ "${DJANGO_SETTINGS_MODULE}" = "config.settings.production" ]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
