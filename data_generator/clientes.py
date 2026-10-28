"""Clientes (personas y empresas) y grupos económicos.

Cada cliente tiene un riesgo latente `z` (normal estándar; mayor = más riesgoso)
que NO se publica: es la "verdad oculta" que explica su comportamiento de pago.
Los atributos observables (ingreso, historial en el SIRC, antigüedad laboral)
se derivan de `z` con ruido, igual que en la realidad: dan pistas del riesgo,
pero no lo revelan por completo. Por eso un scorecard discrimina, pero nunca
de forma perfecta.

Identificadores sintéticos:
- DPI (CUI) de 13 dígitos que termina en "9999". Los últimos 4 dígitos del CUI
  son departamento y municipio; 99/99 no existe, así que ningún DPI generado
  puede pertenecer a una persona real.
- NIT de empresa con formato NNNNNNN-K, también inventado.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

from .catalogos import SECTORES

PALABRAS_EMPRESA_1 = np.array(
    [
        "Agroindustrias",
        "Comercializadora",
        "Constructora",
        "Distribuidora",
        "Inversiones",
        "Servicios",
        "Industrias",
        "Transportes",
        "Desarrollos",
        "Exportadora",
        "Alimentos",
        "Energía",
        "Textiles",
        "Logística",
        "Corporación",
    ]
)
PALABRAS_EMPRESA_2 = np.array(
    [
        "del Altiplano",
        "Cumbre Verde",
        "Las Brisas",
        "Volcán Azul",
        "El Mirador",
        "Río Dulce Norte",
        "La Ceiba",
        "Quetzal Real",
        "Los Pinos",
        "Sierra Madre",
        "Monte Claro",
        "Costa Serena",
        "Valle Alto",
        "Lago Sereno",
        "Tierra Fértil",
    ]
)


class FabricaClientes:
    """Crea clientes por lotes y lleva el registro de todos los creados.

    Los métodos reciben arreglos (un elemento por cliente) para generar miles
    de clientes en una sola llamada vectorizada.
    """

    def __init__(
        self,
        rng: np.random.Generator,
        semilla: int,
        agencias: pd.DataFrame,
        cantidad_grupos: int,
        grupo_concentrado: dict,
    ):
        self.rng = rng
        self.faker = Faker("es_MX")
        self.faker.seed_instance(semilla)
        self.agencias = agencias.reset_index(drop=True)
        self.lotes: list[pd.DataFrame] = []
        self.total = 0
        self.grupo_concentrado = grupo_concentrado["id"]
        self.grupos = self._crear_grupos(cantidad_grupos, grupo_concentrado)
        # Registro rápido de personas para reutilizarlas (clientes multiproducto).
        self._personas_id: list[np.ndarray] = []
        self._personas_z: list[np.ndarray] = []

    # ------------------------------------------------------------------ grupos
    def _crear_grupos(self, cantidad: int, concentrado: dict) -> pd.DataFrame:
        ids = [f"G-{i:03d}" for i in range(1, cantidad + 1)]
        sectores = self.rng.choice(SECTORES, size=cantidad)
        pesos = self.rng.pareto(1.6, size=cantidad) + 1
        idx = ids.index(concentrado["id"])
        sectores[idx] = concentrado["sector"]
        df = pd.DataFrame(
            {
                "grupo_economico_id": ids,
                "grupo_nombre": [
                    f"Grupo {self.rng.choice(PALABRAS_EMPRESA_2)} {i:03d}" for i in range(1, cantidad + 1)
                ],
                "sector": sectores,
                "peso": pesos / pesos.sum(),
            }
        )
        return df

    # ----------------------------------------------------------------- comunes
    def _ids(self, n: int) -> np.ndarray:
        ids = np.array([f"CL-{i:07d}" for i in range(self.total + 1, self.total + n + 1)])
        self.total += n
        return ids

    def _ubicacion(self, n: int) -> pd.DataFrame:
        idx = self.rng.choice(len(self.agencias), size=n, p=self.agencias["peso"].to_numpy())
        return self.agencias.iloc[idx][["agencia_codigo", "departamento", "region"]].reset_index(drop=True)

    # ---------------------------------------------------------------- personas
    def nuevas_personas(self, z: np.ndarray, fechas_alta: pd.DatetimeIndex, ingreso_base: float) -> np.ndarray:
        n = len(z)
        if n == 0:
            return np.array([], dtype=object)
        ids = self._ids(n)
        ubic = self._ubicacion(n)
        edad = np.clip(self.rng.normal(38, 10, n), 19, 75).astype(int)
        # Ingreso log-normal; quien es más riesgoso tiende a ganar menos.
        ingreso = ingreso_base * np.exp(self.rng.normal(-0.18 * z, 0.45))
        dpi = self.rng.integers(100_000_000, 999_999_999, n).astype(str).astype(object) + "9999"
        dias_edad = edad * 365 + self.rng.integers(0, 365, n)
        nacimiento = pd.DatetimeIndex(fechas_alta) - pd.to_timedelta(dias_edad, unit="D")
        lote = pd.DataFrame(
            {
                "cliente_id": ids,
                "tipo_persona": "Individual",
                "nombre": [self.faker.name() for _ in range(n)],
                "dpi": dpi,
                "nit": None,
                "fecha_nacimiento": nacimiento.date,
                "departamento": ubic["departamento"].to_numpy(),
                "region": ubic["region"].to_numpy(),
                "agencia_codigo": ubic["agencia_codigo"].to_numpy(),
                "tipo_empleo": self.rng.choice(["Asalariado", "Independiente", "Profesional"], n, p=[0.62, 0.25, 0.13]),
                "ingreso_mensual": ingreso.round(2),
                "sector": None,
                "grupo_economico_id": None,
                "es_pep": self.rng.random(n) < 0.004,
                "fecha_alta": pd.DatetimeIndex(fechas_alta).date,
                "_z": z,
            }
        )
        self.lotes.append(lote)
        self._personas_id.append(ids)
        self._personas_z.append(z)
        return ids

    def personas_existentes(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Elige n personas ya creadas (para clientes con varios productos)."""
        if n == 0 or not self._personas_id:
            return np.array([], dtype=object), np.array([])
        todos_id = np.concatenate(self._personas_id)
        todos_z = np.concatenate(self._personas_z)
        idx = self.rng.integers(0, len(todos_id), n)
        return todos_id[idx], todos_z[idx]

    # ---------------------------------------------------------------- empresas
    def nuevas_empresas(
        self, z: np.ndarray, fechas_alta: pd.DatetimeIndex, ingreso_base: float, prob_grupo: float = 0.55
    ) -> np.ndarray:
        n = len(z)
        if n == 0:
            return np.array([], dtype=object)
        ids = self._ids(n)
        ubic = self._ubicacion(n)
        en_grupo = self.rng.random(n) < prob_grupo
        idx_grupo = self.rng.choice(len(self.grupos), size=n, p=self.grupos["peso"].to_numpy())
        grupo_id = np.where(en_grupo, self.grupos["grupo_economico_id"].to_numpy()[idx_grupo], None)
        sector = np.where(en_grupo, self.grupos["sector"].to_numpy()[idx_grupo], self.rng.choice(SECTORES, size=n))
        nombres = (
            self.rng.choice(PALABRAS_EMPRESA_1, n).astype(object)
            + " "
            + self.rng.choice(PALABRAS_EMPRESA_2, n).astype(object)
            + ", S.A."
        )
        nit = (
            self.rng.integers(1_000_000, 9_999_999, n).astype(str).astype(object)
            + "-"
            + self.rng.choice(list("0123456789K"), n).astype(object)
        )
        lote = pd.DataFrame(
            {
                "cliente_id": ids,
                "tipo_persona": "Jurídica",
                "nombre": nombres,
                "dpi": None,
                "nit": nit,
                "fecha_nacimiento": None,
                "departamento": ubic["departamento"].to_numpy(),
                "region": ubic["region"].to_numpy(),
                "agencia_codigo": ubic["agencia_codigo"].to_numpy(),
                "tipo_empleo": None,
                "ingreso_mensual": (ingreso_base * np.exp(self.rng.normal(-0.15 * z, 0.6))).round(2),
                "sector": sector,
                "grupo_economico_id": grupo_id,
                "es_pep": False,
                "fecha_alta": pd.DatetimeIndex(fechas_alta).date,
                "_z": z,
            }
        )
        self.lotes.append(lote)
        return ids

    def asignar_a_grupo(self, cliente_ids: np.ndarray, grupo_id: str) -> None:
        """Mueve empresas al grupo concentrado (calibra la concentración del top 20)."""
        sector = self.grupos.set_index("grupo_economico_id").loc[grupo_id, "sector"]
        for lote in self.lotes:
            mascara = lote["cliente_id"].isin(cliente_ids)
            lote.loc[mascara, "grupo_economico_id"] = grupo_id
            lote.loc[mascara, "sector"] = sector

    def tabla(self) -> pd.DataFrame:
        return pd.concat(self.lotes, ignore_index=True)
