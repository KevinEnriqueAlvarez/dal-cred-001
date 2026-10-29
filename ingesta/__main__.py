"""Punto de entrada de la ingesta Landing -> Bronze.

Ejemplos:
    python -m ingesta --landing data/landing                      # DuckDB en data/dal_cred_001.duckdb
    python -m ingesta --landing data/landing --motor sqlserver    # SQL Server con DAL_SQLSERVER_CONN

Código de salida: 0 si la corrida es exitosa; 1 si algún archivo fue rechazado
(el orquestador detiene las capas siguientes); 2 si la corrida falló.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from . import __version__
from .cargador import Cargador
from .motores import abrir


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingesta Landing -> Bronze · DAL-CRED-001")
    ap.add_argument("--landing", default="data/landing", help="carpeta landing con _manifest.json")
    ap.add_argument("--motor", choices=["duckdb", "sqlserver"], default="duckdb")
    ap.add_argument("--destino", default="data/dal_cred_001.duckdb", help="archivo DuckDB (solo motor duckdb)")
    ap.add_argument("--conexion", default=None, help="cadena ODBC (solo sqlserver; por defecto DAL_SQLSERVER_CONN)")
    args = ap.parse_args()

    t0 = time.time()
    motor = abrir(args.motor, args.destino, args.conexion)
    print(f"DAL-CRED-001 · ingesta v{__version__} · motor {motor.nombre}")
    try:
        resultado = Cargador(motor, Path(args.landing)).ejecutar()
    except Exception as exc:
        print(f"Corrida FALLIDA: {exc!r}", file=sys.stderr)
        motor.cerrar()
        return 2
    motor.cerrar()

    estados = Counter(a["estado"] for a in resultado.archivos)
    filas = sum(a["filas_cargadas"] for a in resultado.archivos if a["estado"] in ("cargado", "reemplazado"))
    print(f"run_id {resultado.run_id} · estado {resultado.estado} · {time.time() - t0:.1f} s")
    for estado, n in sorted(estados.items()):
        print(f"  {estado:24s} {n:>4}")
    print(f"  filas cargadas a Bronze  {filas:>12,}")
    tarde = [
        a["archivo"] for a in resultado.archivos if a["sla_cumplido"] is False and a["estado"] != "omitido_sin_cambios"
    ]
    if tarde:
        print(f"  llegaron fuera del SLA: {', '.join(tarde)}")
    for a in resultado.archivos:
        if a["estado"].startswith("rechazado"):
            print(f"  RECHAZADO {a['estado']}: {a['archivo']}", file=sys.stderr)
    return 0 if resultado.estado == "exitosa" else 1


if __name__ == "__main__":
    sys.exit(main())
