"""Mayor contable, garantías y castigos.

El mayor contable es la fuente independiente contra la que se concilia la
cartera (control OB-02 y exactitud BCBS 239). Se construye desde los saldos
limpios y se le agregan diferencias pequeñas, como las partidas en tránsito de
un banco real, que deben quedar dentro del umbral de 0,01 %.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .catalogos import CUENTAS_CONTABLES


def mayor_contable(rng: np.random.Generator, saldos: pd.DataFrame, creditos: pd.DataFrame) -> pd.DataFrame:
    base = saldos.merge(creditos[["prestamo_id", "producto_codigo"]], on="prestamo_id")
    mayor = base.groupby(["periodo", "producto_codigo"], as_index=False)["saldo_capital"].sum()
    # Partidas en tránsito: diferencia aleatoria de hasta ±0,004 % del saldo.
    mayor["saldo_contable"] = (mayor.saldo_capital * (1 + rng.uniform(-0.00004, 0.00004, len(mayor)))).round(2)
    mayor["cuenta_contable"] = mayor.producto_codigo.map(CUENTAS_CONTABLES)
    mayor["fecha_corte"] = pd.PeriodIndex(mayor.periodo, freq="M").end_time.normalize()
    return mayor[["periodo", "fecha_corte", "cuenta_contable", "producto_codigo", "saldo_contable"]]


def garantias(rng: np.random.Generator, creditos: pd.DataFrame) -> pd.DataFrame:
    """Garantías reales de hipotecarios y empresariales (la tarjeta y el consumo no tienen)."""
    con_garantia = creditos[creditos.producto_codigo.isin(["HIPO", "EMP_MAYOR", "EMP_MENOR"])]
    n = len(con_garantia)
    tipo = np.where(
        con_garantia.producto_codigo == "HIPO",
        "Hipotecaria",
        rng.choice(["Hipotecaria", "Prendaria", "Fiduciaria"], n, p=[0.55, 0.30, 0.15]),
    )
    ltv = np.clip(rng.normal(0.72, 0.08, n), 0.45, 0.95)
    valor = np.where(tipo == "Fiduciaria", 0.0, con_garantia.monto_desembolsado.to_numpy() / ltv)
    return pd.DataFrame(
        {
            "garantia_id": [f"GA-{i:06d}" for i in range(1, n + 1)],
            "prestamo_id": con_garantia.prestamo_id.to_numpy(),
            "tipo_garantia": tipo,
            "valor_avaluo": valor.round(-2),
            "fecha_avaluo": (
                pd.to_datetime(con_garantia.fecha_desembolso) - pd.to_timedelta(rng.integers(10, 60, n), unit="D")
            ).dt.date.to_numpy(),
        }
    )


def castigos(creditos: pd.DataFrame) -> pd.DataFrame:
    c = creditos[creditos.estado_final == "Castigado"]
    return pd.DataFrame(
        {
            "prestamo_id": c.prestamo_id,
            "fecha_castigo": c.fecha_fin.dt.date,
            "saldo_castigado": c.saldo_castigado,
        }
    ).reset_index(drop=True)
