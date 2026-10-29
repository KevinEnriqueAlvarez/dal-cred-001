"""Escritura de la zona Landing: un CSV por fuente y periodo, más el manifiesto.

Estructura que produce (igual a lo que entregarían los sistemas de un banco):

    <salida>/landing/
        catalogos/                 productos, agencias, canales, analistas, políticas
        clientes/                  clientes y grupos económicos (foto al corte)
        originacion/solicitudes/   solicitudes_AAAAMM.csv
        core_bancario/prestamos/   prestamos_AAAAMMDD.csv (maestro al corte)
        core_bancario/saldos/      saldos_AAAAMM.csv (extracto de cierre de mes)
        core_bancario/pagos/       pagos_AAAAMM.csv
        core_bancario/garantias/   garantias_AAAAMMDD.csv
        core_bancario/castigos/    castigos_AAAAMMDD.csv
        contabilidad/mayor/        mayor_AAAAMM.csv
        _manifest.json             filas, hash SHA-256 y hora de llegada por archivo
    <salida>/_control/             respuestas para las pruebas (el pipeline no lo lee)

El hash SHA-256 de cada archivo permite demostrar que Bronze cargó exactamente
lo que llegó (control de integridad de la ingesta).
"""

from __future__ import annotations

import hashlib
import json
import zlib
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from .configuracion import Parametros

SLA_LLEGADA = time(6, 0)  # hora límite de llegada de los archivos (D+1)


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _sin_internas(df: pd.DataFrame) -> pd.DataFrame:
    """Quita columnas internas (las que empiezan con "_", como el riesgo latente)."""
    return df[[c for c in df.columns if not c.startswith("_")]]


class Escritor:
    def __init__(self, p: Parametros, salida: Path):
        self.p = p
        self.base = Path(salida) / "landing"
        self.control = Path(salida) / "_control"
        self.archivos: list[dict] = []

    def escribir(
        self, df: pd.DataFrame, relativa: str, periodo: str | None = None, llegada: datetime | None = None
    ) -> None:
        ruta = self.base / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        _sin_internas(df).to_csv(ruta, index=False, encoding="utf-8")
        self.archivos.append(
            {
                "archivo": relativa,
                "periodo": periodo,
                "filas": int(len(df)),
                "sha256": sha256(ruta),
                "fecha_llegada": (llegada or self._llegada_normal(periodo)).isoformat(timespec="minutes"),
            }
        )

    def _llegada_normal(self, periodo: str | None) -> datetime:
        """Llegada estándar: día hábil siguiente al cierre, entre 01:00 y 03:30."""
        if periodo is None:
            fin = pd.Timestamp(self.p.fecha_corte)
        else:
            fin = pd.Period(periodo, freq="M").end_time.normalize()
        minutos = 60 + zlib.crc32((periodo or "").encode()) % 150
        return (fin + timedelta(days=1)).to_pydatetime().replace(hour=0, minute=0) + timedelta(minutes=minutos)

    def manifiesto(self) -> None:
        contenido = {
            "proyecto": self.p.crudo["proyecto"],
            "banco_ficticio": self.p.crudo["banco_ficticio"],
            "generado_por": "data_generator",
            "semilla": self.p.semilla,
            "escala": self.p.escala,
            "fecha_corte": self.p.fecha_corte.isoformat(),
            "sla_llegada": SLA_LLEGADA.isoformat(timespec="minutes"),
            "archivos": self.archivos,
        }
        (self.base / "_manifest.json").write_text(json.dumps(contenido, indent=2, ensure_ascii=False), encoding="utf-8")

    def escribir_control(self, nombre: str, contenido: dict) -> None:
        self.control.mkdir(parents=True, exist_ok=True)
        (self.control / nombre).write_text(
            json.dumps(contenido, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )


def escribir_todo(
    p: Parametros, salida: Path, tablas: dict[str, pd.DataFrame], catalogos: dict[str, pd.DataFrame], errores: dict
) -> Escritor:
    w = Escritor(p, salida)
    corte = p.fecha_corte.strftime("%Y%m%d")

    for nombre, df in catalogos.items():
        w.escribir(df, f"catalogos/{nombre}.csv")
    w.escribir(tablas["clientes"], f"clientes/clientes_{corte}.csv")
    w.escribir(tablas["grupos"], f"clientes/grupos_economicos_{corte}.csv")
    w.escribir(tablas["prestamos"], f"core_bancario/prestamos/prestamos_{corte}.csv")
    w.escribir(tablas["garantias"], f"core_bancario/garantias/garantias_{corte}.csv")
    w.escribir(tablas["castigos"], f"core_bancario/castigos/castigos_{corte}.csv")

    tardio = errores["archivo_tardio"]
    sol = tablas["solicitudes"]
    sol_mes = sol.fecha_ingreso.astype("datetime64[ns]").dt.to_period("M").astype(str)
    pagos = tablas["pagos"]
    pagos_mes = pagos.fecha_pago.astype("string").str[:7]
    for mes in p.meses_publicados:
        m = str(mes)
        aaaamm = m.replace("-", "")
        w.escribir(tablas["saldos"][tablas["saldos"].periodo == m], f"core_bancario/saldos/saldos_{aaaamm}.csv", m)
        # Los pagos con fecha inválida se reportan en el archivo del mes en que se cargaron.
        w.escribir(pagos[pagos_mes == m], f"core_bancario/pagos/pagos_{aaaamm}.csv", m)
        w.escribir(tablas["mayor"][tablas["mayor"].periodo == m], f"contabilidad/mayor/mayor_{aaaamm}.csv", m)
        llegada = None
        if tardio["fuente"] == "solicitudes" and tardio["periodo"] == m:
            h, mi = map(int, tardio["hora_llegada"].split(":"))
            llegada = (mes.end_time.normalize() + timedelta(days=1)).to_pydatetime().replace(hour=h, minute=mi)
        w.escribir(sol[sol_mes == m], f"originacion/solicitudes/solicitudes_{aaaamm}.csv", m, llegada)

    # Pagos con fecha inválida no caen en ningún mes por su fecha: van al archivo del corte.
    invalidos = pagos[~pagos_mes.isin([str(x) for x in p.meses_publicados])]
    if len(invalidos):
        ultimo = str(p.meses_publicados[-1]).replace("-", "")
        ruta = w.base / f"core_bancario/pagos/pagos_{ultimo}.csv"
        invalidos.pipe(_sin_internas).to_csv(ruta, mode="a", header=False, index=False, encoding="utf-8")
        registro = next(a for a in w.archivos if a["archivo"].endswith(f"pagos_{ultimo}.csv"))
        registro["filas"] += len(invalidos)
        registro["sha256"] = sha256(ruta)
    w.manifiesto()
    return w
