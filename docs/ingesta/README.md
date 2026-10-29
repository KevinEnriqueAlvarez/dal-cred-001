# Ingesta Landing → Bronze · Actividad 3.2

> Carga los 98 archivos de Landing a Bronze tal como llegaron, sin perder una fila. En DuckDB, 5,07 millones de filas entran en un minuto. Cada fila queda trazada a su archivo, hash y corrida, y nada entra sin pasar cuatro controles.

## Qué hace

```
landing/ (98 CSV + _manifest.json)
      │
      ▼  por cada archivo del manifiesto
 ┌─────────────────────────────────────────────────────────────┐
 │ 1. ¿existe?  2. ¿hash = manifiesto?  3. ¿ya cargado igual?  │
 │ 4. ¿filas = manifiesto?  5. carga en una transacción        │
 └─────────────────────────────────────────────────────────────┘
      │                                   │
      ▼                                   ▼
 bronze.<fuente>                    audit.ingesta_archivo (una fila por archivo)
 (texto + 6 columnas meta_)         audit.run_log         (una fila por corrida)
```

| Paso | Control | Si falla | Dimensión de calidad |
| --- | --- | --- | --- |
| Declarado en el manifiesto | Todo CSV en Landing debe estar en `_manifest.json` | `rechazado_no_declarado` | Integridad |
| Existe en disco | El archivo declarado está presente | `rechazado_faltante` | Completitud |
| Hash SHA-256 | Coincide con el del manifiesto | `rechazado_hash` | Integridad (exactitud de la ingesta) |
| Idempotencia | Mismo archivo y mismo hash ya cargados | `omitido_sin_cambios`: no se duplica | — |
| Filas | Filas leídas = filas declaradas | `rechazado_filas` | Completitud |
| Versión corregida | Mismo nombre, hash distinto | `reemplazado`: se borran las filas viejas de ese archivo y se cargan las nuevas | — |
| Columnas nuevas | La fuente agregó columnas | Se agregan a la tabla y se registran en `columnas_nuevas` | Esquema (observabilidad) |
| SLA de llegada (06:00) | Hora de llegada del manifiesto | Se carga, pero se marca `sla_cumplido = falso` | Oportunidad |

Un archivo rechazado no detiene a los demás. La corrida termina con estado `con_rechazos` y código de salida 1, para que el orquestador no avance a Silver.

## Tablas que produce

| Tabla Bronze | Fuente | Filas (escala 1) |
| --- | --- | --- |
| `bronze.saldos` | `core_bancario/saldos/saldos_AAAAMM.csv` (22 archivos) | 2.399.902 |
| `bronze.pagos` | `core_bancario/pagos/pagos_AAAAMM.csv` (22) | 2.216.670 |
| `bronze.clientes` | `clientes/clientes_20261031.csv` | 190.078 |
| `bronze.prestamos` | `core_bancario/prestamos/prestamos_20261031.csv` | 164.560 |
| `bronze.solicitudes` | `originacion/solicitudes/solicitudes_AAAAMM.csv` (22) | 87.079 |
| `bronze.castigos`, `bronze.garantias` | `core_bancario/` | 10.904 · 4.672 |
| `bronze.mayor_contable` | `contabilidad/mayor/mayor_AAAAMM.csv` (22) | 132 |
| `bronze.grupos_economicos` | `clientes/grupos_economicos_20261031.csv` | 60 |
| `bronze.cat_*` (5 tablas) | `catalogos/` | 90 |

**Columnas de linaje en cada tabla Bronze**

| Columna | Contenido |
| --- | --- |
| `meta_archivo` | Ruta del archivo de origen, relativa a Landing |
| `meta_sha256` | Hash del archivo; prueba que la fila vino de ese archivo exacto |
| `meta_fila` | Número de fila dentro del archivo (1 = primera fila de datos) |
| `meta_fecha_llegada` | Hora en que el archivo llegó (según el manifiesto) |
| `meta_run_id` | Corrida que la cargó; se cruza con `audit.run_log` |
| `meta_cargado_en` | Hora de carga (hora de Guatemala) |

Todas las columnas de negocio se guardan como **texto**. Bronze es una copia fiel: la fecha imposible `2026-02-30` o el saldo `-12580.42` llegan intactos. Detectarlos y corregirlos es trabajo de Silver (actividad 3.3), y las pruebas lo verifican.

## Tablas de auditoría

- **`audit.run_log`** registra una fila por corrida:
  - motor y versión del código (`git_sha`);
  - inicio y fin;
  - estado;
  - archivos cargados, omitidos y rechazados;
  - filas de entrada y salida;
  - hash de entrada (el manifiesto) y de salida (la huella de lo cargado);
  - quién la ejecutó.
- **`audit.ingesta_archivo`** registra una fila por archivo y corrida: hashes, filas, llegada, SLA, estado y columnas nuevas.

Ambas son de solo inserción. Nunca se actualizan ni se borran: son la pista que lee el auditor.

## Cómo correrlo

```bash
python -m data_generator                                   # si aún no hay datos
python -m ingesta                                          # DuckDB en data/dal_cred_001.duckdb
python -m ingesta --motor sqlserver                        # SQL Server (ver guía)
```

- **SQL Server en tu equipo:** [guía paso a paso](guia_sqlserver_local.md).
- **Decisión de diseño:** [ADR-009](../adr/ADR-009-ingesta-bronze.md).

## Pruebas

`tests/test_ingesta.py` trae 12 pruebas, que corren sobre DuckDB siempre y sobre SQL Server 2022 en CI:

- carga completa con auditoría;
- idempotencia;
- archivo alterado;
- código de salida;
- versión corregida;
- archivo no declarado;
- filas distintas al manifiesto;
- columna nueva;
- llegada tardía;
- copia fiel;
- mapa de fuentes;
- motor por defecto.

## Resultado de referencia (escala 1, DuckDB)

| Corrida | Estado | Archivos | Filas | Tiempo |
| --- | --- | --- | --- | --- |
| Primera | exitosa | 98 cargados | 5.074.147 | 59 s |
| Segunda (sin cambios) | exitosa | 98 omitidos | 0 | 0,7 s |

Llegó fuera del SLA: `originacion/solicitudes/solicitudes_202610.csv` (06:42). Es el error de oportunidad inyectado a propósito.
