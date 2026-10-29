"""Mapa de archivos de Landing a tablas de Bronze.

Cada patrón de ruta (relativo a landing/) define la tabla destino. Los archivos
mensuales de una misma fuente (saldos_202501.csv, saldos_202502.csv, ...) van a
la misma tabla; la columna meta_archivo distingue de qué archivo vino cada fila.
"""

from __future__ import annotations

import fnmatch

FUENTES: dict[str, str] = {
    "core_bancario/saldos/saldos_*.csv": "saldos",
    "core_bancario/pagos/pagos_*.csv": "pagos",
    "core_bancario/prestamos/prestamos_*.csv": "prestamos",
    "core_bancario/garantias/garantias_*.csv": "garantias",
    "core_bancario/castigos/castigos_*.csv": "castigos",
    "originacion/solicitudes/solicitudes_*.csv": "solicitudes",
    "clientes/clientes_*.csv": "clientes",
    "clientes/grupos_economicos_*.csv": "grupos_economicos",
    "contabilidad/mayor/mayor_*.csv": "mayor_contable",
    "catalogos/productos.csv": "cat_productos",
    "catalogos/agencias.csv": "cat_agencias",
    "catalogos/canales.csv": "cat_canales",
    "catalogos/analistas.csv": "cat_analistas",
    "catalogos/politicas.csv": "cat_politicas",
}

# Columnas de linaje que Bronze agrega a cada fila. El prefijo meta_ las separa
# de las columnas de negocio y evita choques de nombre con la fuente.
COLUMNAS_META = [
    "meta_archivo",
    "meta_sha256",
    "meta_fila",
    "meta_fecha_llegada",
    "meta_run_id",
    "meta_cargado_en",
]


def tabla_destino(archivo: str) -> str | None:
    """Devuelve la tabla Bronze de un archivo, o None si no corresponde a ninguna fuente."""
    for patron, tabla in FUENTES.items():
        if fnmatch.fnmatch(archivo, patron):
            return tabla
    return None
