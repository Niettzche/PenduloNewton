import base64
import csv
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from scipy.signal import savgol_filter

# ------------ CONFIGURACIÓN PARA BOLA NARANJA SOBRE FONDO NEGRO ------------
ORANGE_LOWER = np.array([5, 140, 80], dtype=np.uint8)  # H, S, V
ORANGE_UPPER = np.array([30, 255, 255], dtype=np.uint8)

MIN_CONTOUR_AREA = 100  # área mínima de la bola
DEAD_ZONE = 5  # px alrededor del centro que se consideran "centro"

# Suavizado del centro (0 = no usa valor previo, 1 = no cambia nunca)
CENTER_ALPHA = 0.8  # cuanto más alto, más suave/estable el centro
# ----------------------------------------------------------------------------


def _savgol_or_original(values, polyorder=3):
    """Devuelve la señal suavizada si hay suficientes datos para Savitzky-Golay."""
    count = len(values)
    if count < polyorder + 2:
        return np.array(values)

    window = 41 if count > 50 else 9
    if window >= count:
        window = count if count % 2 == 1 else count - 1

    if window < polyorder + 2:
        return np.array(values)

    return savgol_filter(values, window_length=window, polyorder=polyorder)


def _zero_crossings(times, signal):
    """Devuelve los instantes donde la señal cruza por cero."""
    crossings = []
    for i in range(len(signal) - 1):
        y1 = signal[i]
        y2 = signal[i + 1]
        if y1 == 0 and y2 == 0:
            continue
        if y1 == 0:
            crossings.append(float(times[i]))
            continue
        if y2 == 0:
            crossings.append(float(times[i + 1]))
            continue
        if y1 * y2 < 0:
            frac = -y1 / (y2 - y1)
            if 0 <= frac <= 1:
                t_cross = times[i] + frac * (times[i + 1] - times[i])
                crossings.append(float(t_cross))
    return crossings


@dataclass
class PendulumStats:
    total_time: float
    samples: int
    oscillations: float
    period: Optional[float]
    frequency: Optional[float]
    angular_frequency: Optional[float]
    max_angle_deg: float
    length_px: float
    max_ang_velocity: float
    max_ang_acceleration: float
    pivot_x: float
    pivot_y: float


def _compute_physical_stats(times, xs, ys, pivot_x=None, pivot_y=None, fallback_px=230, fallback_py=120):
    """Calcula periodo, frecuencia, amplitud angular, etc."""
    if len(times) < 3:
        return None

    px = pivot_x if pivot_x is not None else fallback_px
    py = pivot_y if pivot_y is not None else fallback_py

    arr_t = np.array(times)
    arr_x = _savgol_or_original(xs)
    arr_y = _savgol_or_original(ys)

    dx = arr_x - px
    dy = arr_y - py

    theta = np.arctan2(dx, dy)
    theta_centered = theta - np.mean(theta)
    theta_deg = np.degrees(theta)

    crossings = _zero_crossings(arr_t, theta_centered)
    oscillations = len(crossings) / 2 if crossings else 0.0
    half_periods = np.diff(crossings) if len(crossings) >= 2 else np.array([])

    period = float(np.median(half_periods) * 2) if half_periods.size else None
    frequency = (1.0 / period) if period and period > 0 else None
    angular_frequency = (2 * np.pi / period) if period and period > 0 else None

    total_time = float(arr_t[-1] - arr_t[0]) if len(arr_t) > 1 else 0.0
    length_px = float(np.mean(np.sqrt(dx ** 2 + dy ** 2)))

    theta_dot = np.gradient(theta, arr_t)
    theta_ddot = np.gradient(theta_dot, arr_t)

    max_ang_velocity = float(np.max(np.abs(theta_dot)))
    max_ang_acceleration = float(np.max(np.abs(theta_ddot)))

    return PendulumStats(
        total_time=total_time,
        samples=len(arr_t),
        oscillations=oscillations,
        period=period,
        frequency=frequency,
        angular_frequency=angular_frequency,
        max_angle_deg=float(np.max(np.abs(theta_deg))),
        length_px=length_px,
        max_ang_velocity=max_ang_velocity,
        max_ang_acceleration=max_ang_acceleration,
        pivot_x=float(px),
        pivot_y=float(py),
    )


