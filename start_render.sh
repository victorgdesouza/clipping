#!/usr/bin/env bash
set -e

python manage.py qcluster &
QCLUSTER_PID=$!

cleanup() {
  kill -TERM "$QCLUSTER_PID" 2>/dev/null || true
  wait "$QCLUSTER_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

gunicorn core.wsgi:application --bind 0.0.0.0:"${PORT}" --timeout 300 &
GUNICORN_PID=$!
wait "$GUNICORN_PID"
