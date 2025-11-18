
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter

CSV_PATH = "datos_pendulo.csv"

PIVOT_X = 230   # ej.
PIVOT_Y = 120   # ej.

df = pd.read_csv(CSV_PATH)

# Por si acaso: ordenar por tiempo
df = df.sort_values("tiempo_s")

t = df["tiempo_s"].values
x = df["x"].values
y = df["y"].values

# 1) Suavizar trayectoria
window = 41 if len(x) > 50 else 9
if window >= len(x):
    window = len(x) - 1 if (len(x) - 1) % 2 == 1 else len(x) - 2  # asegurar impar < N

x_smooth = savgol_filter(x, window_length=window, polyorder=3)
y_smooth = savgol_filter(y, window_length=window, polyorder=3)

# 2) Calcular ángulo respecto a la vertical
dx = x_smooth - PIVOT_X
dy = y_smooth - PIVOT_Y
theta_rad = np.arctan2(dx, dy)
theta_deg = np.degrees(theta_rad)

# 3) Suavizar ángulo
theta_smooth = savgol_filter(theta_deg, window_length=window, polyorder=3)

# 4) Graficar
plt.figure(figsize=(6,8))
plt.plot(t, theta_deg, ".", alpha=0.2, label="Ángulo crudo (ruido)")
plt.plot(t, theta_smooth, "-", linewidth=2, label="Ángulo suavizado (real)")
plt.xlabel("Tiempo (s)")
plt.ylabel("Ángulo θ (grados)")
plt.title("Ángulo del péndulo vs tiempo (corregido)")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()

