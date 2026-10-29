"""Adaptadores de base de datos: el mismo proceso de ingesta sobre DuckDB o SQL Server.

Cada motor implementa la misma interfaz pequeña (crear esquemas y tablas, agregar
columnas, borrar las filas de un archivo, insertar un lote, consultar y registrar
auditoría). El orquestador (cargador.py) no sabe qué motor usa: eso permite que
la corrida pública diaria use DuckDB y el ambiente local use SQL Server (ADR-003).

Tipos en Bronze: todas las columnas de negocio son texto ("copia fiel" de lo que
llegó); la conversión de tipos y la limpieza ocurren en Silver. Solo las
columnas de metadatos tienen tipo.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

# Definición de las tablas de auditoría (solo inserción). Tipos lógicos que cada
# motor traduce: texto(n), entero, fecha_hora, booleano.
TABLAS_AUDIT: dict[str, list[tuple[str, str]]] = {
    "run_log": [
        ("run_id", "texto(36)"),
        ("proceso", "texto(60)"),
        ("tarea", "texto(60)"),
        ("motor", "texto(20)"),
        ("git_sha", "texto(40)"),
        ("inicio", "fecha_hora"),
        ("fin", "fecha_hora"),
        ("estado", "texto(20)"),
        ("archivos_declarados", "entero"),
        ("archivos_cargados", "entero"),
        ("archivos_omitidos", "entero"),
        ("archivos_rechazados", "entero"),
        ("filas_entrada", "entero"),
        ("filas_salida", "entero"),
        ("hash_entrada", "texto(64)"),
        ("hash_salida", "texto(64)"),
        ("ejecutado_por", "texto(100)"),
        ("detalle", "texto(4000)"),
    ],
    "ingesta_archivo": [
        ("run_id", "texto(36)"),
        ("archivo", "texto(200)"),
        ("tabla_destino", "texto(60)"),
        ("sha256_manifiesto", "texto(64)"),
        ("sha256_calculado", "texto(64)"),
        ("filas_manifiesto", "entero"),
        ("filas_cargadas", "entero"),
        ("fecha_llegada", "fecha_hora"),
        ("sla_cumplido", "booleano"),
        ("estado", "texto(30)"),
        ("columnas_nuevas", "texto(1000)"),
        ("registrado_en", "fecha_hora"),
    ],
}

COLUMNAS_META_TIPOS = [
    ("meta_archivo", "texto(200)"),
    ("meta_sha256", "texto(64)"),
    ("meta_fila", "entero"),
    ("meta_fecha_llegada", "fecha_hora"),
    ("meta_run_id", "texto(36)"),
    ("meta_cargado_en", "fecha_hora"),
]
LARGO_TEXTO_NEGOCIO = 400


class Motor(ABC):
    """Interfaz común de los motores."""

    nombre: str

    # ----------------------------------------------------------- tipos y nombres
    @abstractmethod
    def tipo(self, logico: str) -> str: ...

    def q(self, identificador: str) -> str:
        """Identificador entre comillas (protege nombres de columnas de la fuente)."""
        return f'"{identificador}"'

    # ----------------------------------------------------------- ejecución
    @abstractmethod
    def ejecutar(self, sql: str, parametros: tuple | list = ()) -> None: ...

    @abstractmethod
    def consultar(self, sql: str, parametros: tuple | list = ()) -> list[tuple]: ...

    @abstractmethod
    def insertar_lote(self, esquema: str, tabla: str, df: pd.DataFrame) -> None: ...

    @abstractmethod
    def esquema_existe_sql(self, esquema: str) -> str: ...

    @abstractmethod
    def columnas(self, esquema: str, tabla: str) -> list[str] | None: ...

    @abstractmethod
    def confirmar(self) -> None: ...

    @abstractmethod
    def revertir(self) -> None: ...

    @abstractmethod
    def cerrar(self) -> None: ...

    # ----------------------------------------------------------- comunes
    def crear_esquemas(self) -> None:
        for esquema in ("bronze", "audit"):
            self.ejecutar(self.esquema_existe_sql(esquema))
        for tabla, cols in TABLAS_AUDIT.items():
            if self.columnas("audit", tabla) is None:
                self.crear_tabla("audit", tabla, cols)
        self.confirmar()

    def crear_tabla(self, esquema: str, tabla: str, columnas: list[tuple[str, str]]) -> None:
        defs = ", ".join(f"{self.q(c)} {self.tipo(t)}" for c, t in columnas)
        self.ejecutar(f"CREATE TABLE {esquema}.{self.q(tabla)} ({defs})")

    def asegurar_tabla_bronze(self, tabla: str, columnas_fuente: list[str]) -> list[str]:
        """Crea la tabla si no existe o agrega columnas nuevas (deriva de esquema).

        Devuelve la lista de columnas agregadas para registrarla en auditoría.
        """
        existentes = self.columnas("bronze", tabla)
        negocio = [(c, f"texto({LARGO_TEXTO_NEGOCIO})") for c in columnas_fuente]
        if existentes is None:
            self.crear_tabla("bronze", tabla, negocio + COLUMNAS_META_TIPOS)
            return []
        nuevas = [c for c in columnas_fuente if c not in existentes]
        for c in nuevas:
            self.ejecutar(
                f"ALTER TABLE bronze.{self.q(tabla)} ADD {self.q(c)} {self.tipo(f'texto({LARGO_TEXTO_NEGOCIO})')}"
            )
        return nuevas

    def borrar_archivo(self, tabla: str, archivo: str) -> None:
        self.ejecutar(f"DELETE FROM bronze.{self.q(tabla)} WHERE meta_archivo = ?", (archivo,))

    def registrar(self, tabla_audit: str, fila: dict) -> None:
        cols = [c for c, _ in TABLAS_AUDIT[tabla_audit]]
        marcas = ", ".join("?" for _ in cols)
        lista = ", ".join(self.q(c) for c in cols)
        self.ejecutar(
            f"INSERT INTO audit.{self.q(tabla_audit)} ({lista}) VALUES ({marcas})",
            tuple(fila.get(c) for c in cols),
        )

    def ultima_carga(self, archivo: str) -> str | None:
        """Hash del último archivo con el mismo nombre que se cargó con éxito."""
        filas = self.consultar(
            "SELECT sha256_calculado, registrado_en FROM audit.ingesta_archivo "
            "WHERE archivo = ? AND estado IN ('cargado', 'reemplazado') ORDER BY registrado_en DESC",
            (archivo,),
        )
        return filas[0][0] if filas else None


# =============================================================================
# DuckDB
# =============================================================================
class MotorDuckDB(Motor):
    nombre = "duckdb"

    def __init__(self, ruta: str):
        import duckdb

        self.con = duckdb.connect(ruta)
        self.con.execute("BEGIN TRANSACTION")

    def tipo(self, logico: str) -> str:
        if logico.startswith("texto"):
            return "VARCHAR"
        return {"entero": "BIGINT", "fecha_hora": "TIMESTAMP", "booleano": "BOOLEAN"}[logico]

    def ejecutar(self, sql, parametros=()):
        self.con.execute(sql, list(parametros))

    def consultar(self, sql, parametros=()):
        return self.con.execute(sql, list(parametros)).fetchall()

    def esquema_existe_sql(self, esquema):
        return f"CREATE SCHEMA IF NOT EXISTS {esquema}"

    def columnas(self, esquema, tabla):
        filas = self.consultar(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = ? AND table_name = ? "
            "ORDER BY ordinal_position",
            (esquema, tabla),
        )
        return [f[0] for f in filas] or None

    def insertar_lote(self, esquema, tabla, df):
        # pandas 3 usa el tipo "str" para texto; DuckDB recibe objetos de Python con None como nulo.
        df = df.astype(object).where(df.notna(), None)
        self.con.register("lote_ingesta", df)
        try:
            self.con.execute(f"INSERT INTO {esquema}.{self.q(tabla)} BY NAME SELECT * FROM lote_ingesta")
        finally:
            self.con.unregister("lote_ingesta")

    def confirmar(self):
        self.con.execute("COMMIT")
        self.con.execute("BEGIN TRANSACTION")

    def revertir(self):
        self.con.execute("ROLLBACK")
        self.con.execute("BEGIN TRANSACTION")

    def cerrar(self):
        self.con.execute("COMMIT")
        self.con.close()


# =============================================================================
# SQL Server
# =============================================================================
class MotorSQLServer(Motor):
    """SQL Server 2022 vía ODBC (pyodbc).

    La cadena de conexión sale del parámetro o de la variable de entorno
    DAL_SQLSERVER_CONN, por ejemplo (autenticación de Windows):

        DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=dal_cred_001;
        Trusted_Connection=yes;TrustServerCertificate=yes

    Nunca se escribe una contraseña en el código ni en el repositorio.
    """

    nombre = "sqlserver"
    # Lotes chicos: fast_executemany reserva memoria por fila según el ancho declarado.
    TAMANO_LOTE = 2_000

    def __init__(self, cadena: str | None = None):
        import pyodbc

        cadena = cadena or os.environ.get("DAL_SQLSERVER_CONN")
        if not cadena:
            raise ValueError("Falta la cadena de conexión: use --conexion o la variable DAL_SQLSERVER_CONN")
        self.con = pyodbc.connect(cadena, autocommit=False)
        self.cur = self.con.cursor()
        self.cur.fast_executemany = True

    def tipo(self, logico: str) -> str:
        if logico.startswith("texto("):
            return f"NVARCHAR({logico[6:-1]})"
        return {"entero": "BIGINT", "fecha_hora": "DATETIME2(3)", "booleano": "BIT"}[logico]

    def q(self, identificador: str) -> str:
        return f"[{identificador}]"

    def ejecutar(self, sql, parametros=()):
        self.cur.execute(sql, *parametros) if parametros else self.cur.execute(sql)

    def consultar(self, sql, parametros=()):
        self.ejecutar(sql, parametros)
        return [tuple(f) for f in self.cur.fetchall()]

    def esquema_existe_sql(self, esquema):
        return f"IF SCHEMA_ID('{esquema}') IS NULL EXEC('CREATE SCHEMA {esquema}')"

    def columnas(self, esquema, tabla):
        filas = self.consultar(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            (esquema, tabla),
        )
        return [f[0] for f in filas] or None

    def insertar_lote(self, esquema, tabla, df):
        cols = list(df.columns)
        sql = (
            f"INSERT INTO {esquema}.{self.q(tabla)} ({', '.join(self.q(c) for c in cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})"
        )
        import pyodbc

        # Tipos explícitos por columna: evita que pyodbc los adivine con la primera fila (que puede ser nula).
        tamanos = []
        for c in cols:
            if c == "meta_fila":
                tamanos.append((pyodbc.SQL_BIGINT, 0, 0))
            elif c in ("meta_fecha_llegada", "meta_cargado_en"):
                tamanos.append((pyodbc.SQL_TYPE_TIMESTAMP, 23, 3))
            elif c == "meta_sha256":
                tamanos.append((pyodbc.SQL_WVARCHAR, 64, 0))
            else:
                tamanos.append((pyodbc.SQL_WVARCHAR, LARGO_TEXTO_NEGOCIO, 0))
        self.cur.setinputsizes(tamanos)
        valores = df.astype(object).where(df.notna(), None).values.tolist()
        for i in range(0, len(valores), self.TAMANO_LOTE):
            self.cur.executemany(sql, valores[i : i + self.TAMANO_LOTE])

    def confirmar(self):
        self.con.commit()

    def revertir(self):
        self.con.rollback()

    def cerrar(self):
        self.con.commit()
        self.con.close()


def abrir(motor: str, destino: str | None = None, conexion: str | None = None) -> Motor:
    if motor == "duckdb":
        return MotorDuckDB(destino or "data/dal_cred_001.duckdb")
    if motor == "sqlserver":
        return MotorSQLServer(conexion)
    raise ValueError(f"Motor desconocido: {motor} (use duckdb o sqlserver)")


def ahora() -> datetime:
    """Hora de Guatemala (UTC-6) sin zona, en milisegundos: igual en local y en GitHub Actions."""
    n = datetime.now(ZoneInfo("America/Guatemala")).replace(tzinfo=None)
    return n.replace(microsecond=n.microsecond // 1000 * 1000)
