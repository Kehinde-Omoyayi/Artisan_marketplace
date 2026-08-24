# Alternative to Nixpacks: a reproducible image with the GeoDjango system libraries
# baked in. Use this on Railway (Settings -> Build -> Dockerfile), Fly.io, or Render.

FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Part 3 Step 1 — GDAL/GEOS/PROJ are OS libraries, not pip packages.
RUN apt-get update && apt-get install -y --no-install-recommends \
        binutils \
        libproj-dev \
        gdal-bin \
        libgdal-dev \
        libgeos-dev \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .


EXPOSE 8000

CMD ["sh", "-c", "gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 3 --timeout 60"]
