"""Reporte de calibración: compara lo generado contra los objetivos de los parámetros.

Uso:
    python -m data_generator.calibracion --escala 0.2

Imprime la mezcla de cartera, la mora 30+ por producto y periodo, el efecto del
go-live sobre las cosechas y la deterioración de las cosechas de la política P-07.
"""

from __future__ import annotations

import argparse
import time
from math import isnan

import numpy as np
import pandas as pd

from . import configuracion
from .generador import Resultado, generar


def base_saldos(r: Resultado) -> pd.DataFrame:
    return r.saldos.merge(r.prestamos[["prestamo_id", "producto_codigo", "fecha_desembolso", "politica_id"]])


def mora_por_periodo(r: Resultado, umbral: int = 30) -> pd.DataFrame:
    b = base_saldos(r)
    b["en_mora"] = np.where(b.dias_atraso > umbral, b.saldo_capital, 0.0)
    g = b.groupby(["periodo", "producto_codigo"])[["en_mora", "saldo_capital"]].sum()
    tabla = (g.en_mora / g.saldo_capital).unstack()
    total = b.groupby("periodo")[["en_mora", "saldo_capital"]].sum()
    tabla["TOTAL"] = total.en_mora / total.saldo_capital
    return tabla


def mezcla_al_corte(r: Resultado, corte: str) -> pd.Series:
    b = base_saldos(r)
    s = b[b.periodo == corte].groupby("producto_codigo").saldo_capital.sum()
    return s


def cosechas(r: Resultado, producto: str, mob: int) -> pd.Series:
    """Mora 30+ (saldo) a `mob` meses de cada mes de desembolso del producto."""
    b = base_saldos(r)
    b = b[b.producto_codigo == producto].copy()
    b["cosecha"] = pd.PeriodIndex(b.fecha_desembolso, freq="M")
    b["mob"] = pd.PeriodIndex(b.periodo, freq="M").asi8 - b.cosecha.astype("period[M]").array.asi8
    m = b[b.mob == mob]
    m = m.assign(en_mora=np.where(m.dias_atraso > 30, m.saldo_capital, 0.0))
    g = m.groupby("cosecha")[["en_mora", "saldo_capital"]].sum()
    return (g.en_mora / g.saldo_capital).round(4)


def cosechas_agrupadas(r: Resultado, productos: list[str], mob: int) -> dict:
    b = base_saldos(r)
    b = b[b.producto_codigo.isin(productos)].copy()
    b["mob"] = pd.PeriodIndex(b.periodo, freq="M").asi8 - pd.PeriodIndex(b.fecha_desembolso, freq="M").asi8
    b["anio"] = pd.to_datetime(b.fecha_desembolso).dt.year
    m = b[(b.mob == mob) & b.anio.isin([2025, 2026])]
    m = m.assign(en_mora=np.where(m.dias_atraso > 30, m.saldo_capital, 0.0))
    g = m.groupby("anio")[["en_mora", "saldo_capital"]].sum()
    return {int(k): round(float(v) * 100, 2) for k, v in (g.en_mora / g.saldo_capital).items()}


def gini_referencia(r: Resultado) -> float:
    from .scorecard_referencia import calcular_score

    s = r.solicitudes
    s = s[(s.decision == "Aprobada") & s.producto_codigo.isin(["TC", "CONS"]) & (s.fecha_ingreso < "2025-11-01")].copy()
    s["score"] = calcular_score(s)
    b = base_saldos(r).merge(r.prestamos[["prestamo_id", "solicitud_id"]])
    b["mob"] = pd.PeriodIndex(b.periodo, freq="M").asi8 - pd.PeriodIndex(b.fecha_desembolso, freq="M").asi8
    malo = b[(b.mob <= 12) & (b.dias_atraso > 60)].solicitud_id.unique()
    s["malo"] = s.solicitud_id.isin(malo)
    orden = s.sort_values("score")
    # AUC por rangos (Mann-Whitney); Gini = 2·AUC − 1, con el score orientado a "bueno".
    rangos = orden.score.rank()
    n1 = orden.malo.sum()
    n0 = len(orden) - n1
    auc_malo_bajo = 1 - (rangos[orden.malo].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    g = 2 * auc_malo_bajo - 1
    return round(float(g), 3) if not isnan(g) else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--escala", type=float, default=0.2)
    args = ap.parse_args()
    p = configuracion.cargar(escala=args.escala)
    t0 = time.time()
    r = generar(p)
    print(f"Generado en {time.time() - t0:.1f} s · escala {p.escala}")
    corte = str(pd.Period(p.fecha_corte, freq="M"))
    mez = mezcla_al_corte(r, corte)
    print("\nSaldo al corte (Q M, reescalado a escala 1):")
    print((mez / 1e6 / p.escala).round(1).to_string(), "\nTOTAL", round(mez.sum() / 1e6 / p.escala, 1))
    print("\nMezcla al corte vs objetivo:")
    obj = pd.Series({k: v["participacion_objetivo"] for k, v in p.productos.items()})
    print(pd.DataFrame({"real": (mez / mez.sum()).round(3), "objetivo": obj}).to_string())
    m = mora_por_periodo(r)
    print("\nMora 30+ por periodo (% saldo):")
    print((m * 100).round(2).iloc[::3].to_string())
    print(
        "\nCrecimiento de cartera oct-2026 vs oct-2025:", round(mez.sum() / mezcla_al_corte(r, "2025-10").sum() - 1, 3)
    )
    for prod in ("TC", "CONS", "HIPO"):
        print(f"\nCosechas {prod} · mora 30+ a 4 MOB:")
        print((cosechas(r, prod, 4) * 100).round(2).to_string())
    print("\nO3 · mora 30+ a 6 MOB por año de desembolso (TC+CONS tratados; HIPO control):")
    for grupo in (["TC", "CONS"], ["HIPO"]):
        print(" ", "+".join(grupo), cosechas_agrupadas(r, grupo, 6))
    s = r.solicitudes
    s["anio"] = s.fecha_ingreso.dt.year
    print("\nTasa de aprobación por año y producto:")
    print(s.assign(ap=s.decision.eq("Aprobada")).groupby(["anio", "producto_codigo"]).ap.mean().unstack().round(3))
    print("\nGini del score de referencia (malo = 60+ en 12 meses, TC y CONS desembolsados 2025):", gini_referencia(r))
    print(
        "\nFilas: solicitudes",
        len(r.solicitudes),
        "· préstamos",
        len(r.prestamos),
        "· saldos",
        len(r.saldos),
        "· pagos",
        len(r.pagos),
        "· clientes",
        len(r.clientes),
    )


if __name__ == "__main__":
    main()
