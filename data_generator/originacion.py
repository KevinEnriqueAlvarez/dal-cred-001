"""Originación: cartera inicial (stock), solicitudes de crédito y desembolsos.

Flujo por producto y mes:
1. Llegan solicitudes (volumen con estacionalidad y crecimiento anual).
2. Cada solicitante tiene un riesgo latente `z` y variables observables (5 C's).
3. Se decide:
   - Antes del go-live: criterio del analista = puntaje de referencia + ruido
     + sesgo propio del analista (decisión subjetiva y variable).
   - Desde el go-live, en tarjeta y consumo: scorecard SC-CONS v1.0 sin ruido.
   - Se aprueba si el puntaje >= corte de la política vigente y la relación
     cuota/ingreso <= máximo de la política; un pequeño porcentaje bajo el corte
     se aprueba como excepción con aprobador de nivel superior.
4. Las aprobadas se desembolsan (salvo desistimientos) y pasan a la cartera.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .catalogos import CANALES_POR_PRODUCTO, politica_vigente
from .clientes import FabricaClientes
from .configuracion import Parametros
from .scorecard_referencia import calcular_score

# Ingreso mensual de referencia del solicitante (personas) o ventas mensuales (empresas).
INGRESO_BASE = {
    "TC": 9_000,
    "CONS": 12_000,
    "HIPO": 26_000,
    "MICRO": 9_000,
    "EMP_MENOR": 450_000,
    "EMP_MAYOR": 3_500_000,
}
PRODUCTOS_EMPRESA = {"EMP_MAYOR", "EMP_MENOR"}
# Media del riesgo latente de quienes solicitan (más riesgo en tarjeta y micro).
Z_SOLICITANTE = {"TC": 0.15, "CONS": 0.0, "HIPO": -0.2, "MICRO": 0.15, "EMP_MENOR": 0.0, "EMP_MAYOR": -0.2}
PROB_CLIENTE_EXISTENTE = {"TC": 0.20, "CONS": 0.25, "HIPO": 0.15, "MICRO": 0.10}


def cuota_mensual(monto: np.ndarray, tasa_anual: float, plazo: np.ndarray) -> np.ndarray:
    """Cuota nivelada (sistema francés). Plazo 0 = tarjeta: pago de referencia del 3 % del límite."""
    r = tasa_anual / 12
    plazo = np.asarray(plazo, dtype=float)
    con_plazo = plazo > 0
    cuota = np.where(con_plazo, 0.0, 0.03 * monto)
    n = np.where(con_plazo, plazo, 1)
    cuota = np.where(con_plazo, monto * r / (1 - (1 + r) ** (-n)), cuota)
    return cuota.round(2)


def _variables_5c(
    rng: np.random.Generator, z: np.ndarray, cuota: np.ndarray, ingreso: np.ndarray
) -> dict[str, np.ndarray]:
    """Variables observables derivadas del riesgo latente con ruido independiente."""
    n = len(z)
    z1 = z + rng.normal(0, 0.75, n)
    atraso = np.select(
        [z1 < 0.8, z1 < 1.3, z1 < 1.8, z1 < 2.3],
        [0, rng.integers(5, 31, n), rng.integers(31, 61, n), rng.integers(61, 91, n)],
        rng.integers(91, 181, n),
    )
    z2 = z + rng.normal(0, 0.9, n)
    entidades = np.clip(np.round(1.6 + 0.9 * z2 + rng.normal(0, 0.6, n)), 0, 9).astype(int)
    z3 = z + rng.normal(0, 0.75, n)
    endeudamiento = np.exp(1.0 + 0.45 * z3).round(2)
    z4 = z + rng.normal(0, 0.9, n)
    antiguedad = np.clip(np.exp(3.9 - 0.45 * z4), 1, 480).astype(int)
    return {
        "atraso_max_sirc_12m": atraso,
        "entidades_con_deuda_sirc": entidades,
        "endeudamiento_sirc_meses_ingreso": endeudamiento,
        "relacion_cuota_ingreso": (cuota / np.maximum(ingreso, 1)).round(4),
        "antiguedad_laboral_meses": antiguedad,
    }


def politica_por_fecha(
    politicas: pd.DataFrame, producto: str, fechas: pd.DatetimeIndex
) -> tuple[np.ndarray, np.ndarray]:
    """Política vigente (id y corte de score) para cada fecha, vectorizado."""
    tabla = politicas[politicas.producto_codigo == producto].sort_values("vigente_desde")
    idx = np.searchsorted(tabla.vigente_desde.to_numpy(), fechas.to_numpy(), side="right") - 1
    idx = np.clip(idx, 0, len(tabla) - 1)
    return tabla.politica_id.to_numpy()[idx], tabla.corte_score.to_numpy()[idx]


def _desplazamiento_campana(politicas: pd.DataFrame, producto: str, fechas: pd.DatetimeIndex) -> np.ndarray:
    """Riesgo extra de los solicitantes atraídos por una campaña ligada a la política."""
    if "z_campana" not in politicas.columns:
        return np.zeros(len(fechas))
    tabla = politicas[politicas.producto_codigo == producto].sort_values("vigente_desde")
    idx = np.clip(np.searchsorted(tabla.vigente_desde.to_numpy(), fechas.to_numpy(), side="right") - 1, 0, None)
    return np.nan_to_num(tabla.z_campana.to_numpy(dtype=float)[idx])


def _fechas_en_mes(rng: np.random.Generator, mes: pd.Period, n: int) -> pd.DatetimeIndex:
    inicio = mes.start_time
    segundos = rng.uniform(0, (mes.end_time - inicio).total_seconds(), n)
    return pd.DatetimeIndex(inicio + pd.to_timedelta(segundos, unit="s")).floor("min")


# =============================================================================
# Cartera inicial
# =============================================================================
def generar_stock(
    p: Parametros, rng: np.random.Generator, fabrica: FabricaClientes, canales_tabla: pd.DataFrame
) -> pd.DataFrame:
    """Créditos vigentes al inicio de la simulación (desembolsados antes de 2024)."""
    inicio_sim = p.meses_simulados[0].start_time
    filas = []
    for prod, d in p.productos.items():
        n = int(round(d["stock_inicial"] * p.escala))
        if n == 0:
            continue
        # Los clientes del stock ya pasaron una selección: algo menos riesgosos.
        z = rng.normal(Z_SOLICITANTE[prod] - 0.35, 0.95, n)
        meses_atras = rng.integers(1, (inicio_sim.year - p.stock_desde.year) * 12, n)
        fechas = pd.DatetimeIndex([inicio_sim - pd.DateOffset(months=int(m)) for m in meses_atras]) + pd.to_timedelta(
            rng.integers(0, 28, n), unit="D"
        )
        if prod in PRODUCTOS_EMPRESA:
            clientes = fabrica.nuevas_empresas(z, fechas, INGRESO_BASE[prod])
        else:
            clientes = fabrica.nuevas_personas(z, fechas, INGRESO_BASE[prod])
        plazos = np.array(d["plazo_meses"])
        plazo = rng.choice(plazos, n)
        # Solo entran créditos que aún no vencen al inicio de la simulación.
        if plazos.max() > 0:
            plazo = np.maximum(plazo, meses_atras + rng.integers(2, 24, n))
            plazo = np.minimum(plazo, plazos.max() + 24)
        monto = np.exp(np.log(d["monto_mediano"]) + rng.normal(0, d["monto_dispersion"], n)).round(-2)
        filas.append(
            pd.DataFrame(
                {
                    "producto_codigo": prod,
                    "cliente_id": clientes,
                    "solicitud_id": None,
                    "fecha_desembolso": fechas,
                    "monto_desembolsado": monto,
                    "plazo_meses": plazo,
                    "tasa_anual": d["tasa_anual"],
                    "cuota": cuota_mensual(monto, d["tasa_anual"], plazo),
                    "canal_codigo": rng.choice(
                        list(CANALES_POR_PRODUCTO[prod]), n, p=list(CANALES_POR_PRODUCTO[prod].values())
                    ),
                    "politica_id": None,
                    "origen": "stock_inicial",
                    "_z": z,
                }
            )
        )
    return pd.concat(filas, ignore_index=True)


# =============================================================================
# Solicitudes y desembolsos
# =============================================================================
def generar_solicitudes(
    p: Parametros, rng: np.random.Generator, fabrica: FabricaClientes, analistas: pd.DataFrame, politicas: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (solicitudes, créditos desembolsados) de todos los meses simulados."""
    o = p.seccion("originacion")
    est = p.seccion("estacionalidad")
    go_live = pd.Timestamp(p.fecha_go_live)
    corte = pd.Timestamp(p.fecha_corte) + pd.Timedelta(hours=23, minutes=59)
    jefes = analistas[analistas.nivel_autorizacion == "Jefe de análisis"].analista_codigo.to_numpy()

    lotes_sol, lotes_cre = [], []
    contador = 0
    for mes in p.meses_simulados:
        anios = (mes.start_time - pd.Timestamp(p.periodo_inicio)).days / 365.25
        factor = est["solicitudes_mes"][mes.month] * (1 + est["crecimiento_anual_solicitudes"]) ** anios
        despues = mes.start_time >= go_live
        for prod, d in p.productos.items():
            n = int(rng.poisson(d["solicitudes_mes"] * p.escala * factor))
            if n == 0:
                continue
            fechas = _fechas_en_mes(rng, mes, n)

            # ---------------------------------------------- solicitante
            z = rng.normal(Z_SOLICITANTE[prod], 1.0, n)
            z += _desplazamiento_campana(politicas, prod, fechas)
            if prod in PRODUCTOS_EMPRESA:
                clientes = fabrica.nuevas_empresas(z, fechas, INGRESO_BASE[prod])
            else:
                existente = rng.random(n) < PROB_CLIENTE_EXISTENTE[prod]
                ids_ex, z_ex = fabrica.personas_existentes(int(existente.sum()))
                z[existente] = z_ex
                clientes = np.empty(n, dtype=object)
                clientes[existente] = ids_ex
                clientes[~existente] = fabrica.nuevas_personas(z[~existente], fechas[~existente], INGRESO_BASE[prod])
            ingreso = INGRESO_BASE[prod] * np.exp(rng.normal(-0.18 * z, 0.45))

            # ---------------------------------------------- condiciones pedidas
            monto = np.exp(np.log(d["monto_mediano"]) + rng.normal(0, d["monto_dispersion"], n)).round(-2)
            plazo = rng.choice(d["plazo_meses"], n)
            cuota = cuota_mensual(monto, d["tasa_anual"], plazo)
            sol = pd.DataFrame(
                {
                    "solicitud_id": [f"SOL-{contador + i + 1:07d}" for i in range(n)],
                    "fecha_ingreso": fechas,
                    "cliente_id": clientes,
                    "producto_codigo": prod,
                    "canal_codigo": rng.choice(
                        list(CANALES_POR_PRODUCTO[prod]), n, p=list(CANALES_POR_PRODUCTO[prod].values())
                    ),
                    "analista_codigo": rng.choice(analistas.analista_codigo.to_numpy(), n),
                    "monto_solicitado": monto,
                    "plazo_meses": plazo,
                    "tasa_anual": d["tasa_anual"],
                    "cuota_estimada": cuota,
                    "ingreso_mensual_declarado": ingreso.round(2),
                    **_variables_5c(rng, z, cuota, ingreso),
                    "_z": z,
                }
            )
            contador += n

            # ---------------------------------------------- decisión
            score_ref = calcular_score(sol)
            sesgo = analistas.set_index("analista_codigo").loc[sol.analista_codigo, "_sesgo"].to_numpy()
            criterio = score_ref + rng.normal(0, 45 * o["ruido_criterio_analista"], n) + 40 * sesgo
            usa_scorecard = despues and prod in o["productos_con_scorecard"]
            puntaje = score_ref if usa_scorecard else criterio
            pol = politica_vigente(politicas, prod, mes.start_time)
            # La política P-07 entra a mitad de mes: se aplica según la fecha de ingreso.
            politica_ids, cortes = politica_por_fecha(politicas, prod, fechas)
            cumple = (puntaje >= cortes) & (sol.relacion_cuota_ingreso.to_numpy() <= pol["cuota_ingreso_max"])
            excepcion = (~cumple) & (puntaje >= cortes - 25) & (rng.random(n) < o["tasa_excepcion_politica"] * 6)
            aprobada = cumple | excepcion
            desiste = aprobada & (rng.random(n) < o["tasa_desistimiento"])

            sol["metodo_decision"] = "Scorecard SC-CONS v1.0" if usa_scorecard else "Criterio del analista"
            sol["puntaje_decision"] = np.round(puntaje).astype(int)
            sol["score_sc_cons_v1"] = pd.array(
                np.where(despues and prod in o["productos_con_scorecard"], score_ref, np.nan), dtype="Int64"
            )
            sol["politica_id"] = politica_ids
            sol["corte_politica"] = cortes
            sol["es_excepcion"] = excepcion
            sol["aprobador_excepcion"] = np.where(excepcion, rng.choice(jefes, n), None)
            sol["decision"] = np.select([desiste, aprobada], ["Desistida", "Aprobada"], "Rechazada")
            sol["monto_aprobado"] = np.where(aprobada, monto, np.nan)

            # ---------------------------------------------- tiempos y controles
            if despues:
                avance = min(1.0, (mes.start_time - go_live).days / 180)
                mediana = o["horas_respuesta_mediana"]["antes"] + avance * (
                    o["horas_respuesta_mediana"]["despues"] - o["horas_respuesta_mediana"]["antes"]
                )
            else:
                mediana = o["horas_respuesta_mediana"]["antes"]
            horas = np.exp(np.log(mediana) + rng.normal(0, 0.45, n))
            if prod in PRODUCTOS_EMPRESA | {"HIPO"}:
                horas *= 2.5
            sol["fecha_resolucion"] = (fechas + pd.to_timedelta(horas, unit="h")).floor("min")
            pendiente = sol["fecha_resolucion"] > corte
            sol.loc[pendiente, ["fecha_resolucion"]] = pd.NaT
            sol.loc[pendiente, "decision"] = "En análisis"
            sol.loc[pendiente, "monto_aprobado"] = np.nan

            etapa = "despues" if despues else "antes"
            sol["expediente_completo"] = rng.random(n) < o["completitud_expediente"][etapa]
            sol["screening_ld_realizado"] = rng.random(n) < o["cobertura_screening_ld"][etapa]
            sol["coincidencia_listas"] = rng.random(n) < 0.0008
            es_hipo = prod == "HIPO"
            efectivo = es_hipo & (rng.random(n) < 0.04)
            sol["enganche_efectivo_gtq"] = np.where(efectivo, rng.uniform(40_000, 220_000, n).round(-2), 0.0)
            sol["origen_fondos_documentado"] = np.where(efectivo, rng.random(n) < 0.7, True)
            lotes_sol.append(sol)

            # ---------------------------------------------- desembolsos
            des = sol[sol.decision == "Aprobada"]
            if len(des):
                fecha_des = des.fecha_resolucion + pd.to_timedelta(rng.integers(0, 6, len(des)), unit="D")
                fecha_des = fecha_des.where(fecha_des <= corte, corte.normalize())
                lotes_cre.append(
                    pd.DataFrame(
                        {
                            "producto_codigo": prod,
                            "cliente_id": des.cliente_id.to_numpy(),
                            "solicitud_id": des.solicitud_id.to_numpy(),
                            "fecha_desembolso": fecha_des.dt.normalize().to_numpy(),
                            "monto_desembolsado": des.monto_solicitado.to_numpy(),
                            "plazo_meses": des.plazo_meses.to_numpy(),
                            "tasa_anual": d["tasa_anual"],
                            "cuota": des.cuota_estimada.to_numpy(),
                            "canal_codigo": des.canal_codigo.to_numpy(),
                            "politica_id": des.politica_id.to_numpy(),
                            "origen": "originacion",
                            "_z": des._z.to_numpy(),
                        }
                    )
                )

    solicitudes = pd.concat(lotes_sol, ignore_index=True)
    creditos = pd.concat(lotes_cre, ignore_index=True)
    return solicitudes, creditos
