web: gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 3 --timeout 60

worker: celery -A config worker --loglevel=info
beat: celery -A config beat --loglevel=info
release: python manage.py migrate --noinput
