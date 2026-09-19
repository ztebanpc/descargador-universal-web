#!/bin/sh
set -e

echo "[Entrypoint] Iniciando bgutil-pot server en 127.0.0.1:4416..."
bgutil-pot server --host 127.0.0.1 --port 4416 &

echo "[Entrypoint] Iniciando Gunicorn en puerto ${PORT:-10000}..."
exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 300 app:app