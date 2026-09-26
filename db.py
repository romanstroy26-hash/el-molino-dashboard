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
    Column, DateTime, Float, Index, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine, delete, func, select, text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine

HERE = Path(__file__).resolve().parent
DEFAULT_DB_PATH = "el_molino.db"

load_dotenv(HERE / ".env")

metadata = MetaData()

# Одна строка = одна проданная позиция (после фильтров Acción="Venta" y
# sin modificador). Классификация "это кофе или нет" здесь НЕ хранится --
# она считается на лету в metrics.py по списку coffee_keywords, чтобы
# правку списка не нужно было "переигрывать" по старым данным.
#
# ЕДИНИЦА ЗАГРУЗКИ -- ЧЕК (movimiento_pdv), а не файл. Подробно см.
# insert_lines ниже: выгрузки Wansoft приходят перекрывающимися
# диапазонами дат и с разными именами файлов, поэтому "этот файл уже
# грузили" -- ненадёжный признак, а "этот чек уже в базе" -- надёжный.
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

# Индексы. Без них любой вопрос к базе ("что было 18 сентября в этой
# точке?") читает ВСЮ таблицу целиком -- на 300 тысячах строк это ещё
# терпимо локально, но на облачной базе и на паре лет истории уже нет.
#
#  - (fecha, sucursal) -- выборки по дню/диапазону, и когда точка не
#    указана (все точки сразу), и когда указана: первый столбец индекса
#    работает сам по себе.
#  - (sucursal, fecha) -- обратный порядок для запросов, которые фильтруют
#    ТОЛЬКО по точке и читают всю её историю (так делает прогноз по часам).
#  - (movimiento_pdv) -- поиск чека: по нему работает дедупликация при
#    загрузке (см. insert_lines), иначе каждая загрузка снова читала бы
#    таблицу целиком.
INDICES = (
    Index("ix_sales_lines_fecha_sucursal", sales_lines.c.fecha, sales_lines.c.sucursal),
    Index("ix_sales_lines_sucursal_fecha", sales_lines.c.sucursal, sales_lines.c.fecha),
    Index("ix_sales_lines_movimiento", sales_lines.c.movimiento_pdv),
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
    # pool_pre_ping -- перед тем как отдать соединение из пула, тихо
    # проверяет его коротким запросом. Без этого долго живущий процесс
    # (дашборд, который никто не закрывает по многу часов, или
    # vigilar.py, который вообще не останавливается) рано или поздно
    # получает соединение, которое незаметно оборвал облачный пулер
    # (Supabase Session pooler закрывает простаивающие соединения сам) --
    # и падает с невнятной сетевой ошибкой на ровном месте. На SQLite
    # это же самое просто ничего не стоит.
    engine = create_engine(url, future=True, pool_pre_ping=True)
    metadata.create_all(engine)
    _migrate_schema(engine)
    _crear_indices(engine)
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


def _crear_indices(engine: Engine) -> None:
    """Досоздаёт индексы на УЖЕ существующей таблице. metadata.create_all()
    сюда не годится: увидев, что таблица есть, он пропускает её целиком
    вместе с индексами -- поэтому на базе, созданной прошлой версией
    программы, индексы так и не появились бы. checkfirst=True -- значит
    "создать, если такого ещё нет", повторный запуск ничего не ломает."""
    for indice in INDICES:
        indice.create(bind=engine, checkfirst=True)


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


# Лотами, а не всё одним запросом: у SQLite есть предел на количество
# значений в одной команде (~999 во многих сборках) -- при ~15 колонках на
# строку файл в несколько тысяч строк этот предел пробивает.
_TAMANO_LOTE_FILAS = 200
_TAMANO_LOTE_CLAVES = 500


def insert_lines(engine: Engine, rows: Iterable[dict]) -> dict:
    """Загружает нормализованные строки (см. extractors/wansoft.py).

    ЕДИНИЦА ЗАГРУЗКИ -- ЧЕК, а не файл. Для каждого чека из входящих данных
    сначала удаляются все его строки, уже лежащие в базе, и только потом
    вставляются новые. Звучит странно ("зачем удалять то, что и так
    правильное?"), но именно это делает загрузку безопасной:

      - Wansoft выгружает ДИАПАЗОНАМИ дат, и диапазоны перекрываются:
        файл за 01.06-01.08 и файл за 01.08-15.09 содержат ОДИН И ТОТ ЖЕ
        первый августа. Раньше признаком "это уже грузили" было имя файла
        + номер строки -- у разных файлов они разные, поэтому оба августа
        попадали в базу, и выручка за такой день удваивалась (количество
        чеков при этом оставалось верным -- оно считается по уникальным
        номерам -- так что в глаза это не бросалось: выглядело как
        "средний чек вырос вдвое").
      - Номер чека (movimiento_pdv) сквозной и не повторяется ни между
        точками, ни между днями -- проверено на всей базе. Поэтому "этот
        чек уже есть" -- надёжный признак, а "этот файл уже грузили" -- нет.
      - Порядок загрузки перестаёт иметь значение. Если один файл содержит
        день целиком, а другой -- только его начало (выгрузка сделана
        днём, магазин ещё торговал), то загрузка частичного файла ПОСЛЕ
        полного затрёт только те чеки, которые в нём есть, а остальные
        чеки дня останутся на месте. День не теряется.
      - Побочная польза: перезагрузка старых файлов лечит уже задвоенные
        дни сама -- обе копии чека удаляются, вставляется одна.

    Всё это -- одной транзакцией на файл: если что-то упадёт посередине,
    база останется в том виде, в каком была до загрузки (а не с удалённым,
    но не вставленным днём).

    Возвращает словарь со сводкой -- её печатают menu.py и etl_load.py."""
    rows = list(rows)
    if not rows:
        return {"lineas": 0, "tickets": 0, "tickets_ya_estaban": 0, "lineas_reemplazadas": 0}

    tickets = sorted({r["movimiento_pdv"] for r in rows if r["movimiento_pdv"] is not None})
    archivos = sorted({r["archivo_origen"] for r in rows})

    tickets_ya_estaban = 0
    lineas_reemplazadas = 0

    with engine.begin() as conn:
        for lote in _chunked(tickets, _TAMANO_LOTE_CLAVES):
            condicion = sales_lines.c.movimiento_pdv.in_(lote)
            tickets_ya_estaban += conn.execute(
                select(func.count(func.distinct(sales_lines.c.movimiento_pdv))).where(condicion)
            ).scalar_one()
            lineas_reemplazadas += conn.execute(delete(sales_lines).where(condicion)).rowcount or 0

        # Подстраховка для строк БЕЗ номера чека (в текущих выгрузках таких
        # нет, но пустая ячейка в отчёте -- дело возможное): их по чеку не
        # опознать, поэтому для них признаком остаётся файл -- иначе
        # повторная загрузка того же файла упёрлась бы в UNIQUE(archivo,
        # fila).
        for archivo in archivos:
            lineas_reemplazadas += conn.execute(
                delete(sales_lines).where(sales_lines.c.archivo_origen == archivo)
            ).rowcount or 0

        for lote in _chunked(rows, _TAMANO_LOTE_FILAS):
            conn.execute(sales_lines.insert(), lote)

    return {
        "lineas": len(rows),
        "tickets": len(tickets),
        "tickets_ya_estaban": tickets_ya_estaban,
        "lineas_reemplazadas": lineas_reemplazadas,
    }


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
