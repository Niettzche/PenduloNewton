import json
import os
import time
from pathlib import Path
from typing import Dict, Tuple, Optional, Union

from flask import Flask, jsonify, request
from flask_sock import Sock

try:
    import serial  # type: ignore
except Exception:
    serial = None

from pendulum_processor import PendulumProcessor, decode_ws_message, frame_to_b64


# -------------------------------------------------------------------
# FLASK + WEBSOCKET
# -------------------------------------------------------------------

app = Flask(__name__)
sock = Sock(app)


@app.before_request
def handle_preflight():
    """
    Responde rápido a los preflight OPTIONS para que el navegador permita la petición real.
    """
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        origin = request.headers.get("Origin") or "*"
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = request.headers.get(
            "Access-Control-Request-Headers", "Content-Type"
        )
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "3600"
        return response


@app.after_request
def add_cors_headers(response):
    """Permitir CORS simple para los endpoints HTTP."""
    origin = request.headers.get("Origin") or "*"
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Headers"] = request.headers.get(
        "Access-Control-Request-Headers", "Content-Type"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@sock.route("/stream")
def stream(ws):
    """
    WebSocket endpoint: recibe frames y devuelve frame procesado + metadatos.
    Acepta:
      - Texto base64
      - Binario (JPEG/PNG comprimido)
      - JSON: {"frame": "<b64>", "fps": 30, "timestamp": 0.033}
    Respuesta:
      - Si la entrada fue JSON -> JSON {"frame": "<b64>", "info": {...}}
      - Si fue base64/binario simple -> solo el frame en base64
    """
    processor = PendulumProcessor()

    while True:
        data = ws.receive()
        if data is None:
            break

        is_json_input = isinstance(data, str) and data.lstrip().startswith("{")

        try:
            frame, fps_override, timestamp = decode_ws_message(data)
        except Exception as exc:  # noqa: BLE001 - devolver error al cliente
            ws.send(json.dumps({"error": str(exc)}))
            continue

        if fps_override:
            processor.fps = fps_override

        processed, info = processor.process_frame(frame, timestamp=timestamp)

        if is_json_input:
            ws.send(json.dumps({"frame": frame_to_b64(processed), "info": info}))
        else:
            ws.send(frame_to_b64(processed))


# -------------------------------------------------------------------
# SERIAL / SERVO
# -------------------------------------------------------------------

DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
SERVO_COMMAND = "OPENSIGNAL\n"


def _write_serial_command(port: str, message: str, baudrate: int = 9600) -> Tuple[bool, Optional[str]]:
    """
    Envía un mensaje ASCII a un puerto serie y devuelve (ok, error_str).
    No mantiene la conexión abierta: abre, escribe, cierra.
    """
    if serial is None:
        return False, "pyserial no está instalado o hay un paquete 'serial' conflictivo."

    try:
        with serial.Serial(port, baudrate=baudrate, timeout=2) as ser:
            # Muchos Arduinos (sobre todo clones CH340) se reinician al abrir el puerto;
            # esperamos un poco a que termine el boot.
            time.sleep(2.5)
            if hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()
            ser.write(message.encode("ascii"))
            ser.flush()
            return True, None
    except Exception as exc:  # noqa: BLE001 - reportar error al cliente
        return False, str(exc)


def handle_servo_command(port: str, baudrate: int = 9600) -> Dict:
    """
    Lógica central para enviar el comando OPENSIGNAL al Arduino.
    """
    ok, error = _write_serial_command(port, SERVO_COMMAND, baudrate=baudrate)

    if ok:
        message = f"Comando {SERVO_COMMAND.strip()} enviado a {port}"
    else:
        message = f"No se pudo escribir en {port}: {error}"

    return {
        "type": "servo_status",
        "command": "servo",
        "target_port": port,
        "baudrate": baudrate,
        "serial_message": SERVO_COMMAND,
        "write_ok": ok,
        "write_error": error,
        "message": message,
    }


@app.route("/servo", methods=["GET"])
def servo_http():
    """
    Cada petición a /servo envía OPENSIGNAL al Arduino por serial.
    Query opcional:
      - ?port=/dev/ttyACM0
      - ?baudrate=9600
    Responde con JSON con el estado del envío.
    """
    port = request.args.get("port", DEFAULT_SERIAL_PORT)
    baudrate = request.args.get("baudrate", type=int) or 9600

    result = handle_servo_command(port, baudrate)
    return jsonify(result)


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------


def build_ssl_context() -> Union[None, Tuple[str, str]]:
    """
    Devuelve un contexto SSL (cert, key) si USE_HTTPS=1 y existen las rutas.
    Variables:
      - USE_HTTPS=1|0
      - SSL_CERT: ruta al cert (default backend/cert.crt)
      - SSL_KEY: ruta a la key (default backend/cert.key)
    """
    use_https = os.getenv("USE_HTTPS", "1") == "1"
    if not use_https:
        print("HTTP mode habilitado por USE_HTTPS=0")
        return None

    base = Path(__file__).resolve().parent
    cert_path = Path(os.getenv("SSL_CERT", base / "cert.crt"))
    key_path = Path(os.getenv("SSL_KEY", base / "cert.key"))

    if cert_path.exists() and key_path.exists():
        print(f"Usando HTTPS con cert={cert_path} key={key_path}")
        return str(cert_path), str(key_path)

    print("No se encontraron cert/key para HTTPS, continuando en HTTP.")
    print(f"Buscado cert en {cert_path}")
    print(f"Buscado key  en {key_path}")
    return None


if __name__ == "__main__":
    # IMPORTANTE: esto va al final, después de definir todas las rutas
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "5000"))
    ssl_context = build_ssl_context()

    scheme = "https" if ssl_context else "http"
    print(f"Iniciando backend en {scheme}://{host}:{port}")
    app.run(host=host, port=port, debug=True, ssl_context=ssl_context)
