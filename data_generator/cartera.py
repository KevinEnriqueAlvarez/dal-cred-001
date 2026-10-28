"""Simulación mensual de la cartera: saldos, mora, pagos, cancelaciones y castigos.

Cada crédito se mueve mes a mes entre tramos de mora con una cadena de Markov:

    0 al día -> 1 (1–30 días) -> 2 (31–60) -> 3 (61–90) -> 4 (90+) -> castigo

- La probabilidad de caer en mora depende del producto (riesgo_base), del riesgo
  latente del cliente z, de la madurez del crédito (los primeros meses son de
  menor riesgo) y del mes calendario (Bono 14 y aguinaldo mejoran el pago).
- Un crédito en mora puede curarse (paga sus cuotas atrasadas), avanzar al tramo
  siguiente o quedarse. Tras `castigo_meses_en_90` meses en 90+ se castiga y
  sale de la cartera.
- Los créditos a plazo amortizan con cuota nivelada solo cuando pagan; mientras
  están en mora, el saldo de capital no baja. Las tarjetas son revolventes: su
  saldo es una fracción del límite que se mueve cada mes.

Supuesto documentado: "vencido" = más de 90 días de atraso. Las reglas exactas
de traslado a cartera vencida se aplican en la capa Silver con la normativa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .configuracion import Parametros

PREPAGO_TOTAL_MENSUAL = {
    "CONS": 0.010,
    "HIPO": 0.004,
    "EMP_MAYOR": 0.006,
    "EMP_MENOR": 0.008,
    "MICRO": 0.012,
    "TC": 0.0,
}
CIERRE_TARJETA_MENSUAL = 0.009
DISTRIBUCION_INICIAL = [0.955, 0.020, 0.008, 0.006, 0.011]  # tramos al inicio del burn-in


def _saldo_programado(monto, tasa_mensual, plazo, pagadas):
    """Saldo de capital tras `pagadas` cuotas niveladas (sistema francés)."""
    plazo = np.maximum(plazo, 1)
    f_n = (1 + tasa_mensual) ** plazo
    f_k = (1 + tasa_mensual) ** np.minimum(pagadas, plazo)
    return np.maximum(monto * (f_n - f_k) / (f_n - 1), 0.0)


def _dias_atraso(rng, tramo, meses_en_90):
    n = len(tramo)
    dentro = rng.integers(1, 31, n)
    dias = np.where(tramo == 0, 0, 30 * (tramo - 1) + dentro)
    return np.where(tramo == 4, 90 + 30 * meses_en_90 + dentro, dias)


def _fechas_pago(rng, mes: pd.Period, productos: np.ndarray) -> np.ndarray:
    """Consumo se paga en quincena (15 o fin de mes, ±2 días); el resto, cualquier día."""
    n = len(productos)
    ultimo = mes.days_in_month
    quincena = np.where(rng.random(n) < 0.5, 15, ultimo) + rng.integers(-2, 1, n)
    libre = rng.integers(1, ultimo + 1, n)
    usa_quincena = (productos == "CONS") & (rng.random(n) < 0.7)
    dia = np.clip(np.where(usa_quincena, quincena, libre), 1, ultimo)
    return (mes.start_time + pd.to_timedelta(dia - 1, unit="D")).to_numpy()


def simular(
    p: Parametros, rng: np.random.Generator, creditos: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Devuelve (créditos con estado final, saldos mensuales, pagos)."""
    tr = p.seccion("transiciones")
    est = p.seccion("estacionalidad")
    meses = p.meses_simulados
    publicados = set(p.meses_publicados)

    cr = creditos.sort_values("fecha_desembolso", kind="stable").reset_index(drop=True)
    cr["prestamo_id"] = [f"PR-{i:07d}" for i in range(1, len(cr) + 1)]
    n = len(cr)

    prod = cr.producto_codigo.to_numpy()
    z = cr._z.to_numpy()
    monto = cr.monto_desembolsado.to_numpy(dtype=float)
    plazo = cr.plazo_meses.to_numpy(dtype=float)
    tasa_m = cr.tasa_anual.to_numpy(dtype=float) / 12
    es_tc = prod == "TC"
    riesgo_base = np.array([p.productos[x]["riesgo_base"] for x in prod])
    prepago = np.array([PREPAGO_TOTAL_MENSUAL[x] for x in prod])

    mes_des = pd.PeriodIndex(cr.fecha_desembolso, freq="M")
    idx_inicio = mes_des.asi8 - meses[0].ordinal

    # ------------------------------------------------------------ estado inicial
    tramo = np.zeros(n, dtype=np.int8)
    meses_90 = np.zeros(n, dtype=np.int16)
    edad_ini = np.maximum(-idx_inicio, 0)
    pagadas = edad_ini.astype(float)
    del_stock = idx_inicio < 0
    tramo[del_stock] = rng.choice(5, del_stock.sum(), p=DISTRIBUCION_INICIAL)
    meses_90[del_stock & (tramo == 4)] = rng.integers(0, tr["castigo_meses_en_90"], (del_stock & (tramo == 4)).sum())
    uso_tc = np.clip(rng.beta(2.2, 2.6, n), 0.02, 0.98)
    factor_abono = np.ones(n)  # baja por abonos extraordinarios
    estado = np.zeros(n, dtype=np.int8)  # 0 activo, 1 cancelado, 2 castigado
    fecha_fin = np.full(n, np.datetime64("NaT", "ns"))
    saldo_castigo = np.zeros(n)

    saldos_lotes, pagos_lotes = [], []
    cura = {int(k): v for k, v in tr["cura"].items()}
    avance = {int(k): v for k, v in tr["avance"].items()}
    sens = tr["sensibilidad_riesgo"]

    for t, mes in enumerate(meses):
        activo = (idx_inicio <= t) & (estado == 0)
        nuevo = activo & (idx_inicio == t)
        evoluciona = activo & ~nuevo
        edad = t - idx_inicio
        tramo_previo = tramo.copy()

        # -------------------------------------------------- transición de mora
        u = rng.random(n)
        madurez = np.where(np.isin(prod, ["TC", "CONS", "MICRO"]), np.minimum(1.0, 0.35 + edad / 9), 1.0)
        p_mora = riesgo_base * est["riesgo_mes"][mes.month] * np.exp(sens * z) * madurez
        cae = evoluciona & (tramo == 0) & (u < p_mora)
        cambio = tramo.copy()
        cambio[cae] = 1
        despues = mes.start_time >= pd.Timestamp(p.fecha_go_live)
        for b in (1, 2, 3, 4):
            en_b = evoluciona & (tramo == b)
            mejora = 1 + tr["mejora_cura_post_golive"] if (despues and b <= 2) else 1.0
            pc = cura[b] * mejora * np.exp(-0.3 * z)
            pa = avance.get(b, 0.0) * np.exp(0.3 * z)
            se_cura = en_b & (u < pc)
            avanza = en_b & ~se_cura & (u < pc + pa) & (b < 4)
            cambio[se_cura] = 0
            cambio[avanza] = b + 1
        tramo = cambio
        meses_90 = np.where(tramo == 4, np.where(tramo_previo == 4, meses_90 + 1, 0), 0).astype(np.int16)

        # -------------------------------------------------- castigos
        castiga = evoluciona & (tramo == 4) & (meses_90 >= tr["castigo_meses_en_90"])

        # -------------------------------------------------- pagos y saldos
        paga_normal = evoluciona & (tramo_previo == 0) & (tramo == 0)
        se_curo = evoluciona & (tramo_previo > 0) & (tramo == 0)
        saldo_antes = np.where(es_tc, monto * uso_tc, _saldo_programado(monto, tasa_m, plazo, pagadas) * factor_abono)
        cuotas_mora = np.where(se_curo, np.maximum(edad - pagadas, 1), 0)
        pagadas = np.where(paga_normal & ~es_tc, pagadas + 1, pagadas)
        pagadas = np.where(se_curo & ~es_tc, np.minimum(edad, plazo), pagadas)

        # Tarjeta: el uso del límite se mueve; en mora crece por intereses.
        uso_tc = np.where(
            es_tc & evoluciona,
            np.clip(uso_tc + rng.normal(0, 0.05, n) + np.where(tramo > 0, 0.03, -0.004), 0.01, 1.25),
            uso_tc,
        )

        # Abonos extraordinarios en Bono 14 y aguinaldo; cancelaciones anticipadas.
        abona = paga_normal & ~es_tc & (mes.month in est["prepago_meses"]) & (rng.random(n) < 0.06)
        porcentaje_abono = rng.uniform(0.10, 0.30, n)
        cancela_ant = paga_normal & ~es_tc & (rng.random(n) < prepago)
        cierra_tc = es_tc & paga_normal & (rng.random(n) < CIERRE_TARJETA_MENSUAL)

        saldo = np.where(es_tc, monto * uso_tc, _saldo_programado(monto, tasa_m, plazo, pagadas) * factor_abono)
        saldo = np.where(nuevo & es_tc, monto * uso_tc, saldo)
        saldo = np.where(nuevo & ~es_tc, monto, saldo)
        monto_abono = np.where(abona, saldo * porcentaje_abono, 0.0)
        factor_abono = np.where(abona, factor_abono * (1 - porcentaje_abono), factor_abono)
        saldo = saldo - monto_abono
        vence = ~es_tc & evoluciona & (pagadas >= plazo) & (tramo == 0)

        # Monto de cada pago del mes.
        interes = np.where(es_tc, saldo_antes * 0.035, saldo_antes * tasa_m)
        cuota = cr.cuota.to_numpy(dtype=float)
        pago_tc = np.maximum(0.05 * saldo_antes, np.minimum(saldo_antes, saldo_antes * rng.uniform(0.05, 0.6, n)))
        monto_pago = np.where(es_tc, pago_tc, cuota * np.where(se_curo, cuotas_mora + 1, 1))
        monto_pago = np.where(cancela_ant, saldo_antes + interes, monto_pago)
        hay_pago = paga_normal | se_curo | cancela_ant
        tipo = np.select(
            [cancela_ant, se_curo, es_tc],
            ["Cancelación anticipada", "Pago de cuotas en mora", "Pago de tarjeta"],
            "Cuota",
        )

        # Cierres del mes.
        cierra = cancela_ant | vence | cierra_tc
        fin_mes = mes.end_time.normalize().to_datetime64()
        fecha_fin = np.where((cierra | castiga) & (estado == 0), fin_mes, fecha_fin)
        saldo_castigo = np.where(castiga, saldo, saldo_castigo)
        estado = np.where(castiga, 2, np.where(cierra, 1, estado)).astype(np.int8)

        if mes in publicados:
            # Una fila por crédito activo al cierre del mes (los que cierran ya no reportan saldo).
            reporta = activo & ~cierra & ~castiga
            ids = np.flatnonzero(reporta)
            saldos_lotes.append(
                pd.DataFrame(
                    {
                        "periodo": str(mes),
                        "fecha_corte": mes.end_time.normalize(),
                        "prestamo_id": cr.prestamo_id.to_numpy()[ids],
                        "saldo_capital": saldo[ids].round(2),
                        "dias_atraso": _dias_atraso(rng, tramo[ids], meses_90[ids]),
                        "cuotas_pagadas": pagadas[ids].astype(int),
                        "limite_credito": np.where(es_tc[ids], monto[ids], np.nan),
                    }
                )
            )
            con_pago = np.flatnonzero(hay_pago)
            if len(con_pago):
                pagos_lotes.append(
                    pd.DataFrame(
                        {
                            "prestamo_id": cr.prestamo_id.to_numpy()[con_pago],
                            "fecha_pago": _fechas_pago(rng, mes, prod[con_pago]),
                            "monto_pagado": monto_pago[con_pago].round(2),
                            "interes": np.minimum(interes[con_pago], monto_pago[con_pago]).round(2),
                            "tipo_pago": tipo[con_pago],
                        }
                    )
                )
            con_abono = np.flatnonzero(abona)
            if len(con_abono):
                pagos_lotes.append(
                    pd.DataFrame(
                        {
                            "prestamo_id": cr.prestamo_id.to_numpy()[con_abono],
                            "fecha_pago": _fechas_pago(rng, mes, prod[con_abono]),
                            "monto_pagado": monto_abono[con_abono].round(2),
                            "interes": 0.0,
                            "tipo_pago": "Abono extraordinario",
                        }
                    )
                )

    cr["estado_final"] = np.select([estado == 1, estado == 2], ["Cancelado", "Castigado"], "Activo")
    cr["fecha_fin"] = pd.to_datetime(fecha_fin)
    cr["saldo_castigado"] = np.where(estado == 2, saldo_castigo.round(2), np.nan)

    saldos = pd.concat(saldos_lotes, ignore_index=True)
    pagos = pd.concat(pagos_lotes, ignore_index=True)
    pagos["capital"] = (pagos.monto_pagado - pagos.interes).round(2)
    pagos = pagos.sort_values(["fecha_pago", "prestamo_id"], kind="stable").reset_index(drop=True)
    pagos.insert(0, "pago_id", [f"PG-{i:08d}" for i in range(1, len(pagos) + 1)])
    pagos["canal_pago"] = rng.choice(
        ["Agencia", "Banca en línea", "App móvil", "Débito automático", "Corresponsal"],
        len(pagos),
        p=[0.30, 0.25, 0.20, 0.15, 0.10],
    )
    return cr, saldos, pagos
