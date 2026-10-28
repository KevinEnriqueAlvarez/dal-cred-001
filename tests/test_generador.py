"""Pruebas del generador de datos sintéticos (actividad 3.1).

Corren a escala 0,02 (unos segundos) en cada pull request. Verifican:
reproducibilidad, periodo, integridad referencial, identificadores sintéticos,
el manifiesto con hashes y que los errores inyectados quedan detectables.

Las pruebas marcadas `calibracion` corren a escala 0,3 y verifican los
objetivos de negocio; se ejecutan a mano: pytest -m calibracion
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_generator import calibracion, configuracion
from data_generator.generador import generar
from data_generator.scorecard_referencia import calcular_score

ESCALA_CI = 0.02


@pytest.fixture(scope="session")
def salida(tmp_path_factory) -> Path:
    """Corre el generador completo (CLI) una sola vez para toda la sesión de pruebas."""
    destino = tmp_path_factory.mktemp("datos")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "data_generator",
            "--salida",
            str(destino),
            "--escala",
            str(ESCALA_CI),
            "--sin-calibracion",
        ],
        check=True,
    )
    return destino


def leer(salida: Path, patron: str) -> pd.DataFrame:
    archivos = sorted((salida / "landing").glob(patron))
    assert archivos, f"No se encontraron archivos {patron}"
    return pd.concat([pd.read_csv(a, dtype=str) for a in archivos], ignore_index=True)


def control(salida: Path) -> dict:
    return json.loads((salida / "_control" / "errores_inyectados.json").read_text(encoding="utf-8"))


# ----------------------------------------------------------------- reproducibilidad
def test_misma_semilla_mismos_datos():
    p = configuracion.cargar(escala=0.01)
    a, b = generar(p), generar(p)
    pd.testing.assert_frame_equal(a.saldos, b.saldos)
    pd.testing.assert_frame_equal(a.solicitudes, b.solicitudes)


def test_parametros_invalidos_se_rechazan(tmp_path):
    crudo = configuracion.cargar().crudo
    crudo["periodo"]["fecha_corte"] = "2024-12-31"
    import yaml

    ruta = tmp_path / "malo.yaml"
    ruta.write_text(yaml.safe_dump(crudo), encoding="utf-8")
    with pytest.raises(ValueError, match="Fechas incoherentes"):
        configuracion.cargar(ruta)


# ----------------------------------------------------------------- periodo
def test_saldos_cubren_22_meses_hasta_el_corte(salida):
    saldos = leer(salida, "core_bancario/saldos/*.csv")
    periodos = sorted(saldos.periodo.unique())
    assert periodos[0] == "2025-01" and periodos[-1] == "2026-10"
    assert len(periodos) == 22


def test_ninguna_solicitud_despues_del_corte(salida):
    sol = leer(salida, "originacion/solicitudes/*.csv")
    assert pd.to_datetime(sol.fecha_ingreso).max() <= pd.Timestamp("2026-10-31 23:59")


# ----------------------------------------------------------------- privacidad
def test_no_se_publican_columnas_internas(salida):
    """Las columnas de simulación (riesgo latente, sesgo del analista) empiezan con "_" y no se publican."""
    for archivo in (salida / "landing").rglob("*.csv"):
        encabezado = archivo.read_text(encoding="utf-8").splitlines()[0].split(",")
        internas = [c for c in encabezado if c.startswith("_")]
        assert not internas, f"{archivo.name} expone columnas internas: {internas}"


def test_dpi_validos_son_sinteticos(salida):
    cl = leer(salida, "clientes/clientes_*.csv")
    dpi = cl.dpi.dropna()
    validos = dpi[dpi.str.fullmatch(r"\d{13}")]
    # Todo DPI con formato válido termina en 9999 (departamento/municipio inexistente).
    assert validos.str.endswith("9999").all()


# ----------------------------------------------------------------- integridad
def test_integridad_referencial(salida):
    pr = leer(salida, "core_bancario/prestamos/*.csv")
    cl = leer(salida, "clientes/clientes_*.csv")
    pagos = leer(salida, "core_bancario/pagos/*.csv")
    saldos = leer(salida, "core_bancario/saldos/*.csv")
    assert pr.cliente_id.isin(cl.cliente_id).all()
    assert pagos.prestamo_id.isin(pr.prestamo_id).all()
    assert saldos.prestamo_id.isin(pr.prestamo_id).all()


def test_mayor_concilia_con_saldos_limpios(salida):
    saldos = leer(salida, "core_bancario/saldos/*.csv")
    mayor = leer(salida, "contabilidad/mayor/*.csv")
    neg = control(salida)["saldos_negativos"]["cantidad"]
    total_saldos = saldos.saldo_capital.astype(float).abs().sum()
    total_mayor = mayor.saldo_contable.astype(float).sum()
    # Los saldos negativos inyectados son copias con signo cambiado: en valor absoluto cuadran.
    assert neg > 0
    assert abs(total_saldos / total_mayor - 1) < 0.0001


# ----------------------------------------------------------------- manifiesto
def test_manifiesto_hash_y_filas(salida):
    manifiesto = json.loads((salida / "landing" / "_manifest.json").read_text(encoding="utf-8"))
    assert manifiesto["fecha_corte"] == "2026-10-31"
    for a in manifiesto["archivos"]:
        ruta = salida / "landing" / a["archivo"]
        assert hashlib.sha256(ruta.read_bytes()).hexdigest() == a["sha256"], a["archivo"]
        assert len(pd.read_csv(ruta)) == a["filas"], a["archivo"]


def test_archivo_tardio_registrado(salida):
    manifiesto = json.loads((salida / "landing" / "_manifest.json").read_text(encoding="utf-8"))
    tardio = [a for a in manifiesto["archivos"] if a["archivo"].endswith("solicitudes_202610.csv")][0]
    assert tardio["fecha_llegada"].endswith("06:42")
    assert tardio["fecha_llegada"][11:] > manifiesto["sla_llegada"]


# ----------------------------------------------------------------- errores inyectados
def test_errores_inyectados_son_detectables(salida):
    c = control(salida)
    pagos = leer(salida, "core_bancario/pagos/*.csv")
    saldos = leer(salida, "core_bancario/saldos/*.csv")
    cl = leer(salida, "clientes/clientes_*.csv")
    pr = leer(salida, "core_bancario/prestamos/*.csv")
    sol = leer(salida, "originacion/solicitudes/*.csv")

    # Unicidad: el exceso de filas por pago_id es exactamente lo inyectado.
    assert len(pagos) - pagos.pago_id.nunique() == c["pagos_duplicados"]["cantidad"]
    # Validez: fechas que no son una fecha real dentro del periodo.
    fechas = pd.to_datetime(pagos.fecha_pago, errors="coerce")
    fuera = fechas.isna() | (fechas < "2025-01-01") | (fechas > "2026-10-31")
    assert set(pagos.loc[fuera, "pago_id"]) == set(c["pagos_fecha_invalida"]["ids"])
    # Validez: saldos negativos.
    assert (saldos.saldo_capital.astype(float) < 0).sum() == c["saldos_negativos"]["cantidad"]
    # Completitud y validez del DPI.
    ind = cl[cl.tipo_persona == "Individual"]
    assert set(ind.loc[ind.dpi.isna(), "cliente_id"]) == set(c["clientes_dpi_faltante"]["ids"])
    malos = ind.dpi.notna() & ~ind.dpi.fillna("").str.fullmatch(r"\d{13}")
    assert set(ind.loc[malos, "cliente_id"]) == set(c["clientes_dpi_formato_invalido"]["ids"])
    # Unicidad del cliente: DPI repetido con dos códigos.
    repetidos = ind.dpi.dropna()
    assert repetidos.duplicated().sum() == c["clientes_duplicados"]["cantidad"]
    # Control OB-05: desembolsos ligados a solicitudes rechazadas.
    unido = pr.dropna(subset=["solicitud_id"]).merge(sol[["solicitud_id", "decision"]], on="solicitud_id")
    violaciones = unido[unido.decision != "Aprobada"].prestamo_id
    assert set(violaciones) == set(c["desembolsos_sin_solicitud_aprobada"]["ids"])


# ----------------------------------------------------------------- scorecard
def test_scorecard_premia_menor_riesgo():
    base = pd.DataFrame(
        {
            "atraso_max_sirc_12m": [0, 120],
            "entidades_con_deuda_sirc": [1, 7],
            "endeudamiento_sirc_meses_ingreso": [1.5, 9.0],
            "relacion_cuota_ingreso": [0.1, 0.5],
            "antiguedad_laboral_meses": [150, 6],
        }
    )
    bueno, malo = calcular_score(base)
    assert bueno > 600 > malo


def test_politica_p07_baja_el_corte_de_tarjeta(salida):
    sol = leer(salida, "originacion/solicitudes/*.csv")
    tc = sol[sol.producto_codigo == "TC"].assign(fecha=lambda d: pd.to_datetime(d.fecha_ingreso))
    antes = tc[tc.fecha < "2026-04-15"].corte_politica.astype(int).unique()
    despues = tc[tc.fecha >= "2026-04-15"].corte_politica.astype(int).unique()
    assert set(antes) == {600} and set(despues) == {560}


def test_scorecard_solo_desde_el_go_live(salida):
    sol = leer(salida, "originacion/solicitudes/*.csv")
    con_score = sol[sol.metodo_decision == "Scorecard SC-CONS v1.0"]
    assert pd.to_datetime(con_score.fecha_ingreso).min() >= pd.Timestamp("2026-01-01")
    assert set(con_score.producto_codigo) <= {"TC", "CONS"}


# ----------------------------------------------------------------- calibración (lenta)
@pytest.mark.calibracion
def test_objetivos_de_calibracion():
    p = configuracion.cargar(escala=0.3)
    r = generar(p)
    mez = calibracion.mezcla_al_corte(r, "2026-10")
    participacion = mez / mez.sum()
    objetivo = pd.Series({k: v["participacion_objetivo"] for k, v in p.productos.items()})
    assert (participacion - objetivo).abs().max() < 0.06
    mora = calibracion.mora_por_periodo(r)["TOTAL"]
    assert 0.030 < mora[["2025-01", "2025-02", "2025-03"]].mean() < 0.045
    assert mora["2026-10"] < mora["2025-10"]
    o3 = calibracion.cosechas_agrupadas(r, ["TC", "CONS"], 6)
    assert o3[2026] < o3[2025]
    assert calibracion.gini_referencia(r) > 0.35
    assert np.isfinite(mez.sum())
