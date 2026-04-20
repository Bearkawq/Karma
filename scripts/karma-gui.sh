#!/bin/bash
# Karma launcher - uses gunicorn for production WSGI serving
cd /home/mikoleye/karma || exit 1
exec gunicorn --bind 0.0.0.0:5000 --workers 2 wsgi:app