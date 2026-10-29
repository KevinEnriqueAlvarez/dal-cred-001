"""Pruebas de la ingesta Landing -> Bronze (actividad 3.2).

Cada prueba corre sobre DuckDB siempre, y sobre SQL Server cuando existe la
variable DAL_SQLSERVER_CONN (en CI, un contenedor de SQL Server 2022).

Cubren los controles de la ingesta: integridad (hash), completitud (filas),
declaración en el manifiesto, idempotencia, reemplazo de versiones corregidas,
deriva de esquema, oportunidad (SLA), copia fiel y auditoría.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ingesta.cargador import Cargador, sha256
from ingesta.fuentes import FUENTES
from ingesta.motores import Motor, MotorDuckDB, abrir

MOTORES = ["duckdb"] + (["sqlserver"] if os.environ.get("DAL_SQLSERVER_CONN") else [])


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def landing_base(tmp_path_factory) -> Path:
    """Landing generado una sola vez a escala 0,02."""
    destino = tmp_path_factory.mktemp("gen")
    subprocess.run(
        [sys.executable, "-m", "data_generator", "--salida", str(destino), "--escala", "0.02", "--sin-calibracion"],
        check=True,
    )
    return destino / "landing"


@pytest.fixture
def landing(landing_base, tmp_path) -> Path:
    """Copia propia del Landing para que cada prueba pueda alterarlo."""
    copia = tmp_path / "landing"
    shutil.copytree(landing_base, copia)
    return copia


def _limpiar_sqlserver(motor: Motor) -> None:
    for esquema in ("bronze", "audit"):
        for (tabla,) in motor.consultar(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ?", (esquema,)
        ):
            motor.ejecutar(f"DROP TABLE {esquema}.[{tabla}]")
    motor.confirmar()


@pytest.fixture(params=MOTORES)
def nuevo_motor(request, tmp_path):
    """Fábrica de conexiones a una base vacía del motor indicado."""
    abiertos: list[Motor] = []
    ruta = str(tmp_path / "prueba.duckdb")

    def fabrica() -> Motor:
        m = abrir(request.param, destino=ruta)
        if request.param == "sqlserver" and not abiertos:
            _limpiar_sqlserver(m)
        abiertos.append(m)
        return m

    yield fabrica
    for m in abiertos:
        try:
            m.cerrar()
        except Exception:
            pass


def manifiesto(landing: Path) -> dict:
    return json.loads((landing / "_manifest.json").read_text(encoding="utf-8"))


def guardar_manifiesto(landing: Path, contenido: dict) -> None:
    (landing / "_manifest.json").write_text(json.dumps(contenido, indent=2, ensure_ascii=False), encoding="utf-8")


def contar(motor: Motor, tabla: str, donde: str = "", parametros: tuple = ()) -> int:
    return motor.consultar(f"SELECT COUNT(*) FROM bronze.{motor.q(tabla)} {donde}", parametros)[0][0]


def estados(motor: Motor, run_id: str) -> dict[str, str]:
    filas = motor.consultar("SELECT archivo, estado FROM audit.ingesta_archivo WHERE run_id = ?", (run_id,))
    return dict(filas)


# ----------------------------------------------------------------------------- pruebas
def test_carga_completa_y_auditoria(landing, nuevo_motor):
    motor = nuevo_motor()
    r = Cargador(motor, landing).ejecutar()
    m = manifiesto(landing)

    assert r.estado == "exitosa"
    assert r.conteo("cargado") == len(m["archivos"])
    # Completitud: cada archivo dejó en Bronze exactamente las filas declaradas.
    for a in m["archivos"]:
        tabla = r.archivos[[x["archivo"] for x in r.archivos].index(a["archivo"])]["tabla_destino"]
        assert contar(motor, tabla, "WHERE meta_archivo = ?", (a["archivo"],)) == a["filas"], a["archivo"]
    # Metadatos de linaje completos.
    nulos = motor.consultar(
        "SELECT COUNT(*) FROM bronze.saldos WHERE meta_sha256 IS NULL OR meta_run_id IS NULL "
        "OR meta_fila IS NULL OR meta_fecha_llegada IS NULL OR meta_cargado_en IS NULL"
    )[0][0]
    assert nulos == 0
    log = motor.consultar("SELECT estado, archivos_cargados, filas_salida, git_sha FROM audit.run_log")
    assert log == [("exitosa", len(m["archivos"]), sum(a["filas"] for a in m["archivos"]), log[0][3])]
    assert log[0][3]


def test_todas_las_fuentes_tienen_destino(landing):
    from ingesta.fuentes import tabla_destino

    for a in manifiesto(landing)["archivos"]:
        assert tabla_destino(a["archivo"]) in FUENTES.values(), a["archivo"]


def test_segunda_corrida_es_idempotente(landing, nuevo_motor):
    Cargador(nuevo_motor(), landing).ejecutar()
    motor = nuevo_motor()
    antes = contar(motor, "saldos")
    r = Cargador(motor, landing).ejecutar()
    assert r.estado == "exitosa"
    assert r.conteo("omitido_sin_cambios") == len(r.archivos)
    assert contar(motor, "saldos") == antes


def test_archivo_alterado_se_rechaza(landing, nuevo_motor):
    ruta = landing / "core_bancario/saldos/saldos_202503.csv"
    texto = ruta.read_text(encoding="utf-8")
    ruta.write_text(texto.replace(",0,", ",1,", 1), encoding="utf-8")  # un solo carácter cambia
    motor = nuevo_motor()
    r = Cargador(motor, landing).ejecutar()

    assert r.estado == "con_rechazos"
    assert estados(motor, r.run_id)["core_bancario/saldos/saldos_202503.csv"] == "rechazado_hash"
    assert contar(motor, "saldos", "WHERE meta_archivo = ?", ("core_bancario/saldos/saldos_202503.csv",)) == 0
    # El resto sí se cargó: un archivo dañado no detiene a los demás.
    assert r.conteo("cargado") == len(r.archivos) - 1


def test_cli_devuelve_1_con_rechazos(landing, tmp_path):
    (landing / "catalogos/canales.csv").write_text("canal_codigo\nXX\n", encoding="utf-8")
    proceso = subprocess.run(
        [sys.executable, "-m", "ingesta", "--landing", str(landing), "--destino", str(tmp_path / "c.duckdb")],
        capture_output=True,
        text=True,
    )
    assert proceso.returncode == 1
    assert "rechazado_hash" in proceso.stderr


def test_version_corregida_reemplaza_sin_duplicar(landing, nuevo_motor):
    Cargador(nuevo_motor(), landing).ejecutar()
    archivo = "contabilidad/mayor/mayor_202510.csv"
    ruta = landing / archivo
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    ruta.write_text("\n".join(lineas[:-1]) + "\n", encoding="utf-8")  # versión corregida: una fila menos
    m = manifiesto(landing)
    entrada = next(a for a in m["archivos"] if a["archivo"] == archivo)
    entrada["sha256"], entrada["filas"] = sha256(ruta), len(lineas) - 2
    guardar_manifiesto(landing, m)

    motor = nuevo_motor()
    r = Cargador(motor, landing).ejecutar()
    assert estados(motor, r.run_id)[archivo] == "reemplazado"
    assert contar(motor, "mayor_contable", "WHERE meta_archivo = ?", (archivo,)) == len(lineas) - 2


def test_archivo_no_declarado_se_rechaza(landing, nuevo_motor):
    (landing / "core_bancario/saldos/saldos_extra.csv").write_text("periodo\n2026-10\n", encoding="utf-8")
    motor = nuevo_motor()
    r = Cargador(motor, landing).ejecutar()
    assert estados(motor, r.run_id)["core_bancario/saldos/saldos_extra.csv"] == "rechazado_no_declarado"
    assert contar(motor, "saldos", "WHERE meta_archivo = ?", ("core_bancario/saldos/saldos_extra.csv",)) == 0


def test_filas_distintas_al_manifiesto_se_rechaza(landing, nuevo_motor):
    m = manifiesto(landing)
    entrada = next(a for a in m["archivos"] if a["archivo"] == "catalogos/agencias.csv")
    entrada["filas"] += 5
    guardar_manifiesto(landing, m)
    motor = nuevo_motor()
    r = Cargador(motor, landing).ejecutar()
    assert estados(motor, r.run_id)["catalogos/agencias.csv"] == "rechazado_filas"


def test_columna_nueva_se_agrega_y_se_registra(landing, nuevo_motor):
    Cargador(nuevo_motor(), landing).ejecutar()
    archivo = "catalogos/canales.csv"
    ruta = landing / archivo
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    nuevo = [lineas[0] + ",activo"] + [linea + ",S" for linea in lineas[1:]]
    ruta.write_text("\n".join(nuevo) + "\n", encoding="utf-8")
    m = manifiesto(landing)
    next(a for a in m["archivos"] if a["archivo"] == archivo)["sha256"] = sha256(ruta)
    guardar_manifiesto(landing, m)

    motor = nuevo_motor()
    r = Cargador(motor, landing).ejecutar()
    fila = next(a for a in r.archivos if a["archivo"] == archivo)
    assert fila["columnas_nuevas"] == "activo"
    assert "activo" in motor.columnas("bronze", "cat_canales")
    assert contar(motor, "cat_canales", "WHERE activo = 'S'") == len(lineas) - 1


def test_llegada_tardia_se_marca_sin_rechazar(landing, nuevo_motor):
    motor = nuevo_motor()
    r = Cargador(motor, landing).ejecutar()
    tardio = next(a for a in r.archivos if a["archivo"].endswith("solicitudes_202610.csv"))
    assert tardio["estado"] == "cargado"
    assert tardio["sla_cumplido"] is False
    a_tiempo = [a for a in r.archivos if a["sla_cumplido"] is True]
    assert len(a_tiempo) == len(r.archivos) - 1


def test_copia_fiel_conserva_valores_invalidos(landing, nuevo_motor):
    """Bronze no limpia: la fecha imposible 2026-02-30 debe llegar intacta (Silver la detecta)."""
    motor = nuevo_motor()
    Cargador(motor, landing).ejecutar()
    assert contar(motor, "pagos", "WHERE fecha_pago = '2026-02-30'") > 0
    negativos = motor.consultar("SELECT COUNT(*) FROM bronze.saldos WHERE saldo_capital LIKE '-%'")[0][0]
    assert negativos > 0


def test_duckdb_por_defecto():
    assert isinstance(abrir("duckdb", destino=":memory:"), MotorDuckDB)
