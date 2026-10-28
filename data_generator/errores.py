"""Errores inyectados a propósito en los datos de Landing.

Un pipeline de calidad solo se puede probar si existen errores que detectar.
Este módulo daña una pequeña parte de los datos de forma controlada y deja la
lista exacta en `_control/errores_inyectados.json`. Las pruebas de la capa
Silver (actividad 3.3) deben encontrar exactamente esos registros: es la
"respuesta correcta" contra la que se mide la calidad.

Cada error está ligado a una dimensión de calidad de la metodología del Lab.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .configuracion import Parametros


def inyectar(
    p: Parametros, rng: np.random.Generator, tablas: dict[str, pd.DataFrame]
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Devuelve copias de las tablas con errores y el registro de lo inyectado."""
    e = p.seccion("errores")
    t = {k: v.copy() for k, v in tablas.items()}
    registro: dict[str, dict] = {}

    # 1. Unicidad · pagos duplicados (mismo pago_id repetido, como una doble carga).
    pagos = t["pagos"]
    n_dup = max(1, int(len(pagos) * e["pagos_duplicados"]))
    dup = pagos.sample(n_dup, random_state=rng)
    t["pagos"] = pd.concat([pagos, dup], ignore_index=True)
    registro["pagos_duplicados"] = {"dimension": "Unicidad", "cantidad": n_dup, "ids": sorted(dup.pago_id.tolist())}

    # 2. Validez · fechas de pago fuera de rango.
    n_fecha = min(e["pagos_fecha_invalida"], len(pagos))
    idx = rng.choice(len(pagos), n_fecha, replace=False)
    malas = rng.choice(["1900-01-01", "2099-12-31", "2026-02-30"], n_fecha)
    t["pagos"]["fecha_pago"] = t["pagos"]["fecha_pago"].astype("string").str[:10]
    t["pagos"].loc[idx, "fecha_pago"] = malas
    registro["pagos_fecha_invalida"] = {
        "dimension": "Validez",
        "cantidad": int(n_fecha),
        "ids": sorted(t["pagos"].loc[idx, "pago_id"].tolist()),
    }

    # 3. Validez · saldos negativos en el extracto mensual del core.
    saldos = t["saldos"]
    n_neg = min(e["saldos_negativos"], len(saldos))
    idx = rng.choice(len(saldos), n_neg, replace=False)
    saldos.loc[idx, "saldo_capital"] = -saldos.loc[idx, "saldo_capital"].abs().clip(lower=1)
    registro["saldos_negativos"] = {
        "dimension": "Validez",
        "cantidad": int(n_neg),
        "llaves": saldos.loc[idx, ["periodo", "prestamo_id"]].astype(str).agg("|".join, axis=1).sort_values().tolist(),
    }

    # 4. Completitud · clientes individuales sin DPI.
    cl = t["clientes"]
    individuales = np.flatnonzero(cl.tipo_persona.to_numpy() == "Individual")
    n_sin = max(1, int(len(individuales) * e["clientes_dpi_faltante"]))
    idx_sin = rng.choice(individuales, n_sin, replace=False)
    cl.loc[idx_sin, "dpi"] = None
    registro["clientes_dpi_faltante"] = {
        "dimension": "Completitud",
        "cantidad": int(n_sin),
        "ids": sorted(cl.loc[idx_sin, "cliente_id"].tolist()),
    }

    # 5. Validez · DPI con formato inválido (12 dígitos o con letras).
    restantes = np.setdiff1d(individuales, idx_sin)
    n_inv = min(e["clientes_dpi_formato_invalido"], len(restantes))
    idx_inv = rng.choice(restantes, n_inv, replace=False)
    cl.loc[idx_inv, "dpi"] = [
        d[:-1] if i % 2 == 0 else d[:5] + "O" + d[6:] for i, d in enumerate(cl.loc[idx_inv, "dpi"])
    ]
    registro["clientes_dpi_formato_invalido"] = {
        "dimension": "Validez",
        "cantidad": int(n_inv),
        "ids": sorted(cl.loc[idx_inv, "cliente_id"].tolist()),
    }

    # 6. Unicidad · el mismo cliente (mismo DPI) registrado con dos códigos.
    sanos = np.setdiff1d(restantes, idx_inv)
    n_cd = min(e["clientes_duplicados"], len(sanos))
    origen = cl.iloc[rng.choice(sanos, n_cd, replace=False)].copy()
    nuevos_ids = [f"CL-9{i:06d}" for i in range(1, n_cd + 1)]
    registro["clientes_duplicados"] = {
        "dimension": "Unicidad",
        "cantidad": int(n_cd),
        "pares": [[a, b] for a, b in zip(origen.cliente_id, nuevos_ids, strict=True)],
    }
    origen["cliente_id"] = nuevos_ids
    t["clientes"] = pd.concat([cl, origen], ignore_index=True)

    # 7. Control OB-05 · desembolsos ligados a una solicitud que fue rechazada.
    pr = t["prestamos"]
    sol = t["solicitudes"]
    rechazadas = sol[sol.decision == "Rechazada"].solicitud_id.to_numpy()
    originados = np.flatnonzero(
        (pr.origen == "originacion").to_numpy() & (pr.fecha_desembolso >= pd.Timestamp(p.periodo_inicio)).to_numpy()
    )
    n_ob = min(e["desembolsos_sin_solicitud"], len(originados), len(rechazadas))
    idx = rng.choice(originados, n_ob, replace=False)
    pr.loc[idx, "solicitud_id"] = rng.choice(rechazadas, n_ob, replace=False)
    registro["desembolsos_sin_solicitud_aprobada"] = {
        "dimension": "Control OB-05 (integridad de originación)",
        "cantidad": int(n_ob),
        "ids": sorted(pr.loc[idx, "prestamo_id"].tolist()),
    }

    # 8. Oportunidad · un archivo llega después del SLA (se registra en el manifiesto).
    registro["archivo_tardio"] = {"dimension": "Oportunidad", **e["archivo_tardio"]}
    return t, registro
