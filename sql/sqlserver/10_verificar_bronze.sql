/* =============================================================================
   DAL-CRED-001 · Verificación de la carga a Bronze (evidencia de la actividad 3.2)
   Correr en SSMS después de: python -m ingesta --motor sqlserver
   ========================================================================== */
USE dal_cred_001;
GO

/* 1. Última corrida: debe decir "exitosa", 98 archivos y ~5,07 millones de filas. */
SELECT TOP (3)
    run_id, motor, estado, archivos_declarados, archivos_cargados, archivos_omitidos,
    archivos_rechazados, filas_salida, inicio, fin,
    DATEDIFF(SECOND, inicio, fin) AS segundos, git_sha, ejecutado_por
FROM audit.run_log
ORDER BY inicio DESC;

/* 2. Filas por tabla Bronze contra lo declarado en el manifiesto. */
SELECT
    i.tabla_destino,
    COUNT(*)              AS archivos,
    SUM(i.filas_manifiesto) AS filas_declaradas,
    SUM(i.filas_cargadas)   AS filas_cargadas,
    CASE WHEN SUM(i.filas_manifiesto) = SUM(i.filas_cargadas) THEN 'Cuadra' ELSE 'REVISAR' END AS control
FROM audit.ingesta_archivo AS i
WHERE i.estado IN ('cargado', 'reemplazado')
GROUP BY i.tabla_destino
ORDER BY filas_cargadas DESC;

/* 3. Archivos fuera del SLA de llegada (06:00): se espera solicitudes_202610.csv. */
SELECT archivo, fecha_llegada, sla_cumplido, estado
FROM audit.ingesta_archivo
WHERE sla_cumplido = 0 AND estado IN ('cargado', 'reemplazado');

/* 4. Muestra del linaje: cada fila sabe de qué archivo, hash y corrida vino. */
SELECT TOP (5) prestamo_id, periodo, saldo_capital, dias_atraso,
       meta_archivo, LEFT(meta_sha256, 12) + '…' AS meta_sha256, meta_fila, meta_run_id, meta_cargado_en
FROM bronze.saldos
ORDER BY meta_archivo, meta_fila;
GO
