web: gunicorn config.wsgi
worker: celery -A config worker --loglevel=info
beat: celery -A config beat --loglevel=info
release: python manage.py migrate --noinput
