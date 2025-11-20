# Streaming de frames con Flask

App para recibir video frame a frame por WebSocket, procesarlo con OpenCV (detección y marcado del péndulo) y devolver el resultado.

## Requisitos

- Python 3.10+
- Dependencias: `pip install -r requirements.txt`

## Ejecutar

```bash
export FLASK_APP=app.py
flask run --host 0.0.0.0 --port 5000
```

Endpoint WebSocket: `ws://localhost:5000/stream`

- Cliente envía cada frame como texto base64, binario (JPEG/PNG) o JSON:
  - Texto base64: `ws.send(b64)`
  - Binario: `ws.send(blob | ArrayBuffer)`
  - JSON: `{"frame": "<b64>", "fps": 30, "timestamp": 0.033}`
- El servidor decodifica, ejecuta el pipeline del péndulo y devuelve:
  - Si la entrada fue JSON: `{"frame": "<b64>", "info": {...}}`
  - Si fue base64/binario simple: solo la imagen en base64

El procesamiento está en `pendulum_processor.py` (detecta centros, línea blanca, cuenta oscilaciones y genera overlay).

## Servo por HTTP

El WebSocket es solo para frames. Para abrir el servo se usa la ruta GET `/servo`, que envía por pyserial el texto fijo `OPENSIGNAL\n`.

Query opcional:

- `port` (ej.: `/dev/ttyACM0`; por defecto `/dev/ttyUSB0`)
- `baudrate` (por defecto 9600)
- `enabled` (true/false; si es false no se envía nada)

Respuesta ejemplo:

```json
{
  "type": "servo_status",
  "command": "servo",
  "requested_port": null,
  "arduino_port": null,
  "target_port": "/dev/ttyUSB0",
  "baudrate": 9600,
  "serial_message": "OPENSIGNAL\n",
  "write_ok": true,
  "write_error": null,
  "ports": [],
  "message": "Comando OPENSIGNAL enviado a /dev/ttyUSB0 (usando puerto por defecto)"
}
```

## Cliente de prueba (JavaScript)

```js
const ws = new WebSocket("ws://localhost:5000/stream");
ws.onmessage = (ev) => {
  const payload = (() => {
    try { return JSON.parse(ev.data); } catch { return null; }
  })();
  const b64 = payload ? payload.frame : ev.data;
  const img = new Image();
  img.src = "data:image/jpeg;base64," + b64;
  document.body.appendChild(img);
  if (payload?.info) console.log("meta", payload.info);
};

function sendFrame(canvas) {
  canvas.toBlob((blob) => {
    blob.arrayBuffer().then((buf) => {
      const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
      ws.send(JSON.stringify({ frame: b64, fps: 30 }));
    });
  }, "image/jpeg", 0.7);
}
```

## Notas

- Para menor overhead, envía frames como binario (`ws.receive()` bytes) y usa `cv2.imdecode` directamente (ya soportado).
- Para despliegue, usa un servidor compatible WebSocket (p.ej. `hypercorn --bind 0.0.0.0:5000 --worker-class asyncio app:app`).
