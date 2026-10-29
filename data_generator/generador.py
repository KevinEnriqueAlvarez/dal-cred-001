"""Orquesta la generación completa: catálogos -> clientes -> originación ->
simulación de cartera -> contabilidad -> errores inyectados -> archivos.

`generar()` devuelve las tablas en memoria (útil para pruebas y calibración);
`__main__` las escribe en la zona Landing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import cartera, catalogos, contabilidad, originacion
from .clientes import FabricaClientes
from .configuracion import Parametros


@dataclass
class Resultado:
    """Tablas generadas, todavía sin errores inyectados (versión "limpia")."""

    catalogos: dict[str, pd.DataFrame]
    clientes: pd.DataFrame
    grupos: pd.DataFrame
    solicitudes: pd.DataFrame
    prestamos: pd.DataFrame
    saldos: pd.DataFrame
    pagos: pd.DataFrame
    garantias: pd.DataFrame
    castigos: pd.DataFrame
    mayor: pd.DataFrame


def _concentrar_grupo(p: Parametros, prestamos: pd.DataFrame, saldos: pd.DataFrame, fabrica: FabricaClientes) -> None:
    """Asigna créditos empresariales mayores al grupo concentrado hasta la participación objetivo."""
    objetivo = p.seccion("grupos_economicos")["grupo_concentrado"]
    corte = str(pd.Period(p.fecha_corte, freq="M"))
    al_corte = saldos[saldos.periodo == corte].merge(prestamos[["prestamo_id", "cliente_id", "producto_codigo"]])
    total = al_corte.saldo_capital.sum()
    candidatos = (
        al_corte[al_corte.producto_codigo == "EMP_MAYOR"]
        .groupby("cliente_id")
        .saldo_capital.sum()
        .sort_values(ascending=False)
    )
    meta = objetivo["participacion_objetivo"] * total
    elegidos, acumulado = [], 0.0
    for cliente, saldo in candidatos.items():
        if acumulado + saldo > meta * 1.05:
            continue
        elegidos.append(cliente)
        acumulado += saldo
        if acumulado >= meta * 0.95:
            break
    fabrica.asignar_a_grupo(np.array(elegidos), objetivo["id"])


def generar(p: Parametros) -> Resultado:
    rng = np.random.default_rng(p.semilla)
    cat = {
        "productos": catalogos.productos(p),
        "agencias": catalogos.agencias(rng),
        "canales": catalogos.canales(),
        "analistas": catalogos.analistas(rng),
        "politicas": catalogos.politicas(p),
    }
    ge = p.seccion("grupos_economicos")
    fabrica = FabricaClientes(rng, p.semilla, cat["agencias"], ge["cantidad"], ge["grupo_concentrado"])

    stock = originacion.generar_stock(p, rng, fabrica, cat["canales"])
    solicitudes, desembolsos = originacion.generar_solicitudes(p, rng, fabrica, cat["analistas"], cat["politicas"])
    creditos = pd.concat([stock, desembolsos], ignore_index=True)

    prestamos, saldos, pagos = cartera.simular(p, rng, creditos)
    _concentrar_grupo(p, prestamos, saldos, fabrica)

    # Solo se publican los créditos vivos en algún momento del periodo (2025 en adelante).
    inicio = pd.Timestamp(p.periodo_inicio)
    vivos = prestamos.fecha_fin.isna() | (prestamos.fecha_fin >= inicio)
    prestamos = prestamos[vivos].reset_index(drop=True)

    clientes = fabrica.tabla()
    agencia_cliente = clientes.set_index("cliente_id").agencia_codigo
    prestamos["agencia_codigo"] = prestamos.cliente_id.map(agencia_cliente)
    primeras = ["prestamo_id", "cliente_id", "producto_codigo", "solicitud_id"]
    prestamos = prestamos[primeras + [c for c in prestamos.columns if c not in primeras]]

    inicio_pub = pd.Timestamp(p.periodo_inicio)
    solicitudes = solicitudes[solicitudes.fecha_ingreso >= inicio_pub].reset_index(drop=True)

    return Resultado(
        catalogos=cat,
        clientes=clientes,
        grupos=fabrica.grupos.drop(columns="peso"),
        solicitudes=solicitudes,
        prestamos=prestamos,
        saldos=saldos,
        pagos=pagos,
        garantias=contabilidad.garantias(rng, prestamos),
        castigos=contabilidad.castigos(prestamos),
        mayor=contabilidad.mayor_contable(rng, saldos, prestamos),
    )
