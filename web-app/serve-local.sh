#!/usr/bin/env bash
set -euo pipefail

# Serve the Vite app to the local network and refresh server.json with this host IP.
# Usage: PORT=4173 BACKEND_PORT=5000 ./serve-local.sh

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PORT="${PORT:-4173}"
BACKEND_PORT="${BACKEND_PORT:-5000}"
HTTPS="${HTTPS:-1}" # usa 1 para https, 0 para http

# Pick the first IPv4 on a non-loopback interface.
IP="${LOCAL_IP:-}"
if [ -z "${IP:-}" ]; then
  IP="$(hostname -I 2>/dev/null || true)"
  IP="$(echo "$IP" | awk 'NF{print $1; exit}')"
fi
if [ -z "${IP:-}" ] && command -v ip >/dev/null 2>&1; then
  IP="$(ip -4 route get 1 2>/dev/null | awk '{print $7; exit}')"
fi
if [ -z "${IP:-}" ] && command -v python3 >/dev/null 2>&1; then
  IP="$(python3 - <<'PY' || true
import socket
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(('192.168.0.1', 80))
    print(sock.getsockname()[0])
    sock.close()
except Exception:
    pass
PY
)"
fi

if [ -z "${IP:-}" ]; then
  echo "No se pudo detectar la IP local. Exporta LOCAL_IP=TU_IP y reintenta, o edita public/server.json a mano." >&2
  exit 1
fi

cat > public/server.json <<EOF
{
  "ip": "${IP}:${BACKEND_PORT}"
}
EOF

echo "📡 IP detectada: ${IP}"
echo "🛰️  Backend esperado en: ${IP}:${BACKEND_PORT}"
echo "💾 server.json actualizado en web-app/public/server.json"

ARGS=(--host 0.0.0.0 --port "${PORT}")
DEV_ENV=()
PROTO=$([ "${HTTPS}" = "1" ] && echo "https" || echo "http")

if [ "${HTTPS}" = "1" ]; then
  CERT_DIR="${ROOT}/.cert"
  KEY_FILE="${CERT_DIR}/key.pem"
  CERT_FILE="${CERT_DIR}/cert.pem"
  mkdir -p "${CERT_DIR}"
  if [ ! -f "${KEY_FILE}" ] || [ ! -f "${CERT_FILE}" ]; then
    if ! command -v openssl >/dev/null 2>&1; then
      echo "⚠️  No se encontró openssl para generar certificado. Instálalo o ejecuta con HTTPS=0 (no recomendado para cámara)." >&2
      exit 1
    fi
    echo "🔐 Generando certificado autofirmado para ${IP}..."
    openssl req -x509 -nodes -newkey rsa:2048 \
      -keyout "${KEY_FILE}" -out "${CERT_FILE}" \
      -days 365 \
      -subj "/CN=${IP}" \
      -addext "subjectAltName=DNS:localhost,IP:${IP}"
  fi
  DEV_ENV+=(HTTPS=1 SSL_KEY="${KEY_FILE}" SSL_CERT="${CERT_FILE}")
  echo "🔒 Sirviendo con HTTPS (cert autofirmado en .cert/)"
else
  DEV_ENV+=(HTTPS=0)
  echo "⚠️  Sirviendo por HTTP. getUserMedia solo funcionará en 'insecure origins' permitidos o si el navegador lo permite."
fi

DEV_ENV+=(PROXY_TARGET="${PROTO}://${IP}:${BACKEND_PORT}")

# Install deps on first run if missing.
if [ ! -d node_modules ]; then
  echo "📦 Instalando dependencias..."
  npm install
fi

echo "🚀 Sirviendo en ${PROTO}://${IP}:${PORT}"
echo "   (usa esa URL desde otros equipos de la LAN)"
env "${DEV_ENV[@]}" PORT="${PORT}" npm run dev -- "${ARGS[@]}"
