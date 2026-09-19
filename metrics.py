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

from db import get_coffee_keywords

CAFETERIA_TIPOS = {"CAFETERIA", "FRAPPES"}

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


GRANULARIDADES = {"dia": _periodo_dia, "decada": _periodo_decada, "quincena": _periodo_quincena}


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
    """Doля кофе por periodo (dia/decada/quincena), agregando desde la
    base. sucursal=None -> todas las sucursales juntas. desde/hasta =
    'YYYY-MM-DD' (opcional)."""
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
    unid_ventas = defaultdict(float)
    unid_cafe = defaultdict(float)
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
            if is_coffee(row["platillo"], row["tipo_grupo"], keywords):
                cafe[key] += row["importe"]
                unid_cafe[key] += row["cantidad"]

    salida = []
    for key in sorted(ventas, key=lambda k: k[0]):
        start, end, etiqueta, anio = meta[key]
        tot, cof = ventas[key], cafe.get(key, 0.0)
        u_tot, u_cof = unid_ventas[key], unid_cafe.get(key, 0.0)
        salida.append({
            "periodo_inicio": start, "periodo_fin": end, "etiqueta": etiqueta, "anio": anio,
            "ventas_totales": round(tot, 2), "cafe_total": round(cof, 2),
            "cafe_pct": round(100 * cof / tot, 2) if tot else 0.0,
            "unidades_totales": round(u_tot, 2), "unidades_cafe": round(u_cof, 2),
            "unidades_cafe_pct": round(100 * u_cof / u_tot, 2) if u_tot else 0.0,
        })
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

    'Cerrado' = cualquier fecha que NO sea la fecha real de HOY (según el
    reloj de esta computadora). Como trabajamos postfactum con
    exportaciones de Wansoft, un día anterior a hoy siempre está
    completo; el día de hoy puede seguir vendiendo, así que nunca entra
    en estas comparaciones (ni como día suelto, ni en la suma semanal)."""
    target = dt.date.fromisoformat(fecha)
    hoy = dt.date.today()
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
