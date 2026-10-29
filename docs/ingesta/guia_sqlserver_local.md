# Guía · Correr la ingesta en tu SQL Server local (Windows)

> Diez pasos, de clonar el repositorio a ver los 5 millones de filas en SSMS. La primera vez toma unos 30 minutos; después, una sola línea.

## Antes de empezar: qué necesitas

| Herramienta | Cómo comprobar que la tienes (PowerShell) | Si no la tienes |
| --- | --- | --- |
| SQL Server 2022 (Developer o Express) | Abre SSMS y conéctate a `localhost` (o `localhost\SQLEXPRESS`) | [Descargar SQL Server](https://www.microsoft.com/es-es/sql-server/sql-server-downloads) |
| SQL Server Management Studio (SSMS) | Está en el menú Inicio | [Descargar SSMS](https://learn.microsoft.com/es-es/ssms/install/install) |
| Python 3.11 o superior | `python --version` | [python.org](https://www.python.org/downloads/): marca "Add python.exe to PATH" |
| Git | `git --version` | [git-scm.com](https://git-scm.com/download/win) |
| ODBC Driver 18 for SQL Server | `Get-OdbcDriver -Name "ODBC Driver 18*"` | [Descargar ODBC Driver 18](https://learn.microsoft.com/es-es/sql/connect/odbc/download-odbc-driver-for-sql-server) |

## Pasos

**1. Clona el repositorio** (PowerShell, en la carpeta donde guardes tus proyectos):

```powershell
git clone https://github.com/KevinEnriqueAlvarez/dal-cred-001.git
cd dal-cred-001
```

**2. Crea un entorno virtual e instala las dependencias.** El entorno aísla las librerías del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,sqlserver]"
```

Si PowerShell bloquea el script de activación, ejecuta una vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y repite.

**3. Comprueba que todo funciona:**

```powershell
pytest
```

Debe terminar con `26 passed`.

**4. Crea la base en SQL Server.** En SSMS abre `sql/sqlserver/00_crear_base.sql` y ejecútalo con **F5**. Al final debe mostrar los esquemas `audit`, `bronze`, `gold` y `silver`.

**5. Genera los datos** (unos 2 minutos, 344 MB en la carpeta `data`, que Git ignora):

```powershell
python -m data_generator
```

**6. Configura la conexión.** Tu instancia usa autenticación de Windows, así que no hay contraseña. Usa la línea que corresponda a tu instancia:

```powershell
# Instancia predeterminada (Developer):
$env:DAL_SQLSERVER_CONN = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=dal_cred_001;Trusted_Connection=yes;TrustServerCertificate=yes"

# Instancia con nombre (Express):
$env:DAL_SQLSERVER_CONN = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=dal_cred_001;Trusted_Connection=yes;TrustServerCertificate=yes"
```

La variable vive solo en esa ventana de PowerShell; nunca queda guardada en el repositorio.

**7. Carga Bronze en SQL Server** (entre 10 y 30 minutos según tu equipo):

```powershell
python -m ingesta --motor sqlserver
```

Al terminar debe decir `estado exitosa`, `cargado 98` y `filas cargadas a Bronze 5,074,147`.

**8. Prueba la idempotencia.** Corre el mismo comando otra vez. Debe terminar en segundos con `omitido_sin_cambios 98`.

**9. Verifica en SSMS.** Abre y ejecuta `sql/sqlserver/10_verificar_bronze.sql`. Muestra:
- las dos corridas en `audit.run_log`;
- el cuadre de filas por tabla, con todas en **Cuadra**;
- el archivo que llegó tarde;
- una muestra de las filas con su linaje.

**10. Toma las capturas de evidencia:**
- **A.** La consola de PowerShell con el resultado de los pasos 7 y 8.
- **B.** El resultado del script de verificación en SSMS: las cuatro consultas.

## Si algo falla

| Mensaje | Causa probable | Solución |
| --- | --- | --- |
| `Data source name not found` | Falta el ODBC Driver 18 | Instálalo (tabla de arriba) |
| `Login failed` o `Cannot open database` | La base no existe o el nombre de la instancia no es el correcto | Repite el paso 4; revisa `SERVER=` en el paso 6 |
| `SSL Provider: certificate chain` | El driver exige certificado | Confirma que la cadena incluye `TrustServerCertificate=yes` |
| `Falta la cadena de conexión` | No se definió la variable, o se abrió otra ventana | Repite el paso 6 en la misma ventana |
| `estado con_rechazos` | Un archivo no cuadra con el manifiesto (por ejemplo, alguien lo editó) | Regenera los datos (paso 5) y vuelve a cargar |
