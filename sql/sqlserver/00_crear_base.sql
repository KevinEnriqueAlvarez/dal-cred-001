/* =============================================================================
   DAL-CRED-001 · Creación de la base de datos en SQL Server 2022
   -----------------------------------------------------------------------------
   Se corre una sola vez, en SQL Server Management Studio (SSMS), conectado a la
   instancia local con autenticación de Windows.

   Crea la base dal_cred_001 y los esquemas de la arquitectura Medallion:
     bronze  copia fiel de Landing con metadatos de linaje (actividad 3.2)
     silver  datos limpios y conformados (actividad 3.3)
     gold    hechos, dimensiones y marts regulatorios (actividad 3.4)
     audit   pista de auditoría de solo inserción (run_log, ingesta_archivo...)

   Las tablas de bronze y audit las crea el proceso de ingesta al primer uso.
   ========================================================================== */

IF DB_ID('dal_cred_001') IS NULL
BEGIN
    CREATE DATABASE dal_cred_001;
END
GO

USE dal_cred_001;
GO

IF SCHEMA_ID('bronze') IS NULL EXEC('CREATE SCHEMA bronze');
IF SCHEMA_ID('silver') IS NULL EXEC('CREATE SCHEMA silver');
IF SCHEMA_ID('gold')   IS NULL EXEC('CREATE SCHEMA gold');
IF SCHEMA_ID('audit')  IS NULL EXEC('CREATE SCHEMA audit');
GO

/* Verificación: deben aparecer los cuatro esquemas. */
SELECT name AS esquema
FROM sys.schemas
WHERE name IN ('bronze', 'silver', 'gold', 'audit')
ORDER BY name;
GO
