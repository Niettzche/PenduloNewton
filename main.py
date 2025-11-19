import cv2
import numpy as np
import csv

VIDEO_PATH = "pendulo10.mp4"
OUTPUT_VIDEO = "pendulo_marcado.mp4"
CSV_PATH = "datos_pendulo.csv"

# ------------ CONFIGURACIÓN PARA BOLA NARANJA SOBRE FONDO NEGRO ------------

ORANGE_LOWER = np.array([5, 140, 80], dtype=np.uint8)   # H, S, V
ORANGE_UPPER = np.array([30, 255, 255], dtype=np.uint8)

MIN_CONTOUR_AREA = 100   # área mínima de la bola
DEAD_ZONE       = 5      # px alrededor de la línea central que se consideran "centro"

# Suavizado del centro (0 = no usa valor previo, 1 = no cambia nunca)
CENTER_ALPHA    = 0.8    # cuanto más alto, más suave/estable el centro
# ----------------------------------------------------------------------------

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

# ==== Variables para contar oscilaciones ====
last_side    = 0
sign_changes = 0
oscillations = 0.0
# ==== Centro dinámico ====
center_x = None   # valor suavizado
# =========================

while True:
    ret, frame = cap.read()
    if not ret:
        break

    tiempo_s = frame_idx / fps
    display = frame.copy()

    # ---- 1) ACTUALIZAR CENTRO A PARTIR DE LA LÍNEA BLANCA ----
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, bin_img = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

    # Usamos solo la mitad superior (por ejemplo) para buscar la línea
    bin_roi = bin_img[0:height//2, :]
    ys, xs = np.where(bin_roi == 255)

    if len(xs) > 0:
        center_x_measured = float(np.median(xs))

        if center_x is None:
            center_x = center_x_measured
        else:
            # Suavizado exponencial
            center_x = CENTER_ALPHA * center_x + (1.0 - CENTER_ALPHA) * center_x_measured

    # Si aún no hemos estimado el centro, evitamos usarlo
    center_x_int = int(center_x) if center_x is not None else width // 2

    # ---- 2) DETECCIÓN DE LA BOLA NARANJA EN LA ROI INFERIOR ----
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

            # ---- CONTAR OSCILACIONES USANDO CENTRO DINÁMICO ----
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

    # ---- 3) MARCAR EL CENTRO ACTUAL ----
    cv2.line(display, (center_x_int, 0), (center_x_int, height), (0, 0, 255), 2)
    cv2.circle(display, (center_x_int, height // 2), 8, (0, 255, 255), -1)
    cv2.putText(display, "Centro", (center_x_int + 10, height // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    # ---- Texto en pantalla ----
    cv2.putText(display, f"Tiempo: {tiempo_s:.2f} s", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 0), 3)

    cv2.putText(display, f"Oscilaciones: {int(oscillations)}", (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

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

print("\n✅ Listo")
print("📁 Video marcado:", OUTPUT_VIDEO)
print("📄 Datos guardados en:", CSV_PATH)
print(f"🔁 Oscilaciones detectadas: {int(oscillations)}")
