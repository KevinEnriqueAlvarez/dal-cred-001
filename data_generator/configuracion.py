"""Carga y valida los parámetros del generador (config/parametros.yaml).

Todos los supuestos viven en el YAML; este módulo los convierte en un objeto
tipado y calcula el calendario de meses que recorre la simulación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

RUTA_PARAMETROS = Path(__file__).parent / "config" / "parametros.yaml"

# Un año completo antes del periodo se simula pero no se escribe ("burn-in"):
# así la cartera inicial llega a enero de 2025 con una mezcla realista de
# créditos al día, en mora y cosechas de 2024.
MESES_BURN_IN = 12


@dataclass
class Parametros:
    """Parámetros del generador ya validados."""

    crudo: dict
    semilla: int
    escala: float
    periodo_inicio: date
    fecha_go_live: date
    fecha_corte: date
    periodo_fin: date
    stock_desde: date
    productos: dict = field(default_factory=dict)

    @property
    def meses_simulados(self) -> pd.PeriodIndex:
        """Meses que recorre la simulación: burn-in + periodo real hasta el corte."""
        inicio = pd.Period(self.periodo_inicio, freq="M") - MESES_BURN_IN
        fin = pd.Period(self.fecha_corte, freq="M")
        return pd.period_range(inicio, fin, freq="M")

    @property
    def meses_publicados(self) -> pd.PeriodIndex:
        """Meses que se escriben en los archivos (enero 2025 hasta el corte)."""
        return pd.period_range(
            pd.Period(self.periodo_inicio, freq="M"),
            pd.Period(self.fecha_corte, freq="M"),
            freq="M",
        )

    def seccion(self, nombre: str) -> dict:
        return self.crudo[nombre]


def _fecha(texto: str) -> date:
    return date.fromisoformat(texto)


def cargar(ruta: Path | str | None = None, escala: float | None = None) -> Parametros:
    """Lee el YAML, aplica una escala opcional y valida coherencia de fechas."""
    ruta = Path(ruta) if ruta else RUTA_PARAMETROS
    with open(ruta, encoding="utf-8") as archivo:
        crudo = yaml.safe_load(archivo)

    p = crudo["periodo"]
    parametros = Parametros(
        crudo=crudo,
        semilla=int(crudo["semilla"]),
        escala=float(escala if escala is not None else crudo["escala"]),
        periodo_inicio=_fecha(p["periodo_inicio"]),
        fecha_go_live=_fecha(p["fecha_go_live"]),
        fecha_corte=_fecha(p["fecha_corte"]),
        periodo_fin=_fecha(p["periodo_fin"]),
        stock_desde=_fecha(p["stock_desde"]),
        productos=crudo["productos"],
    )
    _validar(parametros)
    return parametros


def _validar(p: Parametros) -> None:
    if not (p.stock_desde < p.periodo_inicio <= p.fecha_go_live <= p.fecha_corte <= p.periodo_fin):
        raise ValueError(
            "Fechas incoherentes: debe cumplirse stock_desde < periodo_inicio <= "
            "fecha_go_live <= fecha_corte <= periodo_fin"
        )
    if p.escala <= 0:
        raise ValueError("La escala debe ser mayor que cero")
    suma = sum(v["participacion_objetivo"] for v in p.productos.values())
    if abs(suma - 1.0) > 0.001:
        raise ValueError(f"Las participaciones objetivo suman {suma:.3f}, deben sumar 1")
