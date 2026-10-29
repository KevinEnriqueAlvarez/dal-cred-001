"""Scorecard de referencia SC-CONS v1.0 (5 C's del crédito).

Es la tabla de puntos que el banco ficticio pone en producción el 1-ene-2026
para tarjeta y consumo. Cada variable observable se agrupa en rangos y cada
rango suma o resta puntos a una base de 600. Mayor puntaje = menor riesgo.

En F4 el científico de datos reentrena un scorecard con WoE y regresión
logística sobre las solicitudes de 2025; la validación compara ese modelo con
esta referencia (debe discriminar al menos igual: Gini >= 0,40).

Relación con las 5 C's:
- Carácter: atraso máximo en el SIRC y entidades con deuda.
- Capacidad: relación cuota/ingreso.
- Capital: endeudamiento total en el SIRC frente al ingreso.
- Condiciones: antigüedad laboral (estabilidad del ingreso).
- Colateral: no aplica a tarjeta y consumo (créditos sin garantía real).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PUNTAJE_BASE = 600

# (límite superior del rango, puntos). Rangos cerrados por la derecha: x <= límite.
TABLA_PUNTOS = {
    "atraso_max_sirc_12m": [(0, 40), (30, 5), (60, -25), (90, -45), (np.inf, -70)],
    "entidades_con_deuda_sirc": [(1, 15), (3, 0), (5, -15), (np.inf, -30)],
    "endeudamiento_sirc_meses_ingreso": [(2, 25), (4, 5), (7, -15), (np.inf, -35)],
    "relacion_cuota_ingreso": [(0.20, 15), (0.35, 0), (np.inf, -20)],
    "antiguedad_laboral_meses": [(12, -20), (36, 0), (120, 10), (np.inf, 20)],
}


def puntos_variable(valores: pd.Series | np.ndarray, rangos: list[tuple[float, int]]) -> np.ndarray:
    valores = np.asarray(valores, dtype=float)
    puntos = np.zeros_like(valores)
    asignado = np.zeros_like(valores, dtype=bool)
    for limite, pts in rangos:
        mascara = (valores <= limite) & ~asignado
        puntos[mascara] = pts
        asignado |= mascara
    return puntos


def calcular_score(solicitudes: pd.DataFrame) -> np.ndarray:
    """Devuelve el puntaje SC-CONS v1.0 de cada solicitud."""
    total = np.full(len(solicitudes), PUNTAJE_BASE, dtype=float)
    for variable, rangos in TABLA_PUNTOS.items():
        total += puntos_variable(solicitudes[variable], rangos)
    return total
