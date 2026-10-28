"""Punto de entrada: genera todos los archivos de Landing.

Ejemplos:
    python -m data_generator                      # banco completo en ./data
    python -m data_generator --escala 0.05        # versión pequeña para pruebas
    python -m data_generator --salida /ruta --config otra_config.yaml
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__, calibracion, configuracion, errores
from .escritura import escribir_todo
from .generador import generar


def resumen_calibracion(r, p) -> dict:
    corte = str(pd.Period(p.fecha_corte, freq="M"))
    mez = calibracion.mezcla_al_corte(r, corte)
    mora = calibracion.mora_por_periodo(r)
    return {
        "cartera_al_corte_gtq": round(float(mez.sum()), 2),
        "mezcla_al_corte": {k: round(float(v / mez.sum()), 4) for k, v in mez.items()},
        "crecimiento_anual": round(float(mez.sum() / calibracion.mezcla_al_corte(r, "2025-10").sum() - 1), 4),
        "mora_30_total": {k: round(float(v), 4) for k, v in mora["TOTAL"].items()},
        "mora_30_a_6_mob_tc_cons": calibracion.cosechas_agrupadas(r, ["TC", "CONS"], 6),
        "mora_30_a_6_mob_hipo_control": calibracion.cosechas_agrupadas(r, ["HIPO"], 6),
        "gini_score_referencia_2025": calibracion.gini_referencia(r),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Generador de datos sintéticos DAL-CRED-001")
    ap.add_argument("--salida", default="data", help="carpeta de salida (por defecto ./data)")
    ap.add_argument("--escala", type=float, default=None, help="multiplica los volúmenes (1.0 = completo)")
    ap.add_argument("--config", default=None, help="ruta a un YAML de parámetros alternativo")
    ap.add_argument("--sin-calibracion", action="store_true", help="omite el resumen de calibración")
    args = ap.parse_args()

    inicio = time.time()
    p = configuracion.cargar(args.config, args.escala)
    print(f"DAL-CRED-001 · generador v{__version__} · semilla {p.semilla} · escala {p.escala}")
    r = generar(p)

    limpias = {
        "clientes": r.clientes,
        "grupos": r.grupos,
        "solicitudes": r.solicitudes,
        "prestamos": r.prestamos,
        "saldos": r.saldos,
        "pagos": r.pagos,
        "garantias": r.garantias,
        "castigos": r.castigos,
        "mayor": r.mayor,
    }
    # Generador de números aleatorios aparte para los errores: cambiar los errores
    # no altera los datos limpios.
    con_errores, registro = errores.inyectar(p, np.random.default_rng(p.semilla + 1), limpias)
    w = escribir_todo(p, Path(args.salida), con_errores, r.catalogos, registro)
    w.escribir_control("errores_inyectados.json", registro)
    if not args.sin_calibracion:
        w.escribir_control("calibracion.json", resumen_calibracion(r, p))

    total = sum(a["filas"] for a in w.archivos)
    print(f"{len(w.archivos)} archivos · {total:,} filas · {time.time() - inicio:.1f} s")
    print(f"Landing en {Path(args.salida) / 'landing'}")


if __name__ == "__main__":
    main()
