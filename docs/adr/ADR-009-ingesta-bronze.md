# ADR-009 · Ingesta a Bronze como copia fiel en texto, idempotente por hash y con dos motores

- **Estado:** Propuesta (actividad 3.2; se aprueba con el merge del pull request)
- **Fecha:** 28-oct-2026
- **Decide:** Arquitecto e ingeniero de datos · **Aprueba:** Dueño de producto

## Contexto

Bronze es la primera capa con la que trabaja el banco, y tiene que demostrar dos cosas:

- **Lo que entró es exactamente lo que llegó.** Es la base de la exactitud de BCBS 239 y del control OB-03 del SIRC.
- **Volver a correr no duplica datos.** Si un archivo llega corregido, la versión nueva reemplaza a la anterior sin dejar basura.

Además, ADR-003 exige que el mismo proceso corra sobre SQL Server (local) y DuckDB (corrida pública diaria).

## Decisión

1. **Todas las columnas de negocio como texto en Bronze.** Una fecha inválida o un saldo negativo se conservan tal cual; la tipificación y las reglas se aplican en Silver con pruebas dbt. Si Bronze tipificara, un error de formato rompería la carga o se perdería en silencio.
2. **Seis columnas de linaje (`meta_`) por fila:** archivo, hash, número de fila, llegada, corrida y hora de carga.
3. **Idempotencia por archivo y hash:**
   - mismo hash → `omitido_sin_cambios`;
   - mismo archivo con hash distinto → `reemplazado`, borrando primero las filas viejas de ese archivo;
   - el archivo y su registro de auditoría entran en una sola transacción.
4. **Manifiesto obligatorio.** Ningún archivo entra a Bronze sin estar declarado y sin que su hash y sus filas coincidan.
5. **Patrón de adaptador** (`ingesta/motores.py`): una interfaz con dos implementaciones, DuckDB y SQL Server (pyodbc con `fast_executemany` y tipos declarados).
6. **CI con un SQL Server 2022 real** en un contenedor, con contraseña aleatoria por corrida. Así ningún secreto vive en el repositorio.

## Alternativas descartadas

| Alternativa | Por qué se descartó |
| --- | --- |
| Tipificar al cargar (fechas como DATE, montos como DECIMAL) | Un valor inválido rompería la carga o se perdería; Bronze dejaría de ser evidencia de lo recibido |
| `BULK INSERT` de SQL Server | Requiere que el servicio de SQL Server lea la carpeta del usuario (permisos en Windows) y no existe en DuckDB |
| dbt seeds o `read_csv` de dbt para cargar | No registra hash, llegada ni idempotencia por archivo; los seeds no son para volúmenes de millones |
| Truncar y recargar todo en cada corrida | No es idempotente por archivo, borra la evidencia de qué versión entró y en SQL Server toma 10 o más minutos cada vez |
| Solo un motor | Incumple ADR-003: sin DuckDB no hay corrida pública diaria; sin SQL Server no se demuestra el motor que usa la banca |

## Consecuencias

- **Positivas:**
  - Cualquier fila de Gold se podrá rastrear hasta el archivo y el byte de origen (auditoría simulada de G4: 5 de 5 cifras rastreables).
  - Volver a correr es seguro.
  - El mismo código se prueba en los dos motores.
- **Negativas:**
  - Bronze ocupa más espacio, porque guarda texto y metadatos por fila.
  - Silver debe tipificar cada columna.
  - En SQL Server la primera carga completa toma entre 10 y 30 minutos.
