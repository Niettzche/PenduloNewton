#!/bin/bash

set -e

echo "=== Instalando dependencias para HTTPS local ==="

# Dependencias necesarias para Chrome/Firefox en Arch
sudo pacman -Syu --needed mkcert nss

echo "=== Detectando IP local para incluirla en el certificado ==="
LAN_IP="${1:-$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')}"
if [ -z "$LAN_IP" ]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

if [ -z "$LAN_IP" ]; then
  echo "❌ No se pudo detectar la IP LAN. Ejemplo de uso: ./setup.sh 192.168.0.23"
  exit 1
fi

echo "Usando IP: ${LAN_IP}"

echo "=== Creando carpeta de certificados ==="
mkdir -p certs
cd certs || exit

echo "=== Inicializando CA local (solo la primera vez) ==="
mkcert -install

echo "=== Generando certificados HTTPS locales ==="
mkcert -cert-file dev-cert.pem -key-file dev-key.pem localhost 127.0.0.1 ::1 "${LAN_IP}"

echo "=== Certificados generados en ./certs ==="
cd ..

echo "=== Configurando vite.config.js con soporte HTTPS ==="
cat << 'EOF' > vite.config.js
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'node:url'
import process from 'node:process'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const certDir = path.resolve(__dirname, 'certs')
const certFile = path.join(certDir, 'dev-cert.pem')
const keyFile = path.join(certDir, 'dev-key.pem')

if (!fs.existsSync(certFile) || !fs.existsSync(keyFile)) {
  console.error('❌ No se encontraron dev-cert.pem/dev-key.pem. Ejecuta ./setup.sh')
  process.exit(1)
}

export default ({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const lanHost = env.VITE_DEV_HOST || '0.0.0.0'

  return defineConfig({
    plugins: [react()],
    server: {
      https: {
        key: fs.readFileSync(keyFile),
        cert: fs.readFileSync(certFile),
      },
      host: '0.0.0.0', // permite acceso desde otros dispositivos en la red local
      port: 5173,
      hmr: {
        host: lanHost,
        protocol: 'wss',
        port: 5173,
      },
    },
  })
}
EOF

echo "=== Configuración lista ⚡ ==="
echo "Escribiendo IP en .env.local (VITE_DEV_HOST=${LAN_IP})"
echo "VITE_DEV_HOST=${LAN_IP}" > .env.local
echo "Si prefieres solo localhost en esta máquina, borra .env.local o cambia VITE_DEV_HOST=localhost"
echo "Ejecuta ahora: npm install (si no lo hiciste) y luego:"
echo "--------------------------------------------------------"
echo "  npm run dev"
echo "--------------------------------------------------------"
echo "Abre en navegador:"
echo " - https://localhost:5173  (PC)"
echo " - https://${LAN_IP}:5173  (cel/equipo en la misma red)"
echo ""
echo "⚠ Instala el certificado raíz de mkcert en el dispositivo cliente para evitar advertencias HTTPS."
