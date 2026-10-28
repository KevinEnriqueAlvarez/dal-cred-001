"""Catálogos de referencia: productos, agencias, canales, analistas y políticas.

Los departamentos de Guatemala son reales (son geografía pública); las agencias,
analistas y políticas son inventados para Banco Cumbre, S.A.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .configuracion import Parametros

# Departamento -> (región, peso relativo de la cartera). La región Metropolitana
# concentra la mayor parte del crédito, como en el sistema bancario.
DEPARTAMENTOS = {
    "Guatemala": ("Metropolitana", 0.56),
    "Sacatepéquez": ("Metropolitana", 0.04),
    "Quetzaltenango": ("Occidente", 0.06),
    "San Marcos": ("Occidente", 0.03),
    "Huehuetenango": ("Occidente", 0.03),
    "Totonicapán": ("Occidente", 0.01),
    "Chimaltenango": ("Occidente", 0.03),
    "Zacapa": ("Oriente", 0.03),
    "Chiquimula": ("Oriente", 0.03),
    "Jutiapa": ("Oriente", 0.02),
    "El Progreso": ("Oriente", 0.02),
    "Izabal": ("Oriente", 0.02),
    "Alta Verapaz": ("Norte", 0.03),
    "Petén": ("Norte", 0.03),
    "Escuintla": ("Sur", 0.04),
    "Suchitepéquez": ("Sur", 0.01),
    "Retalhuleu": ("Sur", 0.01),
}

CANALES = {
    "AGE": "Agencia",
    "DIG": "Digital",
    "FVE": "Fuerza de ventas",
    "BEM": "Banca empresarial",
}

# Canal de originación más probable por producto (pesos por canal).
CANALES_POR_PRODUCTO = {
    "TC": {"AGE": 0.35, "DIG": 0.45, "FVE": 0.20},
    "CONS": {"AGE": 0.55, "DIG": 0.25, "FVE": 0.20},
    "HIPO": {"AGE": 0.80, "FVE": 0.20},
    "EMP_MAYOR": {"BEM": 1.0},
    "EMP_MENOR": {"BEM": 0.70, "AGE": 0.30},
    "MICRO": {"AGE": 0.70, "FVE": 0.30},
}

SECTORES = [
    "Agroindustria",
    "Comercio",
    "Construcción",
    "Energía",
    "Manufactura",
    "Servicios",
    "Transporte",
    "Turismo",
    "Inmobiliario",
    "Salud",
]

CANALES_PAGO = ["Agencia", "Banca en línea", "App móvil", "Débito automático", "Corresponsal"]

CUENTAS_CONTABLES = {
    # producto -> cuenta del mayor (catálogo contable simplificado e inventado)
    "TC": "1301.01 Cartera de tarjetas de crédito",
    "CONS": "1301.02 Cartera de consumo",
    "HIPO": "1301.03 Cartera hipotecaria para vivienda",
    "EMP_MAYOR": "1301.04 Cartera empresarial mayor",
    "EMP_MENOR": "1301.05 Cartera empresarial menor",
    "MICRO": "1301.06 Cartera de microcréditos",
}


def productos(p: Parametros) -> pd.DataFrame:
    filas = []
    for codigo, d in p.productos.items():
        filas.append(
            {
                "producto_codigo": codigo,
                "producto_nombre": d["nombre"],
                "familia": d["familia"],
                "segmento_jm47": d["segmento_jm47"],
                "es_revolvente": d["plazo_meses"] == [0],
                "tasa_anual": d["tasa_anual"],
                "cuenta_contable": CUENTAS_CONTABLES[codigo],
            }
        )
    return pd.DataFrame(filas)


def agencias(rng: np.random.Generator) -> pd.DataFrame:
    """Una agencia por cada 0,02 de peso del departamento (mínimo una)."""
    filas = []
    numero = 1
    for depto, (region, peso) in DEPARTAMENTOS.items():
        for i in range(max(1, round(peso / 0.02))):
            filas.append(
                {
                    "agencia_codigo": f"AG-{numero:03d}",
                    "agencia_nombre": f"Agencia {depto} {i + 1}",
                    "departamento": depto,
                    "region": region,
                    "peso": peso / max(1, round(peso / 0.02)),
                }
            )
            numero += 1
    df = pd.DataFrame(filas)
    df["peso"] = df["peso"] / df["peso"].sum()
    return df


def canales() -> pd.DataFrame:
    return pd.DataFrame({"canal_codigo": list(CANALES), "canal_nombre": list(CANALES.values())})


def analistas(rng: np.random.Generator) -> pd.DataFrame:
    """Analistas de crédito. 'sesgo' mide qué tan laxo es su criterio (antes del scorecard)."""
    n = 18
    return pd.DataFrame(
        {
            "analista_codigo": [f"AN-{i:02d}" for i in range(1, n + 1)],
            "nivel_autorizacion": rng.choice(["Analista", "Jefe de análisis"], size=n, p=[0.8, 0.2]),
            "_sesgo": rng.normal(0.0, 0.35, size=n).round(3),
        }
    )


def politicas(p: Parametros) -> pd.DataFrame:
    df = pd.DataFrame(p.seccion("politicas")).rename(
        columns={
            "id": "politica_id",
            "producto": "producto_codigo",
        }
    )
    df["vigente_desde"] = pd.to_datetime(df["vigente_desde"])
    df = df.sort_values(["producto_codigo", "vigente_desde"])
    df["vigente_hasta"] = df.groupby("producto_codigo")["vigente_desde"].shift(-1) - pd.Timedelta(days=1)
    return df.reset_index(drop=True)


def politica_vigente(tabla: pd.DataFrame, producto: str, fecha: pd.Timestamp) -> pd.Series:
    """Devuelve la versión de política vigente para un producto en una fecha."""
    candidatas = tabla[(tabla.producto_codigo == producto) & (tabla.vigente_desde <= fecha)]
    return candidatas.iloc[-1]
