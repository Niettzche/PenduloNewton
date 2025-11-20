import csv
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

from pendulum_processor import PendulumProcessor, decode_ws_message, frame_to_b64, build_plot_and_stats


# -------------------------------------------------------------------
# FLASK + WEBSOCKET
# -------------------------------------------------------------------

app = Flask(__name__)
sock = Sock(app)
session_store: Dict[str, PendulumProcessor] = {}
session_csv_writers: Dict[str, Tuple[Path, object, csv.writer]] = {}


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
      - JSON: {"frame": "<b64>", "fps": 30, "timestamp": 0.033, "session_id": "..."}
    Respuesta:
      - Si la entrada fue JSON -> JSON {"frame": "<b64>", "info": {...}}
      - Si fue base64/binario simple -> solo el frame en base64
    """
    processor = PendulumProcessor()
    touched_sessions = set()

    while True:
        data = ws.receive()
        if data is None:
            break

        is_json_input = isinstance(data, str) and data.lstrip().startswith("{")

        try:
            frame, fps_override, timestamp = decode_ws_message(data)
            session_id = None
            if isinstance(data, str) and data.lstrip().startswith("{"):
                payload = json.loads(data)
                session_id = payload.get("session_id")
        except Exception as exc:  # noqa: BLE001 - devolver error al cliente
            ws.send(json.dumps({"error": str(exc)}))
            continue

        if fps_override:
            processor.fps = fps_override

        target_proc = processor
        if session_id:
            target_proc = session_store.setdefault(session_id, PendulumProcessor(fps=processor.fps))
            touched_sessions.add(session_id)

        processed, info = target_proc.process_frame(frame, timestamp=timestamp)

        if session_id:
            csv_info = session_csv_writers.get(session_id)
            if csv_info is None:
                csv_path = Path(app.root_path).parent / f"datos_pendulo_{session_id}.csv"
                f_handle = open(csv_path, "w", newline="")
                writer = csv.writer(f_handle)
                writer.writerow(["frame", "tiempo_s", "x", "y", "radio"])
                csv_info = (csv_path, f_handle, writer)
                session_csv_writers[session_id] = csv_info
            csv_path, f_handle, writer = csv_info
            if target_proc.records:
                last_row = target_proc.records[-1]
                if len(last_row) >= 5:
                    writer.writerow(last_row)
                    f_handle.flush()

        if is_json_input:
            ws.send(json.dumps({"frame": frame_to_b64(processed), "info": info, "session_id": session_id}))
        else:
            ws.send(frame_to_b64(processed))

    # cerrar csvs usados en esta conexión
    for sid in touched_sessions:
        csv_info = session_csv_writers.get(sid)
        if csv_info:
            _, f_handle, _ = csv_info
            try:
                f_handle.flush()
                f_handle.close()
            except Exception:
                pass


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
# ANÁLISIS (matplotlib desde stream)
# -------------------------------------------------------------------


@app.route("/analysis/plot", methods=["POST"])
def analysis_plot():
    """
    Recibe datos del stream y devuelve el PNG base64 de la gráfica + estadísticas,
    usando la misma lógica que main.py/graficar.py.
    JSON esperado:
      {
        "times": [..],
        "xs": [..],
        "ys": [..],
        "pivot_x": 230?,  // opcional
        "pivot_y": 120?   // opcional
      }
    """
    payload = request.get_json(silent=True, force=True) or {}
    times = payload.get("times") or []
    xs = payload.get("xs") or []
    ys = payload.get("ys") or []
    pivot_x = payload.get("pivot_x")
    pivot_y = payload.get("pivot_y")
    session_id = payload.get("session_id")

    if not (isinstance(times, list) and isinstance(xs, list) and isinstance(ys, list)):
        return jsonify({"error": "times/xs/ys deben ser listas"}), 400
    if not (len(times) == len(xs) == len(ys) and len(times) >= 2):
        return jsonify({"error": "Se requieren al menos 2 muestras y longitudes iguales"}), 400

    try:
        times_f = [float(t) for t in times]
        xs_f = [float(x) for x in xs]
        ys_f = [float(y) for y in ys]
        pivot_x_f = float(pivot_x) if pivot_x is not None else None
        pivot_y_f = float(pivot_y) if pivot_y is not None else None
    except Exception:
        return jsonify({"error": "No se pudieron convertir los datos a float"}), 400

    output = build_plot_and_stats(times_f, xs_f, ys_f, pivot_x=pivot_x_f, pivot_y=pivot_y_f)
    if session_id and session_id in session_store:
        processor = session_store[session_id]
        csv_info = session_csv_writers.get(session_id)
        if csv_info:
            csv_path, f_handle, _ = csv_info
            try:
                f_handle.flush()
            except Exception:
                pass
            output["csv_path"] = str(csv_path)
        elif processor.has_data:
            export_path = Path(app.root_path).parent / f"datos_pendulo_{session_id}.csv"
            processor.export_csv(str(export_path))
            output["csv_path"] = str(export_path)
    if not output.get("plot"):
        return jsonify({"error": "No se pudo generar la gráfica"}), 400
    return jsonify(output)


@app.route("/analysis/export_csv", methods=["POST"])
def analysis_export_csv():
    """
    Guarda el CSV de la sesión indicada.
    JSON esperado: {"session_id": "..."}.
    """
    payload = request.get_json(silent=True, force=True) or {}
    session_id = payload.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id es requerido"}), 400

    processor = session_store.get(session_id)
    if not processor or not processor.has_data:
        return jsonify({"error": "No hay datos para esa sesión"}), 404

    export_path = Path(app.root_path).parent / f"datos_pendulo_{session_id}.csv"
    processor.export_csv(str(export_path))
    return jsonify({"ok": True, "path": str(export_path)})


@app.route("/analysis/finalize_csv", methods=["POST"])
def analysis_finalize_csv():
    """
    Fuerza el guardado del CSV para la sesión indicada y devuelve la ruta.
    """
    payload = request.get_json(silent=True, force=True) or {}
    session_id = payload.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id es requerido"}), 400

    csv_info = session_csv_writers.get(session_id)
    if csv_info:
        csv_path, f_handle, _ = csv_info
        try:
            f_handle.flush()
        except Exception:
            pass
        return jsonify({"ok": True, "path": str(csv_path)})

    processor = session_store.get(session_id)
    if processor and processor.has_data:
        export_path = Path(app.root_path).parent / f"datos_pendulo_{session_id}.csv"
        processor.export_csv(str(export_path))
        return jsonify({"ok": True, "path": str(export_path)})

    return jsonify({"error": "No hay datos para esa sesión"}), 404


@app.route("/analysis/plot_csv", methods=["POST"])
def analysis_plot_csv():
    """
    Genera gráfica y stats a partir de un CSV ya guardado.
    Payload: {"session_id": "..."} o {"path": "<ruta_csv>"}.
    """
    payload = request.get_json(silent=True, force=True) or {}
    session_id = payload.get("session_id")
    path = payload.get("path")

    csv_path = None
    if path:
        csv_path = Path(path)
    elif session_id:
        csv_path = Path(app.root_path).parent / f"datos_pendulo_{session_id}.csv"

    if not csv_path or not csv_path.exists():
        return jsonify({"error": "CSV no encontrado"}), 404

    times: list[float] = []
    xs: list[float] = []
    ys: list[float] = []

    try:
        with open(csv_path, newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                if len(row) < 5:
                    continue
                _, t, x, y, _ = row
                times.append(float(t))
                xs.append(float(x))
                ys.append(float(y))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"No se pudo leer el CSV: {exc}"}), 400

    output = build_plot_and_stats(times, xs, ys)
    output["csv_path"] = str(csv_path)
    if not output.get("plot"):
        return jsonify({"error": "No se pudo generar la gráfica"}), 400
    return jsonify(output)


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
