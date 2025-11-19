#!/usr/bin/env python3
"""
Calcula magnitudes físicas de un péndulo simple a partir de los datos generados
por main.py (oscilaciones vs tiempo). Lee el CSV con las posiciones de la bola
y entrega un resumen con periodo, frecuencia, amplitud angular, etc.
"""

import argparse
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter


DEFAULT_CSV = "datos_pendulo.csv"
DEFAULT_PIVOT_X = 230
DEFAULT_PIVOT_Y = 120


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
    length_m: Optional[float]
    g_estimate: Optional[float]
    max_ang_velocity: float
    max_ang_acceleration: float
    max_linear_velocity: Optional[float]
    max_linear_acceleration: Optional[float]


def _savgol(values: np.ndarray, window: Optional[int], polyorder: int = 3) -> np.ndarray:
    if window is None:
        window = 41 if len(values) > 50 else 9
    window = min(window, len(values) - 1)
    if window % 2 == 0:
        window -= 1

    if window < polyorder + 2:
        return values

    return savgol_filter(values, window_length=window, polyorder=polyorder)


def _zero_crossings(times: np.ndarray, signal: np.ndarray) -> List[float]:
    crossings: List[float] = []
    for i in range(len(signal) - 1):
        y1, y2 = signal[i], signal[i + 1]
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
                crossings.append(t_cross)
    return crossings


def _prepare_angles(df: pd.DataFrame, pivot_x: float, pivot_y: float,
                    window: Optional[int]) -> np.ndarray:
    x = df["x"].to_numpy()
    y = df["y"].to_numpy()

    x_smooth = _savgol(x, window)
    y_smooth = _savgol(y, window)

    dx = x_smooth - pivot_x
    dy = y_smooth - pivot_y
    theta = np.arctan2(dx, dy)

    return _savgol(theta, window)


def compute_stats(csv_path: str,
                  pivot_x: float,
                  pivot_y: float,
                  window: Optional[int],
                  pixels_per_meter: Optional[float],
                  known_length_m: Optional[float]) -> PendulumStats:
    df = pd.read_csv(csv_path).sort_values("tiempo_s")
    if df.empty:
        raise ValueError("El CSV no contiene datos.")

    t = df["tiempo_s"].to_numpy()
    theta = _prepare_angles(df, pivot_x, pivot_y, window)
    theta_centered = theta - np.mean(theta)
    theta_deg = np.degrees(theta)

    crossings = _zero_crossings(t, theta_centered)

    oscillations = len(crossings) / 2 if crossings else 0.0
    half_periods = np.diff(crossings) if len(crossings) >= 2 else np.array([])
    period = float(np.median(half_periods) * 2) if half_periods.size else None
    frequency = (1.0 / period) if period and period > 0 else None
    angular_frequency = (2 * np.pi / period) if period and period > 0 else None

    total_time = float(t[-1] - t[0])

    dr = np.sqrt((df["x"] - pivot_x) ** 2 + (df["y"] - pivot_y) ** 2)
    length_px = float(dr.mean())

    length_m = None
    if known_length_m:
        length_m = known_length_m
    elif pixels_per_meter:
        length_m = length_px / pixels_per_meter

    g_estimate = None
    if period and length_m:
        g_estimate = 4 * np.pi ** 2 * length_m / (period ** 2)

    dt = np.gradient(t)
    theta_dot = np.gradient(theta, t)
    theta_ddot = np.gradient(theta_dot, t)
    max_ang_velocity = float(np.max(np.abs(theta_dot)))
    max_ang_acceleration = float(np.max(np.abs(theta_ddot)))

    max_linear_velocity = None
    max_linear_acceleration = None
    if length_m:
        max_linear_velocity = float(length_m * max_ang_velocity)
        max_linear_acceleration = float(length_m * max_ang_acceleration)

    return PendulumStats(
        total_time=total_time,
        samples=len(df),
        oscillations=oscillations,
        period=period,
        frequency=frequency,
        angular_frequency=angular_frequency,
        max_angle_deg=float(np.max(np.abs(theta_deg))),
        length_px=length_px,
        length_m=length_m,
        g_estimate=g_estimate,
        max_ang_velocity=max_ang_velocity,
        max_ang_acceleration=max_ang_acceleration,
        max_linear_velocity=max_linear_velocity,
        max_linear_acceleration=max_linear_acceleration,
    )


def _print_stats(stats: PendulumStats):
    print("[INFO] Resumen físico del péndulo simple")
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
    if stats.length_m:
        print(f"  Longitud real       : {stats.length_m:.4f} m")
    if stats.g_estimate:
        print(f"  g estimada          : {stats.g_estimate:.4f} m/s²")
    print(f"  |θ'| máx            : {stats.max_ang_velocity:.4f} rad/s")
    print(f"  |θ''| máx           : {stats.max_ang_acceleration:.4f} rad/s²")
    if stats.max_linear_velocity:
        print(f"  Velocidad lineal máx: {stats.max_linear_velocity:.4f} m/s")
    if stats.max_linear_acceleration:
        print(f"  Aceleración lineal  : {stats.max_linear_acceleration:.4f} m/s²")


def main():
    parser = argparse.ArgumentParser(
        description="Calcula magnitudes físicas de un péndulo simple a partir del CSV generado."
    )
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Ruta al archivo CSV con los datos.")
    parser.add_argument("--pivot-x", type=float, default=DEFAULT_PIVOT_X, help="Coordenada X del pivote.")
    parser.add_argument("--pivot-y", type=float, default=DEFAULT_PIVOT_Y, help="Coordenada Y del pivote.")
    parser.add_argument("--window", type=int, default=None, help="Ventana impar para Savitzky-Golay.")
    parser.add_argument("--pixels-per-meter", type=float, default=None,
                        help="Factor de conversión px/m. Permite obtener longitudes reales.")
    parser.add_argument("--length-m", type=float, default=None,
                        help="Longitud real del péndulo en metros (sobrescribe pixels-per-meter).")

    args = parser.parse_args()

    stats = compute_stats(
        csv_path=args.csv,
        pivot_x=args.pivot_x,
        pivot_y=args.pivot_y,
        window=args.window,
        pixels_per_meter=args.pixels_per_meter,
        known_length_m=args.length_m,
    )
    _print_stats(stats)


if __name__ == "__main__":
    main()
