import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { PIVOT_DEFAULTS, savgolOrOriginal } from './pendulumAnalysis'

const SERVO_PATH = '/servo'
const DESIRED_FPS = 5
const JPEG_QUALITY = 0.4

const generateSessionId = () =>
  window.crypto?.randomUUID
    ? window.crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`

function App() {
  const [sessionId, setSessionId] = useState(generateSessionId)
  const [status, setStatus] = useState('idle') // idle | connecting | active
  const [message, setMessage] = useState('Preparando...')
  const [serverIp, setServerIp] = useState('')
  const [ready, setReady] = useState(false)
  const [servoOn, setServoOn] = useState(false)
  const [backendFrame, setBackendFrame] = useState('')
  const [backendInfo, setBackendInfo] = useState('')
  const [analysisPlot, setAnalysisPlot] = useState('')
  const [analysisSummary, setAnalysisSummary] = useState([])
  const [analysisStats, setAnalysisStats] = useState(null)
  const [analysisStatus, setAnalysisStatus] = useState('')
  const [analysisError, setAnalysisError] = useState('')
  const [samplesCount, setSamplesCount] = useState(0)
  const [liveTimes, setLiveTimes] = useState([])
  const [liveAngles, setLiveAngles] = useState([])

  const socketRef = useRef(null)
  const loopRef = useRef(null)
  const sendingRef = useRef(false)
  const cameraRef = useRef(null)
  const livePreviewRef = useRef(null)
  const canvasRef = useRef(null)
  const backendUrlRef = useRef('')
  const sessionIdRef = useRef(sessionId)

  const getTargetHost = useCallback(
    () => (import.meta.env.DEV ? window.location.host : serverIp || window.location.host),
    [serverIp],
  )

  const samplesRef = useRef(0)

  const resetAnalysis = useCallback(() => {
    setAnalysisPlot('')
    setAnalysisSummary([])
    setAnalysisStats(null)
    setAnalysisStatus('')
    setAnalysisError('')
    setSamplesCount(0)
    setLiveTimes([])
    setLiveAngles([])
    samplesRef.current = 0
  }, [])

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
        session_id: sessionIdRef.current,
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

  const liveChartData = useMemo(() => {
    if (!liveTimes.length || !liveAngles.length) return null
    const t0 = liveTimes[0]
    const times = liveTimes.map((t) => t - t0)
    const anglesSmooth = savgolOrOriginal(liveAngles)
    const maxAbs = Math.max(20, ...anglesSmooth.map((v) => Math.abs(v)))
    return { times, angles: liveAngles, smooth: anglesSmooth, maxAbs }
  }, [liveAngles, liveTimes])

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
      if (info.x != null && info.y != null) {
        samplesRef.current += 1
        setSamplesCount(samplesRef.current)
        setLiveTimes((prev) => {
          const next = [...prev, Number(info.time_s ?? prev.length)]
          return next.length > 500 ? next.slice(-500) : next
        })
        setLiveAngles((prev) => {
          const px = info.center_x ?? PIVOT_DEFAULTS.x
          const py = info.line_y ?? PIVOT_DEFAULTS.y
          const thetaDeg = (Math.atan2(Number(info.x) - px, Number(info.y) - py) * 180) / Math.PI
          const next = [...prev, thetaDeg]
          return next.length > 500 ? next.slice(-500) : next
        })
      }
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

  const requestAnalysis = useCallback(
    async (targetSessionId = '') => {
      const sessionToUse =
        typeof targetSessionId === 'string' && targetSessionId.trim()
          ? targetSessionId
          : sessionIdRef.current
      const targetHost = getTargetHost()
      if (!targetHost) {
        setAnalysisError('Host del backend no definido')
      return
    }

    setAnalysisStatus('Generando gráfica y resumen...')
    setAnalysisError('')
    if (!sessionToUse) {
      setAnalysisError('No hay sesión activa para analizar')
      setAnalysisStatus('')
      return
    }
    if (samplesRef.current === 0) {
      setAnalysisError('No hay datos capturados en esta sesión')
      setAnalysisStatus('')
      return
    }
    try {
      const url = new URL('/analysis/session_summary', window.location.origin)
      url.host = targetHost
      url.protocol = url.protocol === 'https:' ? 'https:' : 'http:'
      const res = await fetch(url.toString(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionToUse }),
        })
        const raw = await res.text()
        let data = {}
        if (raw) {
          try {
            data = JSON.parse(raw)
          } catch {
            throw new Error('Respuesta del backend no es JSON válido')
          }
        }
        if (!res.ok || data?.error) {
          const errMsg = data?.error || `El backend devolvió un error (${res.status})`
          throw new Error(errMsg)
        }
        setAnalysisPlot(data.plot ? `data:image/png;base64,${data.plot}` : '')
        setAnalysisSummary(data.summary_lines || [])
        setAnalysisStats(data.stats || null)
        setAnalysisStatus('Resumen generado con los datos del stream')
      } catch (err) {
        setAnalysisError(err?.message || 'No se pudo generar la gráfica')
        setAnalysisStatus('')
      }
    },
    [getTargetHost],
  )

  const startTransmission = useCallback(async () => {
    updateStatus('connecting', 'Solicitando cámara...')
    const ok = await ensureCamera()
    if (!ok) {
      updateStatus('idle', 'Permiso de cámara rechazado')
      return
    }

    const newSession = generateSessionId()
    setSessionId(newSession)
    sessionIdRef.current = newSession
    samplesRef.current = 0
    resetAnalysis()
    const sessionForSocket = newSession

    const targetHost = getTargetHost()
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
      if (samplesRef.current > 0) {
        void requestAnalysis(sessionForSocket)
      } else {
        setAnalysisError('No se capturaron datos en la sesión')
        setAnalysisStatus('')
      }
    }
  }, [ensureCamera, getTargetHost, handleMessage, requestAnalysis, resetAnalysis, startLoop, stopLoop, updateStatus])

  const toggleServo = useCallback(async () => {
    const next = !servoOn

    const targetHost = getTargetHost()
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
  }, [applyServoStatus, getTargetHost, servoOn])

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

  const formatStat = (value, digits = 3) => {
    if (value === undefined || value === null) return '-'
    const numeric = Number(value)
    if (Number.isNaN(numeric)) return '-'
    return numeric.toFixed(digits)
  }

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

        <section className="card">
          <div className="section-label">Gráfica en vivo (θ vs tiempo)</div>
          {liveChartData ? (
            <LiveChart data={liveChartData} />
          ) : (
            <div className="placeholder boxed">Inicia la transmisión para ver la gráfica en tiempo real.</div>
          )}
          <div className="meta small">Se muestran los últimos {liveTimes.length} puntos.</div>
        </section>

        <section className="card">
          <div className="section-label">Análisis del stream</div>
          <div className="row space-between">
            <div>
              <div>Sesión actual</div>
              <div className="meta">{sessionId}</div>
              <div className="meta small">Puntos detectados: {samplesCount}</div>
            </div>
            <button
              onClick={() => requestAnalysis(sessionIdRef.current)}
              disabled={!ready || status === 'connecting'}
            >
              Generar gráfica y resumen
            </button>
          </div>
          <div className="analysis-grid">
            <div>
              {analysisPlot ? (
                <img src={analysisPlot} className="preview" alt="Gráfica del péndulo" />
              ) : (
                <div className="placeholder boxed">Genera la gráfica para verla aquí.</div>
              )}
            </div>
            <div className="summary-panel">
              {analysisError && <div className="error">{analysisError}</div>}
              {analysisStatus && <div className="meta">{analysisStatus}</div>}
              <div className="summary-lines">
                {analysisSummary?.length
                  ? analysisSummary.map((line, idx) => (
                      <div key={idx} className="summary-line">
                        {line}
                      </div>
                    ))
                  : !analysisError && <div className="placeholder">Aún no hay resumen.</div>}
              </div>
              {analysisStats && (
                <div className="meta small">
                  Periodo: {formatStat(analysisStats.period)} s | Frecuencia: {formatStat(analysisStats.frequency)} Hz |
                  Oscilaciones: {analysisStats.oscillations != null ? formatStat(analysisStats.oscillations, 2) : '-'}
                </div>
              )}
            </div>
          </div>
        </section>
      </main>

      <video ref={cameraRef} playsInline muted autoPlay className="hidden" />
      <canvas ref={canvasRef} width="640" height="360" className="hidden" />
    </div>
  )
}

export default App

function LiveChart({ data }) {
  const { times, angles, smooth, maxAbs } = data
  const width = 700
  const height = 260
  const padding = 30
  const span = Math.max(1, times[times.length - 1] - times[0])

  const mapX = (t) => padding + ((t - times[0]) / span) * (width - padding * 2)
  const mapY = (v) => {
    const mid = height / 2
    return mid - (v / (maxAbs || 1)) * (height / 2 - padding)
  }

  const toPoints = (xs, ys) => xs.map((t, i) => `${mapX(t)},${mapY(ys[i])}`).join(' ')

  const rawPoints = toPoints(times, angles)
  const smoothPoints = toPoints(times, smooth)

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="live-chart">
      <defs>
        <linearGradient id="bgGrid" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(255,255,255,0.05)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0.02)" />
        </linearGradient>
      </defs>
      <rect x="0" y="0" width={width} height={height} fill="url(#bgGrid)" rx="12" />
      <g stroke="rgba(255,255,255,0.08)" strokeWidth="1">
        {[0.25, 0.5, 0.75].map((p) => (
          <line key={p} x1={padding} x2={width - padding} y1={p * height} y2={p * height} />
        ))}
      </g>
      <polyline points={rawPoints} fill="none" stroke="rgba(14,165,233,0.3)" strokeWidth="2" />
      <polyline points={smoothPoints} fill="none" stroke="#0ea5e9" strokeWidth="3" />
      <text x={padding} y={padding} fill="#e2e8f0" fontSize="12">
        θ (°) máx ±{maxAbs.toFixed(1)}
      </text>
      <text x={width - padding} y={height - padding / 2} textAnchor="end" fill="#94a3b8" fontSize="12">
        Tiempo (s) Δ{span.toFixed(2)}
      </text>
    </svg>
  )
}
