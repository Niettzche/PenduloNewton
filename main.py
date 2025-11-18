import cv2
import numpy as np
import csv

VIDEO_PATH = "pendulo8.mp4"
OUTPUT_VIDEO = "pendulo_marcado.mp4"
CSV_PATH = "datos_pendulo.csv"

# ------------ CONFIGURACIÓN PARA BOLA NARANJA SOBRE FONDO NEGRO ------------

# HSV optimizado para color naranja brillante
# Ajustado con base en cámaras móviles y luz LED
ORANGE_LOWER = np.array([5, 140, 80], dtype=np.uint8)
ORANGE_UPPER = np.array([30, 255, 255], dtype=np.uint8)

# ÁREA mínima detectada (evita puntos falsos)
MIN_CONTOUR_AREA = 100

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

# ROI inicial para evitar procesar todo el video
ROI_TOP = int(height * 0.25)

frame_idx = 0
kernel = np.ones((5, 5), np.uint8)

cv2.namedWindow("Analisis", cv2.WINDOW_NORMAL)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    tiempo_s = frame_idx / fps
    display = frame.copy()

    # ---- Recortar área donde está el péndulo ----
    roi = frame[ROI_TOP:, :]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # ---- Detección por color naranjado ----
    mask = cv2.inRange(hsv, ORANGE_LOWER, ORANGE_UPPER)

    # Limpieza (elimina puntos aislados)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if contours:
        c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(c) > MIN_CONTOUR_AREA:

            (x_roi, y_roi), radius = cv2.minEnclosingCircle(c)
            x = int(x_roi)
            y = int(y_roi + ROI_TOP)
            r = int(radius)

            # ---- GUARDAR DATOS ----
            csv_writer.writerow([frame_idx, tiempo_s, x, y, r])

            # ---- DIBUJAR EN EL VIDEO ----
            cv2.circle(display, (x, y), r, (0, 165, 255), 3)  # círculo naranja
            cv2.circle(display, (x, y), 3, (0, 255, 0), -1)  # centro

            # Rectángulo alrededor
            x1, y1 = max(0, x - r), max(ROI_TOP, y - r)
            x2, y2 = min(width, x + r), min(height, y + r)
            cv2.rectangle(display, (x1, y1), (x2, y2), (0, 200, 255), 2)

    # ---- Información en pantalla ----
    cv2.putText(display, f"Tiempo: {tiempo_s:.2f} s", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 0), 3)

    # Línea mostrando ROI
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

print("\n[INFO] Listo")
print("[INFO] Video marcado:", OUTPUT_VIDEO)
print("[INFO] Datos guardados en:", CSV_PATH)
