#!/bin/bash
# Karma launcher - uses gunicorn for production WSGI serving
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KARMA_DIR="${KARMA_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
cd "$KARMA_DIR" || exit 1

exec gunicorn --bind "${KARMA_BIND:-0.0.0.0:5000}" --workers "${KARMA_WORKERS:-2}" wsgi:app
