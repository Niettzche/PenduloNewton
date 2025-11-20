#!/usr/bin/env bash
set -euo pipefail

# Arranca el backend con TLS usando cert.crt y cert.key del directorio backend.
# Variables opcionales:
#   BACKEND_HOST (default 0.0.0.0)
#   BACKEND_PORT (default 5000)
#   USE_HTTPS   (default 1)
#   SSL_CERT    (default backend/cert.crt)
#   SSL_KEY     (default backend/cert.key)

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
export BACKEND_PORT="${BACKEND_PORT:-5000}"
export USE_HTTPS="${USE_HTTPS:-1}"
export SSL_CERT="${SSL_CERT:-$ROOT/cert.crt}"
export SSL_KEY="${SSL_KEY:-$ROOT/cert.key}"

if [ "${USE_HTTPS}" = "1" ]; then
  if [ ! -f "$SSL_CERT" ] || [ ! -f "$SSL_KEY" ]; then
    echo "No se encontraron cert/key en:"
    echo "  SSL_CERT=$SSL_CERT"
    echo "  SSL_KEY=$SSL_KEY"
    exit 1
  fi
fi

echo "Backend escuchando en ${BACKEND_HOST}:${BACKEND_PORT} (HTTPS=${USE_HTTPS})"
python3 app.py
