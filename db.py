"""
db.py -- Блок 1b: слой хранения. Единственное место, где упоминается
конкретная база данных -- extractors/metrics/dashboard знают только про
"движок" (engine) и обычный SQL, а не про то, SQLite это или Postgres.

По умолчанию: локальный файл SQLite (el_molino.db) -- ничего настраивать
не надо, работает сразу.

Чтобы переключиться на облачную базу (Postgres -- например Supabase или
Neon, у обоих есть бесплатный план): создай в этой же папке файл `.env`
с одной строкой

    DATABASE_URL=postgresql://имя:пароль@адрес-хоста/имя_базы

...и всё -- при следующем запуске meню/дашборда данные пойдут уже в
облако, а не в локальный файл. Ни extractors/wansoft.py, ни metrics.py,
ни dashboard.py трогать не надо -- они работают через функции этого
модуля и не знают, откуда на самом деле берётся SQL-соединение. Это и
есть та самая "адаптация под любую базу", о которой шла речь в начале:
поменялся только db.py.

Проверено (в этом разговоре) на двух движках: SQLite и настоящем
Postgres 16 -- одни и те же функции, один и тот же результат.
"""

import datetime
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from sqlalchemy import (
    Column, DateTime, Float, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine, delete, select, text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

HERE = Path(__file__).resolve().parent
DEFAULT_DB_PATH = "el_molino.db"

load_dotenv(HERE / ".env")

metadata = MetaData()

# Одна строка = одна проданная позиция (после фильтров Acción="Venta" y
# sin modificador). Классификация "это кофе или нет" здесь НЕ хранится --
# она считается на лету в metrics.py по списку coffee_keywords, чтобы
# правку списка не нужно было "переигрывать" по старым данным.
sales_lines = Table(
    "sales_lines", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sucursal", String, nullable=False),
    Column("fecha", String, nullable=False),          # ISO 'YYYY-MM-DD'
    Column("hora_cierre", String),                    # ISO 'YYYY-MM-DDTHH:MM:SS' (puede ser NULL en datos viejos)
    Column("movimiento_pdv", Integer),                 # id único por CHECK (no por línea) -- para contar "ventas" y ticket promedio (puede ser NULL en datos viejos)
    Column("anio", Integer, nullable=False),
    Column("accion", String, nullable=False),
    Column("es_modificador", String, nullable=False),
    Column("tipo_grupo", String),
    Column("grupo", String),
    Column("platillo", String),
    Column("cantidad", Float, nullable=False),
    Column("precio_unit_con_mod", Float, nullable=False),
    Column("importe", Float, nullable=False),
    Column("archivo_origen", String, nullable=False),
    Column("fila_origen", Integer, nullable=False),
    Column("cargado_en", String, nullable=False),
    UniqueConstraint("archivo_origen", "fila_origen", name="uq_sales_lines_archivo_fila"),
)

# Список слов, по которым позиция считается "кофе" -- редактируется
# вручную через страницу "Настройки" в дашборде, без правки кода.
coffee_keywords = Table(
    "coffee_keywords", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("palabra", String, nullable=False, unique=True),
    Column("activo", Integer, nullable=False, default=1),  # 1/0 вместо bool -- проще в sqlite
)

DEFAULT_COFFEE_KEYWORDS = [
    "AMERICANO", "ESPRESSO", "CAPUCCINO", "CAPUCHINO", "LATTE",
    "FLAT WHITE", "MOCHA", "RAF", "MOKA", "MACCHIATO", "CORTADO",
]


def get_engine(db_path: str = DEFAULT_DB_PATH) -> Engine:
    """DATABASE_URL в .env (или в переменных окружения) -> облачная
    (или любая другая) база. Без неё -- локальный файл SQLite рядом."""
    url = os.getenv("DATABASE_URL")
    if not url:
        url = f"sqlite:///{db_path}"
    engine = create_engine(url, future=True)
    metadata.create_all(engine)
    _migrate_schema(engine)
    _seed_coffee_keywords(engine)
    return engine


def _migrate_schema(engine: Engine) -> None:
    """Добавляет в уже существующую таблицу колонки, которых там не было в
    старой версии программы (не теряя уже загруженные данные). И SQLite, и
    Postgres понимают простой 'ALTER TABLE ... ADD COLUMN'."""
    inspector = sa_inspect(engine)
    if "sales_lines" not in inspector.get_table_names():
        return  # metadata.create_all() уже создал таблицу целиком, мигрировать нечего
    existentes = {c["name"] for c in inspector.get_columns("sales_lines")}
    faltantes = [c for c in sales_lines.columns if c.name not in existentes]
    if not faltantes:
        return
    with engine.begin() as conn:
        for column in faltantes:
            tipo_sql = column.type.compile(dialect=engine.dialect)
            conn.execute(text(f'ALTER TABLE sales_lines ADD COLUMN "{column.name}" {tipo_sql}'))


def _seed_coffee_keywords(engine: Engine) -> None:
    with engine.begin() as conn:
        count = conn.execute(select(coffee_keywords.c.id)).first()
        if count is None:
            conn.execute(coffee_keywords.insert(), [
                {"palabra": kw, "activo": 1} for kw in DEFAULT_COFFEE_KEYWORDS
            ])


def _chunked(rows: list[dict], size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _insert_or_update(engine: Engine, table: Table, rows: list[dict]):
    """INSERT que, si el renglón ya existe (misma restricción UNIQUE),
    ACTUALIZA sus columnas en vez de ignorarlo -- funciona igual en SQLite
    y en Postgres, cada uno con su propia sintaxis de 'on conflict'.

    Por qué actualizar y no solo ignorar: así, cuando el programa aprende a
    guardar una columna nueva (por ejemplo 'hora_cierre'), basta con
    recargar los mismos archivos -- ya cargados antes -- y esa columna se
    rellena también en los renglones viejos, sin duplicar nada.

    En lotes chicos (no todo de una vez): SQLite tiene un límite de
    variables por sentencia (~999 en muchas instalaciones) -- con
    ~15 columnas por renglón, un archivo de miles de líneas revienta ese
    límite si se manda en una sola sentencia."""
    batch_size = 200
    clave_unica = ["archivo_origen", "fila_origen"]
    columnas_actualizables = [
        c.name for c in table.columns if c.name not in clave_unica and c.name != "id"
    ]
    insert_fn = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    with engine.begin() as conn:
        for batch in _chunked(rows, batch_size):
            stmt = insert_fn(table).values(batch)
            actualizar = {c: getattr(stmt.excluded, c) for c in columnas_actualizables}
            stmt = stmt.on_conflict_do_update(index_elements=clave_unica, set_=actualizar)
            conn.execute(stmt)


def insert_lines(engine: Engine, rows: Iterable[dict]) -> tuple[int, int]:
    """Inserta renglones normalizados (ver extractors/wansoft.py).
    Devuelve (intentados, insertados_de_verdad -- los que ya existían se
    actualizan, no cuentan como 'nuevos')."""
    rows = list(rows)
    if not rows:
        return 0, 0
    before = _count(engine)
    _insert_or_update(engine, sales_lines, rows)
    after = _count(engine)
    return len(rows), after - before


def _count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM sales_lines")).scalar_one()


def resumen_carga(engine: Engine) -> list[dict]:
    sql = text("""
        SELECT sucursal,
               COUNT(*)      AS renglones,
               MIN(fecha)    AS desde,
               MAX(fecha)    AS hasta,
               SUM(importe)  AS ventas_totales
        FROM sales_lines
        GROUP BY sucursal
        ORDER BY sucursal
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql).mappings()]


def get_coffee_keywords(engine: Engine, solo_activas: bool = True) -> list[dict]:
    sql = select(coffee_keywords).order_by(coffee_keywords.c.palabra)
    if solo_activas:
        sql = sql.where(coffee_keywords.c.activo == 1)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql).mappings()]


def replace_coffee_keywords(engine: Engine, palabras_activas: list[str]) -> None:
    """Reemplaza la lista completa -- así la usa el editor de la página
    'Настройки' del dashboard (recibe la tabla ya editada por el
    usuario)."""
    palabras_activas = sorted({p.strip().upper() for p in palabras_activas if p.strip()})
    with engine.begin() as conn:
        conn.execute(delete(coffee_keywords))
        if palabras_activas:
            conn.execute(coffee_keywords.insert(), [
                {"palabra": p, "activo": 1} for p in palabras_activas
            ])
