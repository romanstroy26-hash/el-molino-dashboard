"""
metrics.py -- Блок 4: считает показатели из базы (db.py), не зная, ни
откуда данные туда попали (Wansoft или что-то другое), ни какой движок
базы данных сейчас используется (SQLite или Postgres -- через db.py).

Здесь же живёт классификация "кофе / не кофе": она читает список слов из
таблицы coffee_keywords (правится вручную на странице "Настройки" в
дашборде) и группу позиции (tipo_grupo). Ограничение по группам
(CAFETERIA/FRAPPES) остаётся в коде -- это структурное правило (в каких
разделах меню вообще имеет смысл искать кофе), а вот сам список слов --
дело вкуса и меню, поэтому он в базе, а не в коде.
"""

import datetime as dt
from collections import defaultdict

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

import tiempo
from db import get_coffee_keywords

CAFETERIA_TIPOS = {"CAFETERIA", "FRAPPES"}

# Grupos que caen en "Остальные напитки" cuando no son café ni frappé.
# REFRESCOS (refrescos embotellados) es volumen mínimo pero es bebida --
# antes quedaba fuera de "Напитки" por completo; ahora se suma aquí para
# que "Напитки" cubra TODA bebida del menú, no solo CAFETERIA/FRAPPES.
OTRAS_BEBIDAS_TIPOS = {"CAFETERIA", "REFRESCOS"}

# Posiciones de PANADERIA que en realidad son empaque (bolsas), no
# producto -- se venden a $0 y no consumen tiempo de horneado/decoración
# de nadie. Cuentan como PANADERIA en tipo_grupo pero deben quedar FUERA
# de cualquier análisis de esa categoría (unidades reales, pronóstico,
# top de posiciones, personal por hora) -- si no, inflan las unidades sin
# representar trabajo real.
PANADERIA_EXCLUIR_SQL = " AND platillo NOT LIKE 'BOLSA%'"

# "Сегодня" здесь НИКОГДА не берётся из часов компьютера -- только из
# tiempo.hoy(), то есть по времени Сан-Луис-Потоси. Почему так и что
# ломалось раньше -- подробно в шапке tiempo.py.

MESES_RU = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


def _periodo_dia(d: dt.date):
    return d, d, f"{d.day:02d} {MESES_RU[d.month]}"


def _periodo_decada(d: dt.date):
    m = MESES_RU[d.month]
    if d.day <= 10:
        return dt.date(d.year, d.month, 1), dt.date(d.year, d.month, 10), f"01-10 {m}"
    if d.day <= 20:
        return dt.date(d.year, d.month, 11), dt.date(d.year, d.month, 20), f"11-20 {m}"
    start = dt.date(d.year, d.month, 21)
    end = (dt.date(d.year, d.month + 1, 1) - dt.timedelta(days=1)) if d.month < 12 else dt.date(d.year, 12, 31)
    return start, end, f"21-{end.day} {m}"


def _periodo_quincena(d: dt.date):
    m = MESES_RU[d.month]
    if d.day <= 15:
        return dt.date(d.year, d.month, 1), dt.date(d.year, d.month, 15), f"01-15 {m}"
    start = dt.date(d.year, d.month, 16)
    end = (dt.date(d.year, d.month + 1, 1) - dt.timedelta(days=1)) if d.month < 12 else dt.date(d.year, 12, 31)
    return start, end, f"16-{end.day} {m}"


def _periodo_mes(d: dt.date):
    start = dt.date(d.year, d.month, 1)
    end = (dt.date(d.year, d.month + 1, 1) - dt.timedelta(days=1)) if d.month < 12 else dt.date(d.year, 12, 31)
    return start, end, MESES_RU[d.month]


GRANULARIDADES = {
    "dia": _periodo_dia, "decada": _periodo_decada, "quincena": _periodo_quincena,
    "mes": _periodo_mes,
}


def is_coffee(platillo: str, tipo_grupo: str, keywords: list[str]) -> bool:
    if tipo_grupo not in CAFETERIA_TIPOS:
        return False
    n = (platillo or "").upper()
    return any(kw in n for kw in keywords)


DIAS_SEMANA_RU = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]


def sucursales_disponibles(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT sucursal FROM sales_lines ORDER BY sucursal"))
        return [r[0] for r in rows]


def rango_fechas(engine: Engine, sucursal: str | None = None) -> tuple[str, str] | None:
    sql = "SELECT MIN(fecha), MAX(fecha) FROM sales_lines"
    params = {}
    if sucursal:
        sql += " WHERE sucursal = :sucursal"
        params["sucursal"] = sucursal
    with engine.connect() as conn:
        row = conn.execute(text(sql), params).first()
    if not row or row[0] is None:
        return None
    return row[0], row[1]


def serie_por_periodo(engine: Engine, granularidad: str, sucursal: str | None = None,
                       desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Aналитика напитков por periodo (dia/decada/quincena/mes), agregando
    desde la base. sucursal=None -> todas las sucursales juntas. desde/hasta
    = 'YYYY-MM-DD' (opcional).

    Cuatro categorías, SIEMPRE la misma partición limpia (sin solapar --
    para que el dashboard pueda sumar "café + frappé + otras bebidas" y
    obtener exactamente "bebidas", en dinero, en % o en unidades, sin
    explicar un doble conteo cada vez):

      - bebidas   -- TODA bebida del menú (CAFETERIA + FRAPPES + REFRESCOS).
      - cafe      -- solo café caliente/frío que NO es frappé (is_coffee
                     arriba, excluyendo tipo_grupo FRAPPES).
      - frappe    -- TODA la categoría FRAPPES, incluido el frappé con
                     café (F. Moka + Espresso, etc.) -- antes ese frappé
                     con café se contaba dentro de "cafe"; se movió aquí
                     porque para el negocio "frappé" es una categoría de
                     producto (bebida fría con hielo/blender), no una
                     pregunta de "¿lleva café o no?".
      - otras     -- resto de CAFETERIA que no es café (chai, matcha,
                     taro, limonada, chocolate...) MÁS todo REFRESCOS
                     (refrescos embotellados) -- volumen mínimo, pero es
                     bebida, y así "bebidas" cubre TODO lo que se vende
                     como bebida, sin dejar nada fuera.

    café + frappe + otras == bebidas, exactamente, en las tres medidas
    (dinero, % de ventas totales, unidades) -- por construcción, no por
    redondeo."""
    fn = GRANULARIDADES[granularidad]
    keywords = [row["palabra"] for row in get_coffee_keywords(engine)]

    sql = ("SELECT fecha, tipo_grupo, platillo, importe, cantidad "
           "FROM sales_lines WHERE 1=1")
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    if desde:
        sql += " AND fecha >= :desde"
        params["desde"] = desde
    if hasta:
        sql += " AND fecha <= :hasta"
        params["hasta"] = hasta

    ventas = defaultdict(float)
    cafe = defaultdict(float)
    frappe = defaultdict(float)         # FRAPPES sin café -- ver docstring
    otras_bebidas = defaultdict(float)  # CAFETERIA que no es café
    unid_ventas = defaultdict(float)
    unid_cafe = defaultdict(float)
    unid_frappe = defaultdict(float)
    unid_otras_bebidas = defaultdict(float)
    meta = {}

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings()
        for row in rows:
            d = dt.date.fromisoformat(row["fecha"])
            start, end, etiqueta = fn(d)
            key = (start, etiqueta)
            meta[key] = (start, end, etiqueta, d.year)
            ventas[key] += row["importe"]
            unid_ventas[key] += row["cantidad"]

            if row["tipo_grupo"] == "FRAPPES":
                frappe[key] += row["importe"]
                unid_frappe[key] += row["cantidad"]
            elif is_coffee(row["platillo"], row["tipo_grupo"], keywords):
                cafe[key] += row["importe"]
                unid_cafe[key] += row["cantidad"]
            elif row["tipo_grupo"] in OTRAS_BEBIDAS_TIPOS:
                otras_bebidas[key] += row["importe"]
                unid_otras_bebidas[key] += row["cantidad"]

    salida = []
    for key in sorted(ventas, key=lambda k: k[0]):
        start, end, etiqueta, anio = meta[key]
        tot = ventas[key]
        cof, fra, otr = cafe.get(key, 0.0), frappe.get(key, 0.0), otras_bebidas.get(key, 0.0)
        beb = cof + fra + otr  # = toda CAFETERIA + toda FRAPPES, sin duplicar

        u_tot = unid_ventas[key]
        u_cof = unid_cafe.get(key, 0.0)
        u_fra = unid_frappe.get(key, 0.0)
        u_otr = unid_otras_bebidas.get(key, 0.0)
        u_beb = u_cof + u_fra + u_otr

        def pct(parte, base):
            return round(100 * parte / base, 2) if base else 0.0

        salida.append({
            "periodo_inicio": start, "periodo_fin": end, "etiqueta": etiqueta, "anio": anio,
            # -- dinero, $ --
            "ventas_totales": round(tot, 2),
            "bebidas_total": round(beb, 2),
            "cafe_total": round(cof, 2),
            "frappe_total": round(fra, 2),
            "otras_bebidas_total": round(otr, 2),
            # -- доля от ОБЩИХ продаж, % (las cuatro sobre la MISMA base,
            #    para que sean comparables directamente en un solo gráfico) --
            "bebidas_pct": pct(beb, tot),
            "cafe_pct": pct(cof, tot),
            "frappe_pct": pct(fra, tot),
            "otras_bebidas_pct": pct(otr, tot),
            # -- доля от выручки НАПИТКОВ, % (para "¿qué tan grande es el
            #    café DENTRO del menú de bebidas?", distinto de "% de
            #    todas las ventas") --
            "cafe_pct_bebidas": pct(cof, beb),
            "frappe_pct_bebidas": pct(fra, beb),
            "otras_bebidas_pct_bebidas": pct(otr, beb),
            # -- unidades, шт --
            "unidades_totales": round(u_tot, 2),
            "unidades_bebidas": round(u_beb, 2),
            "unidades_cafe": round(u_cof, 2),
            "unidades_frappe": round(u_fra, 2),
            "unidades_otras_bebidas": round(u_otr, 2),
            "unidades_cafe_pct": pct(u_cof, u_tot),
        })
    return salida


def patron_horario_bebidas(engine: Engine, sucursal: str | None = None,
                            desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """La MISMA partición de cuatro categorías que serie_por_periodo, pero
    sumada por HORA DEL DÍA (0-23) sobre TODO el rango de una vez -- no
    "cuánto se vende", sino "A QUÉ HORA se vende cada categoría". Sirve
    para ver si el café se concentra en la mañana y el frappé en la
    tarde (calor) -- la misma pregunta que el archivo de referencia
    intentaba responder con la temperatura, pero con datos que ya
    tenemos (hora_cierre), sin depender de un dato externo manual.

    Requiere hora_cierre -- filas sin hora (exportaciones viejas antes de
    que Wansoft empezara a guardar el número de chequeo) quedan fuera."""
    keywords = [row["palabra"] for row in get_coffee_keywords(engine)]

    sql = ("SELECT hora_cierre, tipo_grupo, platillo, importe, cantidad "
           "FROM sales_lines WHERE hora_cierre IS NOT NULL AND hora_cierre != ''")
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    if desde:
        sql += " AND fecha >= :desde"
        params["desde"] = desde
    if hasta:
        sql += " AND fecha <= :hasta"
        params["hasta"] = hasta

    cafe = defaultdict(float)
    frappe = defaultdict(float)
    otras = defaultdict(float)
    u_cafe = defaultdict(float)
    u_frappe = defaultdict(float)
    u_otras = defaultdict(float)

    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            try:
                hora = dt.datetime.fromisoformat(row["hora_cierre"]).hour
            except (ValueError, TypeError):
                continue
            if row["tipo_grupo"] == "FRAPPES":
                frappe[hora] += row["importe"]
                u_frappe[hora] += row["cantidad"]
            elif is_coffee(row["platillo"], row["tipo_grupo"], keywords):
                cafe[hora] += row["importe"]
                u_cafe[hora] += row["cantidad"]
            elif row["tipo_grupo"] in OTRAS_BEBIDAS_TIPOS:
                otras[hora] += row["importe"]
                u_otras[hora] += row["cantidad"]

    return [
        {
            "hora": h,
            "cafe_total": round(cafe.get(h, 0.0), 2),
            "frappe_total": round(frappe.get(h, 0.0), 2),
            "otras_bebidas_total": round(otras.get(h, 0.0), 2),
            "unidades_cafe": round(u_cafe.get(h, 0.0), 2),
            "unidades_frappe": round(u_frappe.get(h, 0.0), 2),
            "unidades_otras_bebidas": round(u_otras.get(h, 0.0), 2),
        }
        for h in range(24)
    ]


def top_platillos_bebidas(engine: Engine, sucursal: str | None = None,
                           desde: str | None = None, hasta: str | None = None,
                           n: int = 6) -> dict[str, list[dict]]:
    """La MISMA partición de tres categorías (café/frappé/otras bebidas --
    ver serie_por_periodo), pero por POSICIÓN DE MENÚ dentro de cada una,
    no por fecha ni por hora. Responde la pregunta que ni la dinámica ni
    el patrón por hora contestan: "la categoría creció -- ¿por CUÁL
    producto exactamente?" -- por ejemplo si el crecimiento de Frappé es
    parejo entre sabores o lo carga un solo producto nuevo."""
    keywords = [row["palabra"] for row in get_coffee_keywords(engine)]

    sql = "SELECT tipo_grupo, platillo, importe, cantidad FROM sales_lines WHERE 1=1"
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    if desde:
        sql += " AND fecha >= :desde"
        params["desde"] = desde
    if hasta:
        sql += " AND fecha <= :hasta"
        params["hasta"] = hasta

    cafe: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    frappe: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    otras: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])

    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            clave = row["platillo"] or "(без названия)"
            if row["tipo_grupo"] == "FRAPPES":
                destino = frappe
            elif is_coffee(row["platillo"], row["tipo_grupo"], keywords):
                destino = cafe
            elif row["tipo_grupo"] in OTRAS_BEBIDAS_TIPOS:
                destino = otras
            else:
                continue
            destino[clave][0] += row["importe"]
            destino[clave][1] += row["cantidad"]

    def _top(datos: dict[str, list[float]]) -> list[dict]:
        total = sum(v[0] for v in datos.values())
        filas = [
            {"platillo": k, "ventas": round(v[0], 2), "unidades": round(v[1], 2),
             "pct_categoria": round(100 * v[0] / total, 1) if total else 0.0}
            for k, v in datos.items()
        ]
        filas.sort(key=lambda r: r["ventas"], reverse=True)
        return filas[:n]

    return {"Кофе": _top(cafe), "Фраппе": _top(frappe), "Остальные напитки": _top(otras)}


def cafe_por_sucursal(engine: Engine, desde: str | None = None,
                       hasta: str | None = None) -> list[dict]:
    """Compara el rendimiento del café ENTRE puntos -- pregunta que ninguna
    otra función de este archivo responde, porque todas filtran a UN punto
    a la vez (o a todos juntos). Siempre trae TODAS las sucursales, sin
    importar el filtro "Точка" de la barra lateral -- es la única sección
    de la página pensada para comparar, no para acotar.

    "% de café" aquí es sobre las VENTAS TOTALES de esa sucursal (todo el
    menú, no solo bebidas) -- así se compara qué tanto pesa el café en
    cada negocio, sin que el resultado dependa de qué tan grande es el
    punto en pesos absolutos."""
    keywords = [row["palabra"] for row in get_coffee_keywords(engine)]

    sql = "SELECT sucursal, tipo_grupo, platillo, importe, cantidad FROM sales_lines WHERE 1=1"
    params: dict = {}
    if desde:
        sql += " AND fecha >= :desde"
        params["desde"] = desde
    if hasta:
        sql += " AND fecha <= :hasta"
        params["hasta"] = hasta

    ventas_totales = defaultdict(float)
    cafe = defaultdict(float)
    unid_cafe = defaultdict(float)

    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            suc = row["sucursal"]
            ventas_totales[suc] += row["importe"]
            if is_coffee(row["platillo"], row["tipo_grupo"], keywords):
                cafe[suc] += row["importe"]
                unid_cafe[suc] += row["cantidad"]

    salida = [
        {
            "sucursal": suc,
            "cafe_total": round(cafe.get(suc, 0.0), 2),
            "unidades_cafe": round(unid_cafe.get(suc, 0.0), 2),
            "ventas_totales": round(tot, 2),
            "cafe_pct_ventas": round(100 * cafe.get(suc, 0.0) / tot, 2) if tot else 0.0,
        }
        for suc, tot in ventas_totales.items()
    ]
    salida.sort(key=lambda r: r["cafe_total"], reverse=True)
    return salida


def _filtro_rango_sql(sucursal, desde, hasta):
    """Construye el fragmento WHERE + parámetros compartido por varias
    consultas de abajo (mismo patrón que serie_por_periodo)."""
    sql = " WHERE 1=1"
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    if desde:
        sql += " AND fecha >= :desde"
        params["desde"] = desde
    if hasta:
        sql += " AND fecha <= :hasta"
        params["hasta"] = hasta
    return sql, params


def top_platillos(engine: Engine, sucursal: str | None = None, desde: str | None = None,
                   hasta: str | None = None, n: int = 15) -> list[dict]:
    """Posiciones de menú más vendidas por ingresos, dentro del rango de
    fechas (todas las categorías, no solo café -- 'ventas completas')."""
    where, params = _filtro_rango_sql(sucursal, desde, hasta)
    sql = "SELECT platillo, tipo_grupo, importe, cantidad FROM sales_lines" + where

    ventas = defaultdict(float)
    unidades = defaultdict(float)
    grupo_de = {}
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            clave = row["platillo"] or "(без названия)"
            ventas[clave] += row["importe"]
            unidades[clave] += row["cantidad"]
            grupo_de[clave] = row["tipo_grupo"]

    filas = [
        {"platillo": k, "grupo": grupo_de.get(k), "ventas": round(v, 2),
         "unidades": round(unidades[k], 2)}
        for k, v in ventas.items()
    ]
    filas.sort(key=lambda r: r["ventas"], reverse=True)
    return filas[:n]


def ventas_por_categoria(engine: Engine, sucursal: str | None = None, desde: str | None = None,
                          hasta: str | None = None) -> list[dict]:
    """Ventas totales agrupadas por 'Tipo de grupo' del menú (CAFETERIA,
    FRAPPES, PANADERIA, etc.) -- la foto completa, no solo café."""
    where, params = _filtro_rango_sql(sucursal, desde, hasta)
    sql = "SELECT tipo_grupo, importe, cantidad FROM sales_lines" + where

    ventas = defaultdict(float)
    unidades = defaultdict(float)
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            clave = row["tipo_grupo"] or "(без категории)"
            ventas[clave] += row["importe"]
            unidades[clave] += row["cantidad"]

    filas = [
        {"categoria": k, "ventas": round(v, 2), "unidades": round(unidades[k], 2)}
        for k, v in ventas.items()
    ]
    filas.sort(key=lambda r: r["ventas"], reverse=True)
    return filas


ORDEN_CATEGORIAS_RESUMEN = ["Panadería", "Pastelería", "Café", "Остальное"]


def resumen_dia(engine: Engine, fecha: str, sucursal: str | None = None) -> dict:
    """Краткая сводка одного дня для главной страницы: сколько продаж
    (чеков), выручка, средний чек и доли по укрупнённым категориям
    (панадерия / пастелерия / кофе / остальное).

    'Продажа' здесь = отдельный чек (уникальный 'movimiento_pdv'), а НЕ
    отдельная строка/позиция -- иначе бы считало каждый круассан отдельной
    продажей."""
    target = dt.date.fromisoformat(fecha)
    keywords = [row["palabra"] for row in get_coffee_keywords(engine)]

    sql = ("SELECT tipo_grupo, platillo, importe, movimiento_pdv "
           "FROM sales_lines WHERE fecha = :fecha")
    params: dict = {"fecha": fecha}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal

    ventas_totales = 0.0
    ordenes: set = set()
    por_categoria: dict[str, float] = defaultdict(float)

    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            ventas_totales += row["importe"]
            if row["movimiento_pdv"] is not None:
                ordenes.add(row["movimiento_pdv"])

            tg = (row["tipo_grupo"] or "").upper()
            if is_coffee(row["platillo"], row["tipo_grupo"], keywords):
                por_categoria["Café"] += row["importe"]
            elif tg == "PANADERIA":
                por_categoria["Panadería"] += row["importe"]
            elif tg == "PASTELERIA":
                por_categoria["Pastelería"] += row["importe"]
            else:
                por_categoria["Остальное"] += row["importe"]

    num_ordenes = len(ordenes)
    categorias = [
        {
            "categoria": k,
            "monto": round(v, 2),
            "pct": round(100 * v / ventas_totales, 1) if ventas_totales else 0.0,
        }
        for k, v in por_categoria.items()
    ]
    categorias.sort(key=lambda c: ORDEN_CATEGORIAS_RESUMEN.index(c["categoria"])
                     if c["categoria"] in ORDEN_CATEGORIAS_RESUMEN else 99)

    return {
        "fecha": fecha,
        "dia_semana": DIAS_SEMANA_RU[target.weekday()],
        # Закрыт ли день -- по времени Сан-Луис-Потоси (tiempo.hoy()).
        # Если нет, цифры ниже -- это ЧАСТЬ дня: магазин ещё торгует, а
        # выгрузка Wansoft сделана посреди дня. Дашборд обязан это
        # подписать, иначе неполный день выглядит как обвал продаж.
        "dia_cerrado": target != tiempo.hoy(),
        "num_ordenes": num_ordenes,
        "ventas_totales": round(ventas_totales, 2),
        "cheque_promedio": round(ventas_totales / num_ordenes, 2) if num_ordenes else 0.0,
        "categorias": categorias,
    }


def fechas_con_hora(engine: Engine, sucursal: str | None = None) -> list[str]:
    """Fechas para las que sí tenemos 'hora_cierre' (o sea, cargadas o
    recargadas ya con la versión del programa que guarda la hora) --
    solo esas sirven para la comparación por hora del día."""
    sql = ("SELECT DISTINCT fecha FROM sales_lines "
           "WHERE hora_cierre IS NOT NULL AND hora_cierre != ''")
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params)
        return sorted(r[0] for r in rows)


# Vida media del peso por recencia, en semanas: a las 8 semanas (~2 meses)
# un día comparable ya pesa la mitad que uno recién pasado; a medio año,
# ~1.5%. No es un corte duro -- TODO el historial sigue entrando en la
# cuenta (rango grande, a propósito), solo que las semanas recientes
# pesan más -- así el pronóstico sigue la tendencia actual del
# negocio en vez de diluirse en meses viejos si las ventas vienen
# creciendo (o cayendo).
_MEDIA_VIDA_SEMANAS = 8.0


def _peso_recencia(fecha_dato: dt.date, fecha_objetivo: dt.date) -> float:
    semanas = abs((fecha_objetivo - fecha_dato).days) / 7
    return 0.5 ** (semanas / _MEDIA_VIDA_SEMANAS)


def _percentil(valores_ordenados: list[float], p: float) -> float:
    """Percentil por interpolación lineal -- sin numpy: metrics.py no
    depende de nada más que SQLAlchemy."""
    if not valores_ordenados:
        return 0.0
    if len(valores_ordenados) == 1:
        return valores_ordenados[0]
    k = (len(valores_ordenados) - 1) * p
    f = int(k)
    c = min(f + 1, len(valores_ordenados) - 1)
    if f == c:
        return valores_ordenados[f]
    return valores_ordenados[f] + (valores_ordenados[c] - valores_ordenados[f]) * (k - f)


def _recortar_atipicos(valores: list[float]) -> list[float]:
    """Suaviza (nunca descarta) valores atípicos de una hora puntual entre
    los días comparables: un evento, una fiesta o un pedido grande de
    catering en UN viernes no debe torcer el pronóstico de todos los
    demás viernes. Método estándar de caja (rango intercuartílico) --
    todo lo que caiga fuera de [Q1 - 1.5*RIC, Q3 + 1.5*RIC] se recorta
    (winsoriza) a ese límite en vez de eliminarse: el día sigue
    contando, solo que su valor extremo deja de arrastrar el promedio.
    Con menos de 5 días el rango intercuartílico no es confiable -- se
    deja el dato tal cual (nada que recortar con tan poca muestra)."""
    if len(valores) < 5:
        return list(valores)
    ordenados = sorted(valores)
    q1 = _percentil(ordenados, 0.25)
    q3 = _percentil(ordenados, 0.75)
    ric = q3 - q1
    piso = max(0.0, q1 - 1.5 * ric)
    techo = q3 + 1.5 * ric
    return [min(max(v, piso), techo) for v in valores]


def panaderia_real_y_pronostico(engine: Engine, desde: str, hasta: str,
                                 sucursal: str | None = None) -> list[dict]:
    """Producción de Panadería (unidades) DÍA por día, para la página
    "Планирование" -- compara "cuánto se vendió" contra "cuánto se
    esperaba vender" y (aparte, en la tabla de plan_produccion) contra
    "cuánto se planeó producir". Mismo método que el pronóstico por hora de
    ventas_por_hora (promedio del mismo día de semana, ponderado por
    recencia -- ver _peso_recencia --, con outliers suavizados -- ver
    _recortar_atipicos), pero agregando POR DÍA COMPLETO en vez de por
    hora, y solo tipo_grupo='PANADERIA' en vez de todo el menú.

    desde/hasta puede incluir fechas FUTURAS (para planear producción de
    días que todavía no pasaron) -- ahí "real_unidades" sale None (no hay
    venta todavía), pero "pronostico_unidades" sí se calcula igual, a
    partir de todo el historial disponible del mismo día de semana."""
    # Agregado en el SQL (GROUP BY fecha), no fila por fila en Python -- esta
    # tabla tiene cientos de miles de líneas de Panadería; traerlas todas
    # para sumar en Python tardaba ~30s por el tráfico de red hacia la base
    # en la nube, contra <1s agregando del lado del servidor.
    sql = ("SELECT fecha, SUM(cantidad) AS total FROM sales_lines "
           "WHERE tipo_grupo = 'PANADERIA'" + PANADERIA_EXCLUIR_SQL)
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    sql += " GROUP BY fecha"

    por_dia: dict[dt.date, float] = {}
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            por_dia[dt.date.fromisoformat(row["fecha"])] = row["total"]

    por_dia_semana: dict[int, list[tuple[dt.date, float]]] = defaultdict(list)
    for d, cantidad in por_dia.items():
        por_dia_semana[d.weekday()].append((d, cantidad))

    fecha_ini = dt.date.fromisoformat(desde)
    fecha_fin = dt.date.fromisoformat(hasta)

    salida = []
    d = fecha_ini
    while d <= fecha_fin:
        historicos = [(fd, val) for fd, val in por_dia_semana.get(d.weekday(), []) if fd != d]
        pronostico = None
        if historicos:
            valores = _recortar_atipicos([v for _, v in historicos])
            pesos = [_peso_recencia(fd, d) for fd, _ in historicos]
            peso_total = sum(pesos)
            if peso_total:
                pronostico = sum(v * p for v, p in zip(valores, pesos)) / peso_total
        salida.append({
            "fecha": d.isoformat(),
            "real_unidades": round(por_dia[d], 2) if d in por_dia else None,
            "pronostico_unidades": round(pronostico, 2) if pronostico is not None else None,
        })
        d += dt.timedelta(days=1)
    return salida


def top_platillos_panaderia(engine: Engine, sucursal: str | None = None,
                             desde: str | None = None, hasta: str | None = None,
                             n: int = 10) -> list[dict]:
    """Top posiciones de Panadería por UNIDADES (no por dinero -- para
    planear producción/personal importa cuántas piezas hay que hacer, no
    cuánto dejan en pesos) dentro del rango pedido. Misma idea que
    top_platillos_bebidas, pero una sola categoría -- responde "¿QUÉ se
    produce?", que ni la serie por día ni el patrón por hora contestan:
    dos posiciones pueden pesar lo mismo en piezas y necesitar personal muy
    distinto (una bandeja de bolillo vs. un pastel decorado a mano)."""
    # Agregado en el SQL (GROUP BY platillo), no fila por fila en Python --
    # mismo motivo que panaderia_real_y_pronostico: cientos de miles de
    # líneas de Panadería, traerlas todas es ~30s de tráfico contra la
    # nube por nada (aquí solo hacen falta los totales por posición).
    sql = ("SELECT platillo, SUM(importe) AS ventas, SUM(cantidad) AS unidades "
           "FROM sales_lines WHERE tipo_grupo = 'PANADERIA'" + PANADERIA_EXCLUIR_SQL)
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    if desde:
        sql += " AND fecha >= :desde"
        params["desde"] = desde
    if hasta:
        sql += " AND fecha <= :hasta"
        params["hasta"] = hasta
    sql += " GROUP BY platillo"

    con_datos: list[dict] = []
    total_unidades = 0.0
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            clave = row["platillo"] or "(без названия)"
            con_datos.append({"platillo": clave, "ventas": row["ventas"], "unidades": row["unidades"]})
            total_unidades += row["unidades"]

    filas = [
        {"platillo": r["platillo"], "unidades": round(r["unidades"], 2),
         "ventas": round(r["ventas"], 2),
         "pct_unidades": round(100 * r["unidades"] / total_unidades, 1) if total_unidades else 0.0}
        for r in con_datos
    ]
    filas.sort(key=lambda r: r["unidades"], reverse=True)
    return filas[:n]


def patron_horario_panaderia(engine: Engine, sucursal: str | None = None,
                              desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """A QUÉ HORA se venden las unidades de Panadería, sumado sobre TODO el
    rango pedido (mismo método que patron_horario_bebidas, una sola
    categoría) -- la pregunta clave para personal: no cuánto se vende en
    total, sino en qué horas hace falta gente detrás del mostrador
    reponiendo/atendiendo. Requiere hora_cierre -- igual que
    patron_horario_bebidas, filas viejas sin hora quedan fuera."""
    # SUBSTR(hora_cierre, 12, 2) saca las dos letras "HH" de un ISO
    # 'YYYY-MM-DDTHH:MM:SS[.ffffff]' -- función portable entre SQLite y
    # Postgres, así el agregado por hora corre en el servidor (GROUP BY)
    # en vez de traer cientos de miles de líneas de Panadería fila por
    # fila (mismo problema de red que panaderia_real_y_pronostico)."""
    sql = ("SELECT SUBSTR(hora_cierre, 12, 2) AS hora_str, "
           "SUM(importe) AS ventas, SUM(cantidad) AS unidades "
           "FROM sales_lines "
           "WHERE tipo_grupo = 'PANADERIA' AND hora_cierre IS NOT NULL "
           "AND hora_cierre != ''" + PANADERIA_EXCLUIR_SQL)
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    if desde:
        sql += " AND fecha >= :desde"
        params["desde"] = desde
    if hasta:
        sql += " AND fecha <= :hasta"
        params["hasta"] = hasta
    sql += " GROUP BY SUBSTR(hora_cierre, 12, 2)"

    ventas = defaultdict(float)
    unidades = defaultdict(float)
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            try:
                hora = int(row["hora_str"])
            except (ValueError, TypeError):
                continue
            ventas[hora] += row["ventas"]
            unidades[hora] += row["unidades"]

    return [
        {
            "hora": h,
            "ventas": round(ventas.get(h, 0.0), 2),
            "unidades": round(unidades.get(h, 0.0), 2),
        }
        for h in range(24)
    ]


def analizar_desviacion_produccion(dias: list[dict], campo: str) -> dict | None:
    """Explica la brecha entre "real_unidades" (ventas ya cerradas) y
    dias[i][campo] -- "pronostico_unidades" o "unidades_plan" -- para la
    página "Планирование": la pregunta que ni el gráfico ni la tabla
    contestan solas es "¿por qué el plan/pronóstico quedó tan por debajo
    (o por arriba) de lo real?".

    Dos causas posibles, distinguibles con aritmética simple (nada de IA
    inventando explicaciones de negocio que no están en los datos):
      - TENDENCIA sostenida -- si la segunda mitad del rango vendió, en
        promedio, bastante más que la primera, el pronóstico (que pesa
        semanas recientes pero sigue mirando hacia atrás) se está
        quedando corto porque el negocio crece más rápido de lo que el
        peso por recencia alcanza a seguir -- no es un solo día raro, es
        el rango entero corriéndose para arriba.
      - DÍA PUNTUAL -- si la tendencia es chica pero hay un día con una
        diferencia mucho mayor que el resto, ese día concreto es el que
        arrastra el promedio (un evento, un fin de semana largo, etc.),
        no un problema del método en general.

    Solo compara días donde AMBOS valores existen (días ya cerrados con
    pronóstico/plan calculado) -- días futuros no tienen "real" con qué
    comparar todavía. Devuelve None si hay menos de 2 días comparables."""
    con_ambos = [d for d in dias if d.get("real_unidades") is not None and d.get(campo) is not None]
    if len(con_ambos) < 2:
        return None

    total_real = sum(d["real_unidades"] for d in con_ambos)
    total_comparado = sum(d[campo] for d in con_ambos)
    desviacion_pct = round(100 * (total_real - total_comparado) / total_comparado, 1) if total_comparado else 0.0

    mitad = len(con_ambos) // 2
    primera, segunda = con_ambos[:mitad] or con_ambos, con_ambos[mitad:] or con_ambos
    real_prom_1 = sum(d["real_unidades"] for d in primera) / len(primera)
    real_prom_2 = sum(d["real_unidades"] for d in segunda) / len(segunda)
    tendencia_pct = round(100 * (real_prom_2 - real_prom_1) / real_prom_1, 1) if real_prom_1 else 0.0

    peor = max(con_ambos, key=lambda d: d["real_unidades"] - d[campo])

    return {
        "n_dias": len(con_ambos),
        "total_real": round(total_real, 0),
        "total_comparado": round(total_comparado, 0),
        "desviacion_pct": desviacion_pct,
        "tendencia_pct": tendencia_pct,
        "peor_dia": peor["fecha"],
        "peor_dia_real": round(peor["real_unidades"], 0),
        "peor_dia_comparado": round(peor[campo], 0),
    }


def ventas_por_hora(engine: Engine, fecha: str, sucursal: str | None = None) -> dict:
    """Продажи по часам одного конкретного дня (в деньгах И в штуках) против
    ПРОГНОЗА для того же дня недели -- построен из ВСЕЙ доступной истории
    (никакого ограничения по диапазону) среди дней с тем же днём недели
    (только они, никаких других), но не простым средним, а взвешенным:

    - недавние недели весят больше старых (экспоненциальное затухание,
      см. _peso_recencia/_MEDIA_VIDA_SEMANAS) -- прогноз следует за
      текущим трендом бизнеса, а не тонет в данных полугодовой давности;
    - резкие всплески/провалы одного дня в конкретный час сглаживаются
      (винзоризация по межквартильному размаху, см. _recortar_atipicos)
      -- один день с банкетом на вынос не должен задирать прогноз для всех
      остальных пятниц.

    Это и есть 'прогноз' -- не реальное время, а обоснованное ожидание
    для такого дня, посчитанное из истории."""
    target = dt.date.fromisoformat(fecha)
    weekday = target.weekday()

    sql = ("SELECT fecha, hora_cierre, importe, cantidad FROM sales_lines "
           "WHERE hora_cierre IS NOT NULL AND hora_cierre != ''")
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal

    real = defaultdict(float)
    real_unid = defaultdict(float)
    # день -> {час: (сумма, штуки)} -- только для дней с ТЕМ ЖЕ днём
    # недели, что и целевой (никогда не сам target). Храним ПОЛНУЮ
    # матрицу, а не только накопленную сумму, потому что и взвешивание по
    # свежести, и сглаживание выбросов по часу (см. выше) требуют
    # отдельных значений по каждому дню, а не готового аккумулятора.
    dias_data: dict[dt.date, dict[int, tuple[float, float]]] = defaultdict(dict)

    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            d = dt.date.fromisoformat(row["fecha"])
            try:
                hora = dt.datetime.fromisoformat(row["hora_cierre"]).hour
            except (ValueError, TypeError):
                continue
            if d == target:
                real[hora] += row["importe"]
                real_unid[hora] += row["cantidad"]
            elif d.weekday() == weekday:
                importe_prev, cantidad_prev = dias_data[d].get(hora, (0.0, 0.0))
                dias_data[d][hora] = (
                    importe_prev + row["importe"], cantidad_prev + row["cantidad"],
                )

    dias_ordenados = sorted(dias_data)
    n_dias = len(dias_ordenados)

    if n_dias:
        pesos = {d: _peso_recencia(d, target) for d in dias_ordenados}
        peso_total = sum(pesos.values())
        # Tamaño de muestra "efectivo" (fórmula estándar de Kish para
        # promedios ponderados) -- si las últimas semanas pesan mucho más
        # que el resto, el pronóstico en la práctica se apoya en menos
        # días de los que dice n_dias; útil para no prometer más
        # precisión de la que hay.
        n_efectivo = round((peso_total ** 2) / sum(p ** 2 for p in pesos.values()), 1)
    else:
        pesos, peso_total, n_efectivo = {}, 0.0, 0.0

    def _pronostico_hora(indice: int) -> float | None:
        if not n_dias:
            return None
        valores = [dias_data[d].get(indice, (0.0, 0.0))[0] for d in dias_ordenados]
        valores = _recortar_atipicos(valores)
        return sum(v * pesos[d] for v, d in zip(valores, dias_ordenados)) / peso_total

    def _pronostico_hora_unidades(indice: int) -> float | None:
        if not n_dias:
            return None
        valores = [dias_data[d].get(indice, (0.0, 0.0))[1] for d in dias_ordenados]
        valores = _recortar_atipicos(valores)
        return sum(v * pesos[d] for v, d in zip(valores, dias_ordenados)) / peso_total

    horas = []
    for h in range(24):
        tipico_h = _pronostico_hora(h)
        tipico_u_h = _pronostico_hora_unidades(h)
        horas.append({
            "hora": h,
            "real": round(real.get(h, 0.0), 2),
            "tipico": round(tipico_h, 2) if tipico_h is not None else None,
            "real_unidades": round(real_unid.get(h, 0.0), 2),
            "tipico_unidades": round(tipico_u_h, 2) if tipico_u_h is not None else None,
        })
    return {
        "fecha": fecha,
        "dia_semana": DIAS_SEMANA_RU[weekday],
        "n_dias_promedio": n_dias,
        "n_dias_efectivo": n_efectivo,
        "horas": horas,
    }


# Con una desviación dentro de este margen (en cualquier sentido) el día se
# considera "en línea" con el pronóstico -- no vale la pena diagnosticar
# ruido normal como si fuera un problema real.
_UMBRAL_DESVIACION_PCT = 5.0

# Si menos de esta fracción de las horas activas terminó por debajo del
# pronóstico, el problema se etiqueta "concentrado" (una franja horaria
# puntual, el resto del día normal) -- si son más, es "distribuido" (el día
# entero flojo por igual). Se mide por CANTIDAD de horas afectadas, no por
# cuánto suman las peores -- con pocas horas activas, tomar "las 3 peores"
# explica casi todo el déficit aunque las 5 horas del día estén parejas
# hacia abajo, lo que daba falsos "concentrado" con muestras chicas.
_UMBRAL_CONCENTRACION = 0.4


def analizar_desempeno_por_hora(horas: list[dict]) -> dict | None:
    """Diagnóstico corto de un día ya cerrado, comparando el mismo bloque de
    horas activas que se ve en el gráfico "Прогноз и факт" (viene de
    ventas_por_hora, ya recortado a horas con movimiento -- ver
    dashboard._horas_activas): cuánto se desvió la venta real del
    pronóstico, si la desviación viene de menos CLIENTES (unidades) o de un
    ticket promedio más bajo (unidades en línea pero dinero no), y si el
    bache se concentra en una franja horaria puntual o está repartido en
    todo el día. Devuelve None cuando no hay pronóstico con el que comparar
    (día sin historial suficiente) -- en ese caso no hay nada que
    diagnosticar todavía.

    No es una IA explicando el día -- son un par de reglas aritméticas
    simples y transparentes sobre los mismos números que ya están en el
    gráfico; dashboard.py solo convierte este diccionario en las frases que
    ve Roman."""
    con_pronostico = [h for h in horas if h["tipico"] is not None]
    if not con_pronostico:
        return None

    total_real = sum(h["real"] for h in horas)
    total_tipico = sum(h["tipico"] for h in con_pronostico)
    if not total_tipico:
        return None

    unid_real = sum(h["real_unidades"] for h in horas)
    con_pronostico_u = [h for h in horas if h["tipico_unidades"] is not None]
    unid_tipico = sum(h["tipico_unidades"] for h in con_pronostico_u) if con_pronostico_u else 0.0

    delta_pct = round(100 * (total_real - total_tipico) / total_tipico, 1)
    delta_unid_pct = round(100 * (unid_real - unid_tipico) / unid_tipico, 1) if unid_tipico else None

    if delta_pct >= _UMBRAL_DESVIACION_PCT:
        estado = "por_encima"
    elif delta_pct <= -_UMBRAL_DESVIACION_PCT:
        estado = "por_debajo"
    else:
        estado = "en_linea"

    # Aporte de cada hora (con pronóstico) a la diferencia total, para
    # encontrar las horas que más pesan en el déficit -- solo se calcula
    # cuando de verdad hay un déficit que explicar.
    horas_criticas: list[dict] = []
    concentrado = False
    if estado == "por_debajo":
        diffs = sorted(
            ({"hora": h["hora"], "diff": round(h["real"] - h["tipico"], 2)} for h in con_pronostico),
            key=lambda d: d["diff"],
        )
        negativas = [d for d in diffs if d["diff"] < 0]
        # "Concentrado" = pocas horas cargan con el problema (el resto del
        # día anduvo normal); "distribuido" = la mayoría de las horas
        # activas terminaron por debajo -- un factor del día completo, no
        # de un momento puntual.
        concentrado = bool(negativas) and (len(negativas) / len(con_pronostico)) <= _UMBRAL_CONCENTRACION
        horas_criticas = negativas[:3]

    return {
        "estado": estado,
        "delta_pct": delta_pct,
        "delta_unid_pct": delta_unid_pct,
        "total_real": round(total_real, 2),
        "total_tipico": round(total_tipico, 2),
        "unid_real": round(unid_real, 2),
        "unid_tipico": round(unid_tipico, 2) if unid_tipico else None,
        "horas_criticas": horas_criticas,
        "concentrado": concentrado,
    }


def _resumen_por_fechas(engine: Engine, fechas: list[str], sucursal: str | None = None) -> dict:
    """Suma ventas, unidades y cuenta pedidos (movimiento_pdv únicos) sobre
    un conjunto de fechas específico -- no necesariamente contiguo (para
    'esta semana' vs 'la semana pasada', por ejemplo)."""
    if not fechas:
        return {"ventas": 0.0, "unidades": 0.0, "ordenes": 0}
    sql = "SELECT importe, cantidad, movimiento_pdv FROM sales_lines WHERE fecha IN :fechas"
    params: dict = {"fechas": fechas}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    stmt = text(sql).bindparams(bindparam("fechas", expanding=True))

    ventas = 0.0
    unidades = 0.0
    ordenes: set = set()
    with engine.connect() as conn:
        for row in conn.execute(stmt, params).mappings():
            ventas += row["importe"]
            unidades += row["cantidad"] or 0
            if row["movimiento_pdv"] is not None:
                ordenes.add(row["movimiento_pdv"])
    return {"ventas": round(ventas, 2), "unidades": round(unidades, 2), "ordenes": len(ordenes)}


def _delta_pct(actual: float, pasado: float) -> float | None:
    return round(100 * (actual - pasado) / pasado, 1) if pasado else None


def comparacion_semanal(engine: Engine, fecha: str, sucursal: str | None = None) -> dict:
    """Dos comparaciones para la página 'Главная', cada una con ventas Y
    unidades de ambos periodos (para pintar la diferencia con flecha en
    los dos):

    - 'dia_vs_semana_pasada': un día contra el MISMO día de la semana
      pasada (7 días antes) -- ej. este viernes contra el viernes pasado,
      no un promedio de muchos viernes (eso ya lo hace 'típico' en
      ventas_por_hora). SIEMPRE usa el último día CERRADO -- si el día
      elegido en la página es HOY (todavía vendiendo), esta ventana en
      vez de quedar vacía usa el día anterior (ya cerrado) y lo dice en
      'fecha_usada' / 'dia_semana_usada', que puede no coincidir con el
      día que se ve en el resto de la página.
    - 'semana_vs_semana_pasada': los últimos 7 días -- NO semana de
      calendario (lunes a domingo), sino "los últimos 7 días" contando
      hacia atrás desde el último día CERRADO -- contra los 7 días
      inmediatamente anteriores a esos (sin superponerse ni un solo día:
      cada fecha cae en un único período). Ej. si el último día cerrado es
      18.09, compara 12.09-18.09 (7 fechas) contra 05.09-11.09 (7 fechas,
      justo antes, sin repetir el 11.09 ni el 12.09 en ambos lados).

    'Cerrado' = cualquier fecha que NO sea HOY en San Luis Potosí (ver
    tiempo.py -- NO el reloj de esta computadora ni el del servidor: el
    dashboard tiene que dar la misma respuesta abierto desde la panadería,
    desde Moscú o desde el celular). Como trabajamos postfactum con
    exportaciones de Wansoft, un día anterior a hoy siempre está
    completo; el día de hoy puede seguir vendiendo, así que nunca entra
    en estas comparaciones (ni como día suelto, ni en la suma semanal)."""
    target = dt.date.fromisoformat(fecha)
    hoy = tiempo.hoy()
    dia_cerrado = target != hoy

    resultado: dict = {"fecha": fecha, "dia_cerrado": dia_cerrado}

    # ---- Ventana 1: mismo día de la semana pasada, último día cerrado ---
    dia_comparacion = target if dia_cerrado else (hoy - dt.timedelta(days=1))
    fecha_comparacion = dia_comparacion.isoformat()
    fecha_pasada = (dia_comparacion - dt.timedelta(days=7)).isoformat()

    actual = _resumen_por_fechas(engine, [fecha_comparacion], sucursal)
    pasado = _resumen_por_fechas(engine, [fecha_pasada], sucursal)

    dia_semana_usada = DIAS_SEMANA_RU[dia_comparacion.weekday()]
    if actual["ventas"] <= 0 and actual["ordenes"] == 0:
        resultado["dia_vs_semana_pasada"] = {
            "disponible": False, "motivo": "sin_datos_actuales",
            "fecha_usada": fecha_comparacion, "dia_semana_usada": dia_semana_usada,
        }
    elif pasado["ventas"] <= 0 and pasado["ordenes"] == 0:
        resultado["dia_vs_semana_pasada"] = {
            "disponible": False, "motivo": "sin_datos_pasados",
            "fecha_usada": fecha_comparacion, "dia_semana_usada": dia_semana_usada,
            "fecha_pasada": fecha_pasada,
        }
    else:
        resultado["dia_vs_semana_pasada"] = {
            "disponible": True,
            "uso_dia_cerrado_distinto": fecha_comparacion != fecha,
            "fecha_usada": fecha_comparacion,
            "dia_semana_usada": dia_semana_usada,
            "fecha_pasada": fecha_pasada,
            "ventas_actual": actual["ventas"], "ventas_pasada": pasado["ventas"],
            "unidades_actual": actual["unidades"], "unidades_pasada": pasado["unidades"],
            "ordenes_actual": actual["ordenes"], "ordenes_pasada": pasado["ordenes"],
            "ventas_delta_pct": _delta_pct(actual["ventas"], pasado["ventas"]),
            "unidades_delta_pct": _delta_pct(actual["unidades"], pasado["unidades"]),
        }

    # ---- Ventana 2: últimos 7 días (no semana de calendario), contra los --
    # 7 días justo antes -- sin superponerse (mismo ancla que la ventana 1
    # -- dia_comparacion, el último día cerrado).
    hasta_actual = dia_comparacion
    desde_actual = hasta_actual - dt.timedelta(days=6)
    hasta_pasada = desde_actual - dt.timedelta(days=1)
    desde_pasada = hasta_pasada - dt.timedelta(days=6)

    dias_actual = [desde_actual + dt.timedelta(days=i) for i in range(7)]
    dias_pasada = [desde_pasada + dt.timedelta(days=i) for i in range(7)]

    actual_sem = _resumen_por_fechas(engine, [d.isoformat() for d in dias_actual], sucursal)
    pasada_sem = _resumen_por_fechas(engine, [d.isoformat() for d in dias_pasada], sucursal)
    resultado["semana_vs_semana_pasada"] = {
        "disponible": True,
        "desde": desde_actual.isoformat(),
        "hasta": hasta_actual.isoformat(),
        "dias_incluidos": len(dias_actual),
        "desde_pasada": desde_pasada.isoformat(),
        "hasta_pasada": hasta_pasada.isoformat(),
        "ventas_actual": actual_sem["ventas"], "ventas_pasada": pasada_sem["ventas"],
        "unidades_actual": actual_sem["unidades"], "unidades_pasada": pasada_sem["unidades"],
        "ordenes_actual": actual_sem["ordenes"], "ordenes_pasada": pasada_sem["ordenes"],
        "ventas_delta_pct": _delta_pct(actual_sem["ventas"], pasada_sem["ventas"]),
        "unidades_delta_pct": _delta_pct(actual_sem["unidades"], pasada_sem["unidades"]),
    }

    return resultado
