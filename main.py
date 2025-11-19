import csv
from dataclasses import dataclass
from typing import Optional

import cv2
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import savgol_filter

VIDEO_PATH = "pendulo12.mp4"
OUTPUT_VIDEO = "pendulo_marcado.mp4"
CSV_PATH = "datos_pendulo.csv"

# ------------ CONFIGURACIÓN PARA BOLA NARANJA SOBRE FONDO NEGRO ------------

ORANGE_LOWER = np.array([5, 140, 80], dtype=np.uint8)   # H, S, V
ORANGE_UPPER = np.array([30, 255, 255], dtype=np.uint8)

MIN_CONTOUR_AREA = 100   # área mínima de la bola
DEAD_ZONE       = 5      # px alrededor del centro que se consideran "centro"

# Suavizado del centro (0 = no usa valor previo, 1 = no cambia nunca)
CENTER_ALPHA    = 0.8    # cuanto más alto, más suave/estable el centro
# ----------------------------------------------------------------------------

# ------------ CONFIGURACIÓN PARA LA GRÁFICA DEL ÁNGULO ----------------------
PIVOT_X = 230   # igual que en graficar.py (ajusta si hace falta)
PIVOT_Y = 120
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


def _update_angle_plot(ax, line_raw, line_smooth, times, xs, ys, pivot_x=None, pivot_y=None):
    """Actualiza la gráfica del ángulo del péndulo."""
    if not xs:
        return

    px = pivot_x if pivot_x is not None else PIVOT_X
    py = pivot_y if pivot_y is not None else PIVOT_Y

    arr_t = np.array(times)
    arr_x = np.array(xs)
    arr_y = np.array(ys)

    x_smooth = _savgol_or_original(arr_x)
    y_smooth = _savgol_or_original(arr_y)

    dx = x_smooth - px
    dy = y_smooth - py
    theta_deg = np.degrees(np.arctan2(dx, dy))
    theta_smooth = _savgol_or_original(theta_deg)

    line_raw.set_data(arr_t, theta_deg)
    line_smooth.set_data(arr_t, theta_smooth)
    ax.relim()
    ax.autoscale_view()
    plt.draw()
    plt.pause(0.001)


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


def _compute_physical_stats(times, xs, ys, pivot_x=None, pivot_y=None):
    """Calcula periodo, frecuencia, amplitud angular, etc."""
    if len(times) < 3:
        return None

    px = pivot_x if pivot_x is not None else PIVOT_X
    py = pivot_y if pivot_y is not None else PIVOT_Y

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


def _print_physical_stats(stats: PendulumStats):
    """Muestra en consola las magnitudes físicas estimadas."""
    print("\n[INFO] Resumen físico del péndulo simple")
    print(f"  Muestras analizadas : {stats.samples}")
    print(f"  Tiempo total        : {stats.total_time:.3f} s")
    print(f"  Oscilaciones        : {stats.oscillations:.2f}")
    if stats.period:
        print(f"  Periodo (T)         : {stats.period:.4f} s")
    if stats.frequency:
        print(f"  Frecuencia (f)      : {stats.frequency:.4f} Hz")
    if stats.angular_frequency:
        print(f"  Pulsación (ω)       : {stats.angular_frequency:.4f} rad/s")
    print(f"  Ángulo máximo       : {stats.max_angle_deg:.2f}°")
    print(f"  Longitud media      : {stats.length_px:.2f} px")
    print(f"  Centro usado        : X={stats.pivot_x:.2f}, Y={stats.pivot_y:.2f} px")
    print(f"  |θ'| máx            : {stats.max_ang_velocity:.4f} rad/s")
    print(f"  |θ''| máx           : {stats.max_ang_acceleration:.4f} rad/s²")


cap = cv2.VideoCapture(VIDEO_PATH)
if not cap.isOpened():
    print("No se pudo abrir el video:", VIDEO_PATH)
    exit()

fps = cap.get(cv2.CAP_PROP_FPS)
width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

print(f"FPS: {fps}, resolución: {width}x{height}")

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, fps, (width, height))

csv_file = open(CSV_PATH, "w", newline="")
csv_writer = csv.writer(csv_file)
csv_writer.writerow(["frame", "tiempo_s", "x", "y", "radio"])

ROI_TOP = int(height * 0.25)

kernel = np.ones((5, 5), np.uint8)
frame_idx = 0

