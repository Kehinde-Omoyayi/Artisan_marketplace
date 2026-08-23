"""
core/storage.py — Part 18.2. Private object storage with short-lived signed URLs.

Works against any S3-compatible provider (Supabase Storage, Backblaze B2, R2...).
The bucket MUST be private. Nothing in this project ever produces a permanent public
URL for a verification document or a piece of dispute evidence.
"""

import io
import os
import uuid

import boto3
import requests
from django.conf import settings

_ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.STORAGE_ENDPOINT_URL,
        aws_access_key_id=settings.STORAGE_ACCESS_KEY,
        aws_secret_access_key=settings.STORAGE_SECRET_KEY,
        region_name=settings.STORAGE_REGION,
    )


def download_whatsapp_media_to_storage(media_id, folder):
    """
    WhatsApp media is a two-step fetch: ask Meta for a short-lived download URL for this
    media_id, download the bytes from THAT url, then upload them into your OWN private
    bucket. Never store or link to Meta's URL directly — it expires within minutes.
    """
    meta_headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    lookup = requests.get(
        f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{media_id}",
        headers=meta_headers,
        timeout=10,
    )
    lookup.raise_for_status()
    media_url = lookup.json()["url"]

    media_response = requests.get(media_url, headers=meta_headers, timeout=15)
    media_response.raise_for_status()

    storage_key = f"{folder}/{uuid.uuid4().hex}.jpg"
    _client().upload_fileobj(
        io.BytesIO(media_response.content), settings.STORAGE_BUCKET, storage_key
    )
    return storage_key


def upload_file_to_storage(uploaded_file, folder):
    """
    Direct-upload path for files the browser already sent us in the request body —
    the webchat counterpart to `download_whatsapp_media_to_storage` above, which
    exists only because WhatsApp media has to be *fetched* first. Same destination,
    same guarantee: private bucket, server-generated key. The key is never built
    from the uploaded filename, so there's no path-traversal surface from a
    malicious file name.
    """
    extension = _safe_extension(getattr(uploaded_file, "name", ""))
    storage_key = f"{folder}/{uuid.uuid4().hex}{extension}"
    _client().upload_fileobj(uploaded_file, settings.STORAGE_BUCKET, storage_key)
    return storage_key


def _safe_extension(filename):
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in _ALLOWED_EXTENSIONS else ".jpg"


def generate_signed_url(storage_key, expires_in_seconds=300):
    """
    The ONLY way anyone — staff included — ever views a verification document or piece
    of dispute evidence. The bucket itself stays private; this makes a link usable for
    five minutes and dead after that.
    """
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.STORAGE_BUCKET, "Key": storage_key},
        ExpiresIn=expires_in_seconds,
    )
