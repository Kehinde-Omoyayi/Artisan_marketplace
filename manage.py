#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def preload_osgeo_gdal():
    """Force OSGeo4W's gdal313.dll to claim the process's DLL namespace
    before anything else (sentry_sdk, psycopg2-binary, cryptography, etc.)
    loads a conflicting libssl-3-x64.dll / libcrypto-3-x64.dll under the
    same filename, which causes WinError 127 when GDAL later resolves
    its own symbols."""
    if os.name != "nt":
        return
    osgeo_bin = r"C:\Users\omoya\AppData\Local\Programs\OSGeo4W\bin"
    if os.path.isdir(osgeo_bin):
        os.add_dll_directory(osgeo_bin)
        from ctypes import WinDLL
        WinDLL(os.path.join(osgeo_bin, "gdal313.dll"))


preload_osgeo_gdal()


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and available on your "
            "PYTHONPATH environment variable? Did you forget to activate a virtual "
            "environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()