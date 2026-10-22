#!/bin/sh
set -e

# Development convenience: generate migrations when AUTO_MAKEMIGRATIONS=1.
if [ "${AUTO_MAKEMIGRATIONS:-0}" = "1" ]; then
  python manage.py makemigrations --noinput
fi

python manage.py migrate --noinput
python manage.py seed_plans

# Always collect static files (cheap, and avoids a missing-manifest 500)
python manage.py collectstatic --noinput

# Create the admin from env vars; does nothing if it already exists
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
  python manage.py createsuperuser --noinput || true
fi

# Must be last: hands the process over to the server command
exec "$@"