class PendulumProcessor:
    """
    Procesa frames de video de un péndulo para detectar la bola, medir ángulos
    y devolver un frame marcado más metadatos. Mantiene estado entre frames.
    """

    def __init__(self, fps: float = 30.0, pivot_x: int = 230, pivot_y: int = 120, enable_plot: bool = False):
        self.fps = fps
        self.default_pivot_x = pivot_x
        self.default_pivot_y = pivot_y
        self.enable_plot = enable_plot

        self.frame_idx = 0
        self.time_series: List[float] = []
        self.x_series: List[int] = []
        self.y_series: List[int] = []
        self.records: List[Tuple[int, float, int, int, int]] = []

        self.center_x: Optional[float] = None
        self.line_y: Optional[int] = None

        self.last_side = 0
        self.sign_changes = 0
        self.oscillations = 0.0

        self.kernel = np.ones((5, 5), np.uint8)

    def _detect_vertices_and_line(self, frame, display):
        """Detecta vértices rojos y la línea blanca, actualiza center_x y line_y."""
        height, width = frame.shape[:2]
        top_roi = frame[0:height // 2, :]

        hsv_top = cv2.cvtColor(top_roi, cv2.COLOR_BGR2HSV)
        gray_top = cv2.cvtColor(top_roi, cv2.COLOR_BGR2GRAY)

        lower_red1 = np.array([0, 100, 80], dtype=np.uint8)
        upper_red1 = np.array([10, 255, 255], dtype=np.uint8)
        lower_red2 = np.array([170, 100, 80], dtype=np.uint8)
        upper_red2 = np.array([180, 255, 255], dtype=np.uint8)

        mask_red1 = cv2.inRange(hsv_top, lower_red1, upper_red1)
        mask_red2 = cv2.inRange(hsv_top, lower_red2, upper_red2)
        mask_red = cv2.bitwise_or(mask_red1, mask_red2)

        mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_OPEN, self.kernel, iterations=1)
        mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_CLOSE, self.kernel, iterations=1)

        conts_center, _ = cv2.findContours(mask_red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        puntos_vertices = []

        for c in conts_center:
            area = cv2.contourArea(c)
            if area < 10:
                continue

            M = cv2.moments(c)
            if M["m00"] == 0:
                continue

            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])

            gx = cx
            gy = cy
            puntos_vertices.append((gx, gy))

        _, bin_white = cv2.threshold(gray_top, 200, 255, cv2.THRESH_BINARY)
        bin_white = cv2.morphologyEx(bin_white, cv2.MORPH_OPEN, self.kernel, iterations=1)
        bin_white = cv2.morphologyEx(bin_white, cv2.MORPH_CLOSE, self.kernel, iterations=1)

        conts_white, _ = cv2.findContours(bin_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidate_line_y = None
        max_width = 0

        for c in conts_white:
            xw, yw, ww, hw = cv2.boundingRect(c)
            if ww > max_width and ww > width * 0.4 and hw < 30:
                max_width = ww
                candidate_line_y = yw + hw // 2

        if candidate_line_y is not None:
            self.line_y = candidate_line_y
            cv2.line(display, (0, self.line_y), (width, self.line_y), (255, 255, 255), 2)
            cv2.putText(display, "Linea blanca", (10, self.line_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        if len(puntos_vertices) >= 2:
            puntos_vertices.sort(key=lambda p: p[0])
            v_left = puntos_vertices[0]
            v_right = puntos_vertices[-1]

            x_left, y_left = v_left
            x_right, y_right = v_right

            center_measured = (x_left + x_right) / 2.0

            if self.center_x is None:
                self.center_x = center_measured
            else:
                self.center_x = CENTER_ALPHA * self.center_x + (1.0 - CENTER_ALPHA) * center_measured

            for i, (vx, vy) in enumerate(puntos_vertices):
                cv2.circle(display, (vx, vy), 6, (0, 0, 255), -1)
                cv2.putText(display, f"V{i+1}", (vx + 5, vy - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            cv2.circle(display, (x_left, y_left), 8, (0, 255, 0), 2)
            cv2.circle(display, (x_right, y_right), 8, (0, 255, 0), 2)
            cv2.line(display, (x_left, y_left), (x_right, y_right), (0, 255, 0), 2)

    def process_frame(self, frame: np.ndarray, timestamp: Optional[float] = None) -> Tuple[np.ndarray, Dict]:
        """
        Procesa un solo frame y devuelve (frame_marcado, info_dict).
        timestamp: tiempo en segundos si viene del cliente; si no, se usa frame_idx / fps.
        """
        height, width = frame.shape[:2]
        roi_top = int(height * 0.25)
        tiempo_s = float(timestamp) if timestamp is not None else (self.frame_idx / self.fps if self.fps else float(self.frame_idx))

        display = frame.copy()

        self._detect_vertices_and_line(frame, display)

        roi = frame[roi_top:, :]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        mask = cv2.inRange(hsv, ORANGE_LOWER, ORANGE_UPPER)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        info: Dict[str, Optional[float]] = {
            "time_s": tiempo_s,
            "x": None,
            "y": None,
            "radius": None,
            "oscillations": self.oscillations,
            "center_x": self.center_x,
            "line_y": self.line_y,
        }

        if contours and self.center_x is not None:
            c = max(contours, key=cv2.contourArea)
            if cv2.contourArea(c) > MIN_CONTOUR_AREA:
                (x_roi, y_roi), radius = cv2.minEnclosingCircle(c)
                x = int(x_roi)
                y = int(y_roi + roi_top)
                r = int(radius)

                self.records.append((self.frame_idx, tiempo_s, x, y, r))

                dx = x - self.center_x
                if abs(dx) <= DEAD_ZONE:
                    side = 0
                else:
                    side = 1 if dx > 0 else -1

                if self.last_side != 0 and side != 0 and side != self.last_side:
                    self.sign_changes += 1
                    self.oscillations = self.sign_changes // 2

                if side != 0:
                    self.last_side = side

                cv2.circle(display, (x, y), r, (0, 165, 255), 3)
                cv2.circle(display, (x, y), 3, (0, 255, 0), -1)

                x1, y1 = max(0, x - r), max(roi_top, y - r)
                x2, y2 = min(width, x + r), min(height, y + r)
                cv2.rectangle(display, (x1, y1), (x2, y2), (0, 200, 255), 2)

                self.time_series.append(tiempo_s)
                self.x_series.append(x)
                self.y_series.append(y)

                info.update(
                    {
                        "x": float(x),
                        "y": float(y),
                        "radius": float(r),
                        "oscillations": float(self.oscillations),
                        "center_x": float(self.center_x) if self.center_x is not None else None,
                        "line_y": float(self.line_y) if self.line_y is not None else None,
                    }
                )

        center_x_int = int(self.center_x) if self.center_x is not None else width // 2
        center_y_int = int(self.line_y) if self.line_y is not None else height // 2

        cv2.line(display, (center_x_int, 0), (center_x_int, height), (0, 0, 255), 2)
        cv2.circle(display, (center_x_int, center_y_int), 8, (0, 255, 255), -1)
        cv2.putText(display, "Centro", (center_x_int + 10, center_y_int), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        cv2.putText(display, f"Tiempo: {tiempo_s:.2f} s", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 0), 3)
        cv2.putText(display, f"Oscilaciones: {int(self.oscillations)}", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

        cv2.line(display, (0, roi_top), (width, roi_top), (255, 0, 0), 2)

        self.frame_idx += 1
        return display, info

    def get_stats(self) -> Optional[PendulumStats]:
        pivot_x = self.center_x if self.center_x is not None else self.default_pivot_x
        pivot_y = self.line_y if self.line_y is not None else self.default_pivot_y
        return _compute_physical_stats(self.time_series, self.x_series, self.y_series, pivot_x=pivot_x, pivot_y=pivot_y, fallback_px=pivot_x, fallback_py=pivot_y)

    def export_csv(self, path: str):
        """Guarda los datos de (frame, tiempo, x, y, radio) en un CSV."""
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["frame", "tiempo_s", "x", "y", "radio"])
            writer.writerows(self.records)


def b64_to_frame(b64_data: str) -> np.ndarray:
    """Decode base64-encoded JPEG/PNG string to an OpenCV BGR frame."""
    return cv2.imdecode(np.frombuffer(base64.b64decode(b64_data), np.uint8), cv2.IMREAD_COLOR)


def frame_to_b64(frame: np.ndarray) -> str:
    """Encode an OpenCV BGR frame to base64-encoded JPEG."""
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        raise ValueError("Failed to encode frame")
    return base64.b64encode(buf).decode()


def decode_ws_message(message) -> Tuple[np.ndarray, Optional[float], Optional[float]]:
    """
    Decodifica un mensaje WebSocket que puede ser:
    - JSON con {frame: <b64>, fps?, timestamp?}
    - Texto base64
    - Binario con la imagen comprimida
    Devuelve (frame_bgr, fps_override, timestamp).
    """
    fps_override = None
    timestamp = None

    if isinstance(message, bytes):
        arr = np.frombuffer(message, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            return frame, fps_override, timestamp
        try:
            message = message.decode()
        except Exception as exc:
            raise ValueError("No se pudo decodificar mensaje binario") from exc

    if isinstance(message, str) and message.lstrip().startswith("{"):
        payload = json.loads(message)
        if "fps" in payload:
            fps_override = float(payload["fps"])
        if "timestamp" in payload:
            timestamp = float(payload["timestamp"])
        frame_b64 = payload.get("frame")
        if not frame_b64:
            raise ValueError("El JSON debe incluir 'frame' en base64")
        frame = b64_to_frame(frame_b64)
        return frame, fps_override, timestamp

    if isinstance(message, str):
        frame = b64_to_frame(message)
        return frame, fps_override, timestamp

    raise ValueError("Formato de mensaje no soportado")
