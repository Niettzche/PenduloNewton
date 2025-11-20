import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

const SERVO_PATH = '/servo'
const DESIRED_FPS = 5
const JPEG_QUALITY = 0.4

function App() {
  const [status, setStatus] = useState('idle') // idle | connecting | active
  const [message, setMessage] = useState('Preparando...')
  const [serverIp, setServerIp] = useState('')
  const [ready, setReady] = useState(false)
  const [servoOn, setServoOn] = useState(false)
  const [backendFrame, setBackendFrame] = useState('')
  const [backendInfo, setBackendInfo] = useState('')

  const socketRef = useRef(null)
  const loopRef = useRef(null)
  const sendingRef = useRef(false)
  const cameraRef = useRef(null)
  const livePreviewRef = useRef(null)
  const canvasRef = useRef(null)
  const backendUrlRef = useRef('')

  const updateStatus = useCallback((nextStatus, nextMessage) => {
    setStatus(nextStatus)
    if (nextMessage !== undefined) setMessage(nextMessage)
  }, [])

  const stopLoop = useCallback(() => {
    if (loopRef.current) {
      clearInterval(loopRef.current)
      loopRef.current = null
    }
    sendingRef.current = false
  }, [])

  const stopTransmission = useCallback(
    (text = 'Transmisión detenida') => {
      updateStatus('connecting', 'Deteniendo transmisión...')
      stopLoop()
      try {
        socketRef.current?.close()
      } catch {
        /* no-op */
      }
      socketRef.current = null
      setServoOn(false)
      updateStatus('idle', text)
    },
    [stopLoop, updateStatus],
  )

  const ensureCamera = useCallback(async () => {
    const camera = cameraRef.current
    const preview = livePreviewRef.current
    if (!camera || !preview) return false
    if (camera.srcObject) return true
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false,
      })
      camera.srcObject = stream
      preview.srcObject = stream
      await camera.play()
      return true
    } catch {
      return false
    }
  }, [])

  const captureAndSendFrame = useCallback(() => {
    const socket = socketRef.current
    const camera = cameraRef.current
    const canvas = canvasRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) return
    if (!camera || !canvas || !camera.srcObject) return
    if (sendingRef.current) return

    const { videoWidth, videoHeight } = camera
    if (!videoWidth || !videoHeight) return

    sendingRef.current = true
    try {
      canvas.width = videoWidth
      canvas.height = videoHeight
      const ctx = canvas.getContext('2d')
      ctx.drawImage(camera, 0, 0, videoWidth, videoHeight)
      const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY)
      const base64 = dataUrl.split(',')[1]
      const payload = JSON.stringify({
        frame: base64,
        fps: DESIRED_FPS,
        timestamp: Date.now() / 1000,
      })
      socket.send(payload)
    } catch {
      stopTransmission('Error capturando frame')
    } finally {
      sendingRef.current = false
    }
  }, [stopTransmission])

  const startLoop = useCallback(() => {
    stopLoop()
    loopRef.current = setInterval(captureAndSendFrame, 1000 / DESIRED_FPS)
  }, [captureAndSendFrame, stopLoop])

  const applyServoStatus = useCallback((payload) => {
    const enabled = Boolean(payload?.enabled)
    setServoOn(enabled)
    if (payload?.message) setMessage(payload.message)
  }, [])

  const handleBackendPayload = useCallback((frame, info) => {
    if (frame) {
      if (backendUrlRef.current) {
        URL.revokeObjectURL(backendUrlRef.current)
        backendUrlRef.current = ''
      }
      setBackendFrame(`data:image/jpeg;base64,${frame}`)
    }
    if (info) {
      const time = info.time_s != null ? Number(info.time_s).toFixed(2) : '-'
      setBackendInfo(`t=${time}s  oscilaciones=${info.oscillations ?? '-'}`)
    } else {
      setBackendInfo('')
    }
  }, [])

  const handleBinaryMessage = useCallback((data) => {
    if (backendUrlRef.current) {
      URL.revokeObjectURL(backendUrlRef.current)
      backendUrlRef.current = ''
    }
    const blob = data instanceof Blob ? data : new Blob([data], { type: 'image/jpeg' })
    const objectUrl = URL.createObjectURL(blob)
    backendUrlRef.current = objectUrl
    setBackendFrame(objectUrl)
  }, [])

  const handleMessage = useCallback(
    (event) => {
      const { data } = event
      if (data instanceof Blob || data instanceof ArrayBuffer) {
        handleBinaryMessage(data)
        return
      }

      let payload = data
      if (typeof payload === 'string' && payload.trim().startsWith('{')) {
        try {
          payload = JSON.parse(payload)
        } catch {
          /* leave as string */
        }
      }

      if (typeof payload === 'string') {
        handleBackendPayload(payload, null)
        return
      }

      if (payload?.servo !== undefined) applyServoStatus(payload.servo)
      handleBackendPayload(payload?.frame, payload?.info)
    },
    [applyServoStatus, handleBackendPayload, handleBinaryMessage],
  )

  const startTransmission = useCallback(async () => {
    updateStatus('connecting', 'Solicitando cámara...')
    const ok = await ensureCamera()
    if (!ok) {
      updateStatus('idle', 'Permiso de cámara rechazado')
      return
    }

    const targetHost = import.meta.env.DEV ? window.location.host : serverIp || window.location.host
    if (!targetHost) {
      updateStatus('idle', 'Host del backend no definido')
      return
    }

    const wsUrl = new URL('/stream', window.location.origin)
    wsUrl.protocol = wsUrl.protocol === 'https:' ? 'wss:' : 'ws:'
    wsUrl.host = targetHost
    let socket
    try {
      socket = new WebSocket(wsUrl)
      socket.binaryType = 'arraybuffer'
    } catch {
      updateStatus('idle', 'No se pudo crear WebSocket')
      return
    }
    socketRef.current = socket
    socket.onopen = () => {
      updateStatus('active', `Transmitiendo a ${targetHost}`)
      startLoop()
    }
    socket.onmessage = handleMessage
    socket.onerror = () => updateStatus('idle', 'Error en la conexión')
    socket.onclose = () => {
      stopLoop()
      socketRef.current = null
      setServoOn(false)
      updateStatus('idle', 'Conexión cerrada')
    }
  }, [ensureCamera, handleMessage, serverIp, startLoop, stopLoop, updateStatus])

  const toggleServo = useCallback(async () => {
    const next = !servoOn

    const targetHost = import.meta.env.DEV ? window.location.host : serverIp || window.location.host
    if (!targetHost) {
      setMessage('Host del backend no definido')
      return
    }

    const url = new URL(SERVO_PATH, window.location.origin)
    url.host = targetHost
    url.protocol = url.protocol === 'https:' ? 'https:' : 'http:'
    url.searchParams.set('enabled', String(next))
    try {
      const res = await fetch(url.toString())
      if (!res.ok) {
        setMessage('El backend devolvió un error al manejar el servo')
        return
      }
      const data = await res.json()
      applyServoStatus(data)
    } catch {
      setMessage('No se pudo contactar al backend para el servo')
    }
  }, [applyServoStatus, servoOn, serverIp])

  const loadServerIp = useCallback(async () => {
    const candidates = ['/server.json', '/app/server.json', '../server.json']
    for (const path of candidates) {
      try {
        const res = await fetch(path)
        if (!res.ok) continue
        const data = await res.json()
        if (data?.ip) return data.ip
      } catch {
        /* try next path */
      }
    }
    return ''
  }, [])

  useEffect(() => {
    let active = true
    const camera = cameraRef.current
    ;(async () => {
      updateStatus('connecting', 'Preparando...')
      const ip = await loadServerIp()
      if (!active) return
      setServerIp(ip)
      setReady(true)
      updateStatus('idle', ip ? 'Listo para conectar' : 'No se pudo cargar server.json')
    })()
    return () => {
      active = false
      stopLoop()
      try {
        socketRef.current?.close()
      } catch {
        /* ignore */
      }
      const stream = camera?.srcObject
      if (stream) {
        stream.getTracks().forEach((track) => track.stop())
      }
      if (backendUrlRef.current) {
        URL.revokeObjectURL(backendUrlRef.current)
        backendUrlRef.current = ''
      }
    }
  }, [loadServerIp, stopLoop, updateStatus])

  const statusText =
    status === 'active'
      ? 'Transmisión activa'
      : status === 'connecting'
        ? 'Conectando...'
        : 'Transmisión detenida'

  const toggleTransmission = () => {
    if (!ready || status === 'connecting') return
    if (socketRef.current) {
      stopTransmission()
    } else {
      startTransmission()
    }
  }

  const servoLabel = servoOn ? 'Apagar servo' : 'Encender servo'

  return (
    <div className="page">
      <main className="container">
        <header className="card">
          <div className="row">
            <div className={`status-dot ${status === 'active' ? 'dot-on' : 'dot-off'}`} />
            <div>
              <div className="section-label">Estado</div>
              <div>{statusText}</div>
            </div>
          </div>
          <div className="meta">{message}</div>
          <div className="actions">
            <button
              onClick={toggleTransmission}
              disabled={!ready || status === 'connecting'}
              className={status === 'active' ? 'stop' : ''}
            >
              {status === 'active' ? 'Detener transmisión' : 'Iniciar transmisión'}
            </button>
            <button
              onClick={toggleServo}
              className={servoOn ? 'stop' : 'positive'}
              disabled={!serverIp}
            >
              {servoLabel}
            </button>
            <div>
              <div className="section-label">Servidor</div>
              <div>{serverIp || 'IP no configurada'}</div>
            </div>
          </div>
        </header>

        <section className="card">
          <div className="section-label">Vista local (fluida)</div>
          <video ref={livePreviewRef} className="preview" playsInline muted autoPlay />
          <div className="meta">No pasa por el backend, es solo para ver lo que la cámara está capturando.</div>
        </section>

        <section className="card">
          <div className="section-label">Respuesta del backend</div>
          <img src={backendFrame} className="preview" alt="frame backend" />
          <div className="meta">{backendInfo}</div>
          <div className="placeholder" style={{ display: backendFrame ? 'none' : 'block' }}>
            Aún no hay respuesta del backend.
          </div>
        </section>
      </main>

      <video ref={cameraRef} playsInline muted autoPlay className="hidden" />
      <canvas ref={canvasRef} width="640" height="360" className="hidden" />
    </div>
  )
}

export default App