cv2.namedWindow("Analisis", cv2.WINDOW_NORMAL)

# ==== Datos para la gráfica en vivo ====
time_series = []
x_series = []
y_series = []

plt.ion()
fig, ax = plt.subplots(figsize=(6, 8))
line_raw, = ax.plot([], [], ".", alpha=0.2, label="Ángulo crudo (ruido)")
line_smooth, = ax.plot([], [], "-", linewidth=2, label="Ángulo suavizado (real)")
ax.set_xlabel("Tiempo (s)")
ax.set_ylabel("Ángulo θ (grados)")
ax.set_title("Ángulo del péndulo vs tiempo (en tiempo real)")
ax.grid(True)
ax.legend()
fig.tight_layout()

# ==== Variables para contar oscilaciones ====
last_side    = 0
sign_changes = 0
oscillations = 0.0

# ==== Centro dinámico basado en vértices + línea blanca ====
center_x = None   # valor suavizado en X
line_y   = None   # posición vertical de la línea blanca
# ============================================

while True:
    ret, frame = cap.read()
    if not ret:
        break

    tiempo_s = frame_idx / fps
    display = frame.copy()

    # ================== 1) MITAD SUPERIOR (VÉRTICES + LÍNEA) ==================
    top_roi = frame[0:height // 2, :]

    hsv_top = cv2.cvtColor(top_roi, cv2.COLOR_BGR2HSV)
    gray_top = cv2.cvtColor(top_roi, cv2.COLOR_BGR2GRAY)

    # ---- Detectar vértices rojos ----
    lower_red1 = np.array([0, 100, 80], dtype=np.uint8)
    upper_red1 = np.array([10, 255, 255], dtype=np.uint8)
    lower_red2 = np.array([170, 100, 80], dtype=np.uint8)
    upper_red2 = np.array([180, 255, 255], dtype=np.uint8)

    mask_red1 = cv2.inRange(hsv_top, lower_red1, upper_red1)
    mask_red2 = cv2.inRange(hsv_top, lower_red2, upper_red2)
    mask_red = cv2.bitwise_or(mask_red1, mask_red2)

    mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_OPEN, kernel, iterations=1)
    mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_CLOSE, kernel, iterations=1)

    conts_center, _ = cv2.findContours(mask_red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    puntos_vertices = []

    for c in conts_center:
        area = cv2.contourArea(c)
        if area < 10:   # evita ruido muy pequeño, ajusta si hace falta
            continue

        M = cv2.moments(c)
        if M["m00"] == 0:
            continue

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        # Coordenadas globales
        gx = cx
        gy = cy  # entre 0 y height//2

        puntos_vertices.append((gx, gy))

    # ---- Detectar línea blanca horizontal ----
    _, bin_white = cv2.threshold(gray_top, 200, 255, cv2.THRESH_BINARY)
    bin_white = cv2.morphologyEx(bin_white, cv2.MORPH_OPEN, kernel, iterations=1)
    bin_white = cv2.morphologyEx(bin_white, cv2.MORPH_CLOSE, kernel, iterations=1)

    conts_white, _ = cv2.findContours(bin_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidate_line_y = None
    max_width = 0

    for c in conts_white:
        xw, yw, ww, hw = cv2.boundingRect(c)
        # filtro: línea más o menos horizontal y relativamente larga
        if ww > max_width and ww > width * 0.4 and hw < 30:
            max_width = ww
            candidate_line_y = yw + hw // 2

    if candidate_line_y is not None:
        # actualizar y de la línea blanca (sin suavizado o con si quieres)
        line_y = candidate_line_y

        # Dibujar la línea detectada
        cv2.line(display,
                 (0, line_y),
                 (width, line_y),
                 (255, 255, 255), 2)
        cv2.putText(display, "Linea blanca", (10, line_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # ---- Calcular centro en X a partir de vértices ----
    if len(puntos_vertices) >= 2:
        # Ordenamos por x y tomamos el más izquierdo y el más derecho
        puntos_vertices.sort(key=lambda p: p[0])
        v_left = puntos_vertices[0]
        v_right = puntos_vertices[-1]

        x_left, y_left = v_left
        x_right, y_right = v_right

        center_measured = (x_left + x_right) / 2.0

        # Inicializar o suavizar centro X
        if center_x is None:
            center_x = center_measured
        else:
            center_x = CENTER_ALPHA * center_x + (1.0 - CENTER_ALPHA) * center_measured

        # Dibujar todos los vértices detectados en rojo
        for i, (vx, vy) in enumerate(puntos_vertices):
            cv2.circle(display, (vx, vy), 6, (0, 0, 255), -1)
            cv2.putText(display, f"V{i+1}", (vx + 5, vy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # Marcar los dos vértices usados para el centro
        cv2.circle(display, (x_left, y_left), 8, (0, 255, 0), 2)
        cv2.circle(display, (x_right, y_right), 8, (0, 255, 0), 2)
        cv2.line(display, (x_left, y_left), (x_right, y_right), (0, 255, 0), 2)

    # ================== 2) DETECCIÓN DE LA BOLA NARANJA ==================
    roi = frame[ROI_TOP:, :]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    mask = cv2.inRange(hsv, ORANGE_LOWER, ORANGE_UPPER)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if contours and center_x is not None:
        c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(c) > MIN_CONTOUR_AREA:
            (x_roi, y_roi), radius = cv2.minEnclosingCircle(c)
            x = int(x_roi)
            y = int(y_roi + ROI_TOP)
            r = int(radius)

            # ---- GUARDAR EN CSV ----
            csv_writer.writerow([frame_idx, tiempo_s, x, y, r])

            # ---- CONTAR OSCILACIONES USANDO CENTRO DINÁMICO EN X ----
            dx = x - center_x
            if abs(dx) <= DEAD_ZONE:
                side = 0
            else:
                side = 1 if dx > 0 else -1

            if last_side != 0 and side != 0 and side != last_side:
                sign_changes += 1
                oscillations = sign_changes // 2

            if side != 0:
                last_side = side

            # ---- DIBUJAR BOLA ----
            cv2.circle(display, (x, y), r, (0, 165, 255), 3)
            cv2.circle(display, (x, y), 3, (0, 255, 0), -1)

            x1, y1 = max(0, x - r), max(ROI_TOP, y - r)
            x2, y2 = min(width, x + r), min(height, y + r)
            cv2.rectangle(display, (x1, y1), (x2, y2), (0, 200, 255), 2)

            # ---- Actualizar gráfica del ángulo ----
            time_series.append(tiempo_s)
            x_series.append(x)
            y_series.append(y)
            _update_angle_plot(
                ax,
                line_raw,
                line_smooth,
                time_series,
                x_series,
                y_series,
                pivot_x=center_x,
                pivot_y=line_y,
            )

    # ================== 3) MARCAR EL CENTRO ACTUAL ==================
    center_x_int = int(center_x) if center_x is not None else width // 2 
    center_y_int = int(line_y) if line_y is not None else height // 2

    cv2.line(display, (center_x_int, 0), (center_x_int, height), (0, 0, 255), 2)
    cv2.circle(display, (center_x_int, center_y_int), 8, (0, 255, 255), -1)
    cv2.putText(display, "Centro", (center_x_int + 10, center_y_int),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    # ---- Texto en pantalla ----
    cv2.putText(display, f"Tiempo: {tiempo_s:.2f} s", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 0), 3)

    cv2.putText(display, f"Oscilaciones: {int(oscillations)}", (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

    # Línea mostrando inicio de la ROI inferior
    cv2.line(display, (0, ROI_TOP), (width, ROI_TOP), (255, 0, 0), 2)

    cv2.imshow("Analisis", display)
    out.write(display)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

    frame_idx += 1

cap.release()
out.release()
csv_file.close()
cv2.destroyAllWindows()
plt.ioff()
plt.show()

pivot_x_for_stats = center_x if center_x is not None else PIVOT_X
pivot_y_for_stats = line_y if line_y is not None else PIVOT_Y

stats = _compute_physical_stats(
    time_series,
    x_series,
    y_series,
    pivot_x=pivot_x_for_stats,
    pivot_y=pivot_y_for_stats,
)
if stats:
    _print_physical_stats(stats)
else:
    print("\n[OPERACION] No hay suficientes datos para estimar las magnitudes físicas.")

print("\n[RESULTADOS] Listo")
print("[RESULTADOS] Video marcado:", OUTPUT_VIDEO)
print("[RESULTADOS] Datos guardados en:", CSV_PATH)
print(f"[RESULTADOS] Oscilaciones detectadas: {int(oscillations)}")
