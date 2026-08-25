#!/bin/sh
# Single source of truth for how the web process starts. Using a real script
# file avoids any ambiguity in how Railway (or any platform) tokenizes an
# inline startCommand string with embedded quotes/variables.
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 3 --timeout 60 --access-logfile - --error-logfile -
