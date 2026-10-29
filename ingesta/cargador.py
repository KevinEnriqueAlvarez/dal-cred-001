"""Orquestación de la carga Landing -> Bronze.

Por cada archivo del manifiesto, en este orden:

1. ¿Existe en disco?                         no -> rechazado_faltante
2. ¿Su SHA-256 coincide con el manifiesto?   no -> rechazado_hash
3. ¿Ya se cargó con ese mismo hash?          sí -> omitido_sin_cambios (idempotencia)
4. ¿Las filas leídas = filas declaradas?     no -> rechazado_filas
5. Carga en una transacción: borra las filas previas de ese archivo (si llegó una
   versión corregida), inserta las nuevas con sus metadatos y registra el
   resultado en audit.ingesta_archivo -> cargado o reemplazado.

Además, todo archivo en Landing que no esté en el manifiesto se rechaza
(rechazado_no_declarado): nada entra a Bronze sin estar declarado.

La llegada fuera del SLA no rechaza el archivo (los datos son correctos, solo
llegaron tarde): se marca sla_cumplido = falso y lo muestra el monitor de cierre.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

import pandas as pd

from .fuentes import tabla_destino
from .motores import Motor, ahora

ESTADOS_RECHAZO = {"rechazado_faltante", "rechazado_hash", "rechazado_filas", "rechazado_no_declarado"}


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def git_sha() -> str:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=Path(__file__).parent
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"


def leer_csv(ruta: Path) -> pd.DataFrame:
    """Lee el archivo como texto, sin interpretar tipos: copia fiel de lo que llegó.

    Solo la celda vacía se vuelve nulo; textos como "NaN" o "None" se conservan.
    """
    return pd.read_csv(ruta, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8")


@dataclass
class ResultadoCorrida:
    run_id: str
    estado: str
    archivos: list[dict] = field(default_factory=list)

    def conteo(self, *estados: str) -> int:
        return sum(1 for a in self.archivos if a["estado"] in estados)


class Cargador:
    def __init__(self, motor: Motor, landing: Path):
        self.motor = motor
        self.landing = Path(landing)
        manifiesto_ruta = self.landing / "_manifest.json"
        self.manifiesto_texto = manifiesto_ruta.read_bytes()
        self.manifiesto = json.loads(self.manifiesto_texto)
        h, m = map(int, self.manifiesto["sla_llegada"].split(":"))
        self.sla = time(h, m)
        self.run_id = str(uuid.uuid4())

    # ------------------------------------------------------------------ archivos
    def _registro(self, entrada: dict, estado: str, **extra) -> dict:
        llegada = datetime.fromisoformat(entrada["fecha_llegada"]) if entrada.get("fecha_llegada") else None
        fila = {
            "run_id": self.run_id,
            "archivo": entrada["archivo"],
            "tabla_destino": tabla_destino(entrada["archivo"]),
            "sha256_manifiesto": entrada.get("sha256"),
            "sha256_calculado": extra.get("sha256_calculado"),
            "filas_manifiesto": entrada.get("filas"),
            "filas_cargadas": extra.get("filas_cargadas", 0),
            "fecha_llegada": llegada,
            "sla_cumplido": None if llegada is None else llegada.time() <= self.sla,
            "estado": estado,
            "columnas_nuevas": extra.get("columnas_nuevas"),
            "registrado_en": ahora(),
        }
        self.motor.registrar("ingesta_archivo", fila)
        return fila

    def _procesar(self, entrada: dict) -> dict:
        ruta = self.landing / entrada["archivo"]
        tabla = tabla_destino(entrada["archivo"])
        if tabla is None:
            return self._registro(entrada, "rechazado_no_declarado")
        if not ruta.exists():
            return self._registro(entrada, "rechazado_faltante")

        calculado = sha256(ruta)
        if calculado != entrada["sha256"]:
            return self._registro(entrada, "rechazado_hash", sha256_calculado=calculado)

        previo = self.motor.ultima_carga(entrada["archivo"])
        if previo == calculado:
            return self._registro(entrada, "omitido_sin_cambios", sha256_calculado=calculado)

        df = leer_csv(ruta)
        if len(df) != entrada["filas"]:
            return self._registro(entrada, "rechazado_filas", sha256_calculado=calculado, filas_cargadas=len(df))

        try:
            nuevas = self.motor.asegurar_tabla_bronze(tabla, list(df.columns))
            if previo is not None:
                self.motor.borrar_archivo(tabla, entrada["archivo"])
            df["meta_archivo"] = entrada["archivo"]
            df["meta_sha256"] = calculado
            df["meta_fila"] = range(1, len(df) + 1)
            df["meta_fecha_llegada"] = datetime.fromisoformat(entrada["fecha_llegada"])
            df["meta_run_id"] = self.run_id
            df["meta_cargado_en"] = ahora()
            self.motor.insertar_lote("bronze", tabla, df)
            fila = self._registro(
                entrada,
                "reemplazado" if previo is not None else "cargado",
                sha256_calculado=calculado,
                filas_cargadas=len(df),
                columnas_nuevas=", ".join(nuevas) or None,
            )
            self.motor.confirmar()  # el archivo y su registro de auditoría entran juntos o no entran
            return fila
        except Exception:
            self.motor.revertir()
            raise

    # ------------------------------------------------------------------ corrida
    def ejecutar(self) -> ResultadoCorrida:
        inicio = ahora()
        self.motor.crear_esquemas()
        resultado = ResultadoCorrida(self.run_id, "en_curso")
        declarados = {a["archivo"] for a in self.manifiesto["archivos"]}
        error = None
        try:
            for entrada in self.manifiesto["archivos"]:
                resultado.archivos.append(self._procesar(entrada))
                self.motor.confirmar()
            # Archivos presentes en Landing pero ausentes del manifiesto.
            for ruta in sorted(self.landing.rglob("*.csv")):
                relativa = ruta.relative_to(self.landing).as_posix()
                if relativa not in declarados:
                    resultado.archivos.append(
                        self._registro({"archivo": relativa}, "rechazado_no_declarado", sha256_calculado=sha256(ruta))
                    )
                    self.motor.confirmar()
        except Exception as exc:  # se registra la falla y se vuelve a lanzar
            error = exc

        rechazados = resultado.conteo(*ESTADOS_RECHAZO)
        resultado.estado = "fallida" if error else ("con_rechazos" if rechazados else "exitosa")
        cargados = [a for a in resultado.archivos if a["estado"] in ("cargado", "reemplazado")]
        huella = "\n".join(f"{a['archivo']}|{a['sha256_calculado']}|{a['filas_cargadas']}" for a in cargados)
        self.motor.registrar(
            "run_log",
            {
                "run_id": self.run_id,
                "proceso": "ingesta_bronze",
                "tarea": "landing_a_bronze",
                "motor": self.motor.nombre,
                "git_sha": git_sha(),
                "inicio": inicio,
                "fin": ahora(),
                "estado": resultado.estado,
                "archivos_declarados": len(declarados),
                "archivos_cargados": len(cargados),
                "archivos_omitidos": resultado.conteo("omitido_sin_cambios"),
                "archivos_rechazados": rechazados,
                "filas_entrada": sum(a["filas_manifiesto"] or 0 for a in resultado.archivos),
                "filas_salida": sum(a["filas_cargadas"] for a in cargados),
                "hash_entrada": hashlib.sha256(self.manifiesto_texto).hexdigest(),
                "hash_salida": hashlib.sha256(huella.encode()).hexdigest() if cargados else None,
                "ejecutado_por": os.environ.get("GITHUB_ACTOR") or getpass.getuser(),
                "detalle": repr(error)[:4000] if error else None,
            },
        )
        self.motor.confirmar()
        if error:
            raise error
        return resultado
