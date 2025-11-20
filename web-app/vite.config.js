import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: (() => {
    const useHttps = process.env.HTTPS === '1'
    const host = '0.0.0.0'
    const port = process.env.PORT ? Number(process.env.PORT) : undefined
    const proxyTarget = process.env.PROXY_TARGET

    if (!useHttps) return { host, port }

    const keyPath = process.env.SSL_KEY || path.resolve(__dirname, '.cert/key.pem')
    const certPath = process.env.SSL_CERT || path.resolve(__dirname, '.cert/cert.pem')

    let https
    if (fs.existsSync(keyPath) && fs.existsSync(certPath)) {
      https = {
        key: fs.readFileSync(keyPath),
        cert: fs.readFileSync(certPath),
      }
    }

    const proxy = proxyTarget
      ? {
          '/servo': {
            target: proxyTarget,
            changeOrigin: true,
            secure: false,
          },
          '/stream': {
            target: proxyTarget,
            ws: true,
            changeOrigin: true,
            secure: false,
          },
        }
      : undefined

    return {
      host,
      port,
      https,
      proxy,
    }
  })(),
})
