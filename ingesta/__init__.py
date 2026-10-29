"""Ingesta Landing -> Bronze de DAL-CRED-001 (actividad 3.2).

Carga cada archivo de la zona Landing tal como llegó ("copia fiel": todas las
columnas como texto) a una tabla del esquema bronze, y le agrega metadatos de
linaje: archivo de origen, hash SHA-256, número de fila, hora de llegada y la
corrida (run_id) que lo cargó.

Controles que aplica antes de cargar:
- El archivo está declarado en el manifiesto (_manifest.json).
- Su hash SHA-256 coincide con el del manifiesto (integridad de la ingesta).
- Las filas cargadas coinciden con las declaradas (completitud).
- La hora de llegada respeta el SLA (oportunidad; si no, se marca, no se rechaza).

Cada corrida queda en audit.run_log y cada archivo en audit.ingesta_archivo,
ambas tablas de solo inserción.

Funciona sobre dos motores con el mismo código (ADR-003):
- DuckDB: corrida pública diaria en GitHub Actions, sin instalación.
- SQL Server 2022: ambiente local de desarrollo y pruebas.

Uso:
    python -m ingesta --landing data/landing --motor duckdb --destino data/dal_cred_001.duckdb
    python -m ingesta --landing data/landing --motor sqlserver   # usa DAL_SQLSERVER_CONN
"""

__version__ = "1.0.0"
