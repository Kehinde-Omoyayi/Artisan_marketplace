#!/bin/sh
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 3 --timeout 60 --access-logfile - --error-logfile -
