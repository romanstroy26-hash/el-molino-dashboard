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
import math
import unicodedata
from collections import defaultdict

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

import tiempo
from db import get_coffee_keywords, get_plan_produccion

CAFETERIA_TIPOS = {"CAFETERIA", "FRAPPES"}

# Grupos que caen en "Остальные напитки" cuando no son café ni frappé.
# REFRESCOS (refrescos embotellados) es volumen mínimo pero es bebida --
# antes quedaba fuera de "Напитки" por completo; ahora se suma aquí para
# que "Напитки" cubra TODA bebida del menú, no solo CAFETERIA/FRAPPES.
OTRAS_BEBIDAS_TIPOS = {"CAFETERIA", "REFRESCOS"}

# "Bolsa*" -- decisión explícita de Roman: TODA posición que empiece con
# "Bolsa" queda fuera del análisis por posición de menú, sin excepción --
# incluidas las que sí tienen venta real (BOLSA MERENGUES, BOLSA GALLETA
# NUEZ 7 PZ, BOLSA ALGODON CON ASA...), no solo el empaque gratis (BOLSA
# #3/#8/#16, BOLSA BLANCA *, BOLSA CELOFAN *). No son el foco del negocio
# (pan/pastelería/café) y su presencia en ABC/top/tendencias/canasta solo
# distrae. Se usa en TODAS las consultas por posición de menú, no solo en
# Panadería (donde antes vivía este filtro, bajo otro nombre).
EXCLUIR_BOLSA_SQL = " AND platillo NOT LIKE 'BOLSA%'"

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

# Festivos/fechas comerciales de México con peso conocido en panadería y
# cafetería -- NO es la lista completa de días oficiales (un día que no
# mueve la venta de pan no aporta nada al análisis de desviaciones). Con
# fecha FIJA cada año -- (mes, día): nombre.
FESTIVOS_MEXICO_FIJOS: dict[tuple[int, int], str] = {
    (1, 1): "Año Nuevo",
    (1, 6): "Día de Reyes",
    (2, 2): "Día de la Candelaria",
    (2, 14): "Día del Amor y la Amistad",
    (3, 21): "Natalicio de Benito Juárez",
    (4, 30): "Día del Niño",
    (5, 1): "Día del Trabajo",
    (5, 10): "Día de las Madres",
    (9, 16): "Día de la Independencia",
    (11, 1): "Día de Todos los Santos",
    (11, 2): "Día de Muertos",
    (11, 20): "Día de la Revolución",
    (12, 12): "Día de la Virgen de Guadalupe",
    (12, 24): "Nochebuena",
    (12, 25): "Navidad",
    (12, 31): "Fin de Año",
}

# Semana Santa -- fecha MÓVIL (depende de la Pascua), no se puede expresar
# como (mes, día) fijo. Cargado a mano por año -- si la base llega a
# cubrir un año que no está aquí, agregarlo (fechas de Jueves/Viernes
# Santo, fáciles de confirmar en cualquier calendario).
FESTIVOS_MEXICO_MOVILES: dict[str, str] = {
    "2025-04-17": "Jueves Santo",
    "2025-04-18": "Viernes Santo",
    "2026-04-02": "Jueves Santo",
    "2026-04-03": "Viernes Santo",
}


def _festivo_exacto(fecha: dt.date) -> str | None:
    iso = fecha.isoformat()
    if iso in FESTIVOS_MEXICO_MOVILES:
        return FESTIVOS_MEXICO_MOVILES[iso]
    return FESTIVOS_MEXICO_FIJOS.get((fecha.month, fecha.day))


def festivo_cercano(fecha: dt.date, ventana_dias: int = 1) -> dict | None:
    """Festivo mexicano exacto en `fecha`, o hasta `ventana_dias` antes/
    después -- para panadería, el pico de venta muchas veces es la
    VÍSPERA (la rosca de Reyes se compra el 5, no el 6), no el día exacto
    del festivo. Devuelve el más cercano (prioriza el día exacto sobre
    los vecinos), o None si no hay ninguno cerca.

    Esto NO dice si el festivo sube o baja la venta -- solo aporta una
    explicación POSIBLE cuando coincide; la dirección (arriba/abajo) ya
    la sabe quien llama (analizar_desempeno_por_hora ya sabe si el día
    quedó por encima o por debajo del pronóstico)."""
    mejor = None
    for offset in range(-ventana_dias, ventana_dias + 1):
        d = fecha + dt.timedelta(days=offset)
        nombre = _festivo_exacto(d)
        if nombre and (mejor is None or abs(offset) < abs(mejor["dias_diferencia"])):
            mejor = {"nombre": nombre, "fecha_festivo": d.isoformat(), "dias_diferencia": offset}
    return mejor


def is_coffee(platillo: str, tipo_grupo: str, keywords: list[str]) -> bool:
    if tipo_grupo not in CAFETERIA_TIPOS:
        return False
    n = (platillo or "").upper()
    return any(kw in n for kw in keywords)


DIAS_SEMANA_RU = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]


def ultima_carga(engine: Engine) -> str | None:
    """Cuándo se cargó el dato MÁS RECIENTE en la base (columna cargado_en,
    puesta por extractors/wansoft.py al momento de insertar cada fila) --
    para el indicador "datos actualizados hace X" en el sidebar del
    dashboard. Es una señal de DATOS, no de "el vigía sigue vivo": si no
    llegan archivos nuevos de Wansoft, esta fecha no avanza aunque
    vigilar.py esté corriendo perfectamente -- pero eso es justo lo que
    a Roman le interesa saber (¿puedo confiar en que las cifras de hoy
    están al día?), no si un proceso en particular sigue en memoria.

    None si la tabla está vacía. Requiere el índice sobre cargado_en (ver
    db.py, INDICES) -- sin él, MAX() leería la tabla entera por un solo
    número."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT MAX(cargado_en) FROM sales_lines")).scalar_one_or_none()


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

    # Agregado en el SQL por (fecha, tipo_grupo, platillo) -- no fila por
    # fila en Python: sin esto, con el filtro de fechas abierto a toda la
    # historia, esta consulta trae la tabla casi entera (medido: ~48s
    # contra <5s agregado) -- mismo motivo y mismo remedio que
    # cafe_por_sucursal, que ya se reescribió así tras un corte de
    # conexión SSL en un rango grande.
    sql = ("SELECT fecha, tipo_grupo, platillo, "
           "SUM(importe) AS importe, SUM(cantidad) AS cantidad "
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
    sql += " GROUP BY fecha, tipo_grupo, platillo"

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


# Franjas del día -- cubren el horario de operación (6-22, mismo rango
# que el resto del dashboard -- ver plan_tarea_dia). Cuatro bloques
# estándar de restaurante/cafetería (desayuno/comida/merienda/cena), no
# inventados para este negocio en particular -- igual que los umbrales de
# ABC. Lista de tuplas (no dict) porque el ORDEN importa para el gráfico.
# Pública (sin "_") -- dashboard.py la usa para saber el orden y los
# nombres de las franjas al armar el gráfico.
FRANJAS_DIA = [
    ("Утро (6-9)", 6, 9),
    ("Обед (10-14)", 10, 14),
    ("Полдник (15-17)", 15, 17),
    ("Вечер (18-22)", 18, 22),
]


def _franja_de_hora(hora: int) -> str | None:
    for nombre, ini, fin in FRANJAS_DIA:
        if ini <= hora <= fin:
            return nombre
    return None


def ventas_por_franja_dia(engine: Engine, granularidad: str, sucursal: str | None = None,
                           desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """¿Cómo cambia la MEZCLA del día (mañana/mediodía/tarde/noche) con el
    tiempo? -- pregunta que ni patron_horario_bebidas (un patrón promedio
    fijo de TODO el rango) ni patron_semana_por_hora (matriz día×hora, sin
    eje de tiempo) contestan: aquí el eje X es el tiempo -- por ejemplo,
    si la tarde va ganando peso mientras la mañana lo pierde, algo que un
    patrón promedio único no puede mostrar porque ya viene todo mezclado.

    Misma granularidad que serie_por_periodo (día/década/quincena/mes) --
    reutiliza las mismas funciones de período, para que el resto del
    dashboard entienda "década" o "mes" siempre de la misma forma.

    Agregado en el SQL por (fecha, hora) primero -- mismo motivo que
    patron_semana_por_hora: portable entre Postgres/SQLite y ya reduce el
    volumen antes de clasificar franja y período en Python."""
    fn = GRANULARIDADES[granularidad]
    sql = (
        "SELECT fecha, SUBSTR(hora_cierre, 12, 2) AS hora_str, SUM(importe) AS ventas "
        "FROM sales_lines WHERE hora_cierre IS NOT NULL AND hora_cierre != ''"
    )
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
    sql += " GROUP BY fecha, SUBSTR(hora_cierre, 12, 2)"

    por_periodo: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    meta: dict[tuple, tuple] = {}
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            try:
                hora = int(row["hora_str"])
            except (ValueError, TypeError):
                continue
            franja = _franja_de_hora(hora)
            if franja is None:
                continue
            d = dt.date.fromisoformat(row["fecha"])
            start, end, etiqueta = fn(d)
            key = (start, etiqueta)
            meta[key] = (start, end, etiqueta)
            por_periodo[key][franja] += row["ventas"]

    salida = []
    for key in sorted(por_periodo, key=lambda k: k[0]):
        start, end, etiqueta = meta[key]
        datos = por_periodo[key]
        total = sum(datos.values())
        fila = {
            "periodo_inicio": start, "periodo_fin": end, "etiqueta": etiqueta,
            "ventas_totales": round(total, 2),
        }
        for nombre, _, _ in FRANJAS_DIA:
            monto = datos.get(nombre, 0.0)
            fila[nombre] = round(monto, 2)
            fila[f"{nombre}_pct"] = round(100 * monto / total, 1) if total else 0.0
        salida.append(fila)
    return salida


# Bandas de temperatura -- cortes redondos de 5°C, no inventados para
# "cuadrar" con este negocio en particular (mismo espíritu que los
# umbrales de ABC o las franjas del día). Lista de tuplas porque el orden
# importa para el gráfico -- (nombre, desde °C inclusive, hasta °C
# exclusive; None = sin límite en ese extremo).
BANDAS_TEMPERATURA = [
    ("< 20°C", None, 20),
    ("20-25°C", 20, 25),
    ("25-30°C", 25, 30),
    ("> 30°C", 30, None),
]

# Menos de esto días en una banda -- promedio poco confiable (un solo día
# raro decide "el promedio" de toda la banda). Se omite esa banda entera
# antes que mostrar un número que parece sólido y no lo es.
_MIN_DIAS_BANDA_TEMPERATURA = 3


def _banda_de_temp(temp: float | None) -> str | None:
    if temp is None:
        return None
    for nombre, ini, fin in BANDAS_TEMPERATURA:
        if (ini is None or temp >= ini) and (fin is None or temp < fin):
            return nombre
    return None


def ventas_por_banda_temperatura(dias_datos: list[dict], clima_datos: list[dict],
                                  campo: str) -> list[dict] | None:
    """Promedio de `campo` (por ejemplo frappe_pct o ventas_totales, del
    resultado de serie_por_periodo con granularidad "dia") agrupado por
    banda de temperatura máxima de ese día (ver BANDAS_TEMPERATURA) --
    para la pregunta "¿se comportan distinto los días calurosos, EN
    GENERAL?" sin que nadie tenga que leer un scatter plot o un
    coeficiente de correlación -- solo el promedio simple por banda.

    Es una COINCIDENCIA observada, no una causa probada -- mismo
    principio que festivo_cercano/clima.clima_dia en el resto del
    dashboard: se muestra el patrón, la explicación queda para quien lee.

    Función PURA (sin acceso a la base ni a la red) -- junta dos listas
    ya cargadas, por fecha. None si no hay suficiente cruce entre las
    dos series como para formar ni una sola banda con
    _MIN_DIAS_BANDA_TEMPERATURA días."""
    temp_por_fecha = {d["fecha"]: d.get("temp_max") for d in clima_datos}

    por_banda: dict[str, list[float]] = defaultdict(list)
    for d in dias_datos:
        valor = d.get(campo)
        if valor is None:
            continue
        banda = _banda_de_temp(temp_por_fecha.get(d["fecha"]))
        if banda is None:
            continue
        por_banda[banda].append(valor)

    salida = []
    for nombre, _, _ in BANDAS_TEMPERATURA:
        valores = por_banda.get(nombre, [])
        if len(valores) < _MIN_DIAS_BANDA_TEMPERATURA:
            continue
        salida.append({
            "banda": nombre, "n_dias": len(valores),
            "promedio": round(sum(valores) / len(valores), 2),
        })
    return salida or None


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
    que Wansoft empezara a guardar el número de chequeo) quedan fuera.

    Agregado en el SQL por (hora, tipo_grupo, platillo) -- no fila por fila
    en Python (mismo motivo y mismo remedio que cafe_por_sucursal: en un
    rango grande esto traía la tabla casi entera). SUBSTR(hora_cierre, 12,
    2) -- mismo truco portable Postgres/SQLite que patron_horario_panaderia
    para sacar la hora sin fila por fila."""
    keywords = [row["palabra"] for row in get_coffee_keywords(engine)]

    sql = ("SELECT SUBSTR(hora_cierre, 12, 2) AS hora_str, tipo_grupo, platillo, "
           "SUM(importe) AS importe, SUM(cantidad) AS cantidad "
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
    sql += " GROUP BY SUBSTR(hora_cierre, 12, 2), tipo_grupo, platillo"

    cafe = defaultdict(float)
    frappe = defaultdict(float)
    otras = defaultdict(float)
    u_cafe = defaultdict(float)
    u_frappe = defaultdict(float)
    u_otras = defaultdict(float)

    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            try:
                hora = int(row["hora_str"])
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
    parejo entre sabores o lo carga un solo producto nuevo.

    Agregado en el SQL por (tipo_grupo, platillo) -- no fila por fila en
    Python (mismo motivo y mismo remedio que cafe_por_sucursal)."""
    keywords = [row["palabra"] for row in get_coffee_keywords(engine)]

    sql = ("SELECT tipo_grupo, platillo, SUM(importe) AS importe, SUM(cantidad) AS cantidad "
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
    sql += " GROUP BY tipo_grupo, platillo"

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

    # Agregado en el SQL por (sucursal, tipo_grupo, platillo) -- no fila
    # por fila en Python: sin esto, esta consulta trae TODA la tabla (sin
    # filtro de sucursal ni de tipo_grupo, a propósito, para comparar
    # todas las sucursales de una vez) -- con las ~900 mil líneas que ya
    # tiene la base, el driver de Postgres llegó a cortar la conexión a
    # mitad de la descarga (SSL error). Agrupado por posición de menú son
    # unos pocos cientos/miles de filas, no cientos de miles -- is_coffee
    # sigue clasificando por platillo/tipo_grupo, solo que ya agregado.
    sql = ("SELECT sucursal, tipo_grupo, platillo, "
           "SUM(importe) AS importe, SUM(cantidad) AS cantidad "
           "FROM sales_lines WHERE 1=1")
    params: dict = {}
    if desde:
        sql += " AND fecha >= :desde"
        params["desde"] = desde
    if hasta:
        sql += " AND fecha <= :hasta"
        params["hasta"] = hasta
    sql += " GROUP BY sucursal, tipo_grupo, platillo"

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
    fechas (todas las categorías, no solo café -- 'ventas completas').
    Excluye "Bolsa*" (ver EXCLUIR_BOLSA_SQL) -- no son el foco del
    negocio, decisión explícita de Roman."""
    where, params = _filtro_rango_sql(sucursal, desde, hasta)
    sql = "SELECT platillo, tipo_grupo, importe, cantidad FROM sales_lines" + where + EXCLUIR_BOLSA_SQL

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


def analisis_abc(engine: Engine, sucursal: str | None = None, desde: str | None = None,
                  hasta: str | None = None) -> dict:
    """ABC/Pareto de posiciones de menú por ingresos -- la pregunta que el
    top-15 de "Топ товаров" no contesta: "¿cuántas posiciones concentran
    cuánta venta?" (para decidir qué NO conviene quitar del menú, y qué sí
    se puede recortar sin perder casi nada). Umbrales estándar de Pareto,
    no inventados para este negocio: A = hasta 80% acumulado, B = 80-95%,
    C = el resto.

    Excluye "Bolsa*" (ver EXCLUIR_BOLSA_SQL) -- no son el foco del
    negocio, decisión explícita de Roman.

    Agregado en SQL (GROUP BY platillo), no fila por fila -- mismo motivo
    que el resto de funciones de este archivo con tablas grandes."""
    where, params = _filtro_rango_sql(sucursal, desde, hasta)
    sql = ("SELECT platillo, SUM(importe) AS ventas, SUM(cantidad) AS unidades "
           "FROM sales_lines" + where + EXCLUIR_BOLSA_SQL + " GROUP BY platillo")
    with engine.connect() as conn:
        filas = [dict(r) for r in conn.execute(text(sql), params).mappings()]

    total_ventas = sum(f["ventas"] for f in filas)
    filas.sort(key=lambda f: f["ventas"], reverse=True)

    acumulado = 0.0
    detalle = []
    for f in filas:
        acumulado += f["ventas"]
        pct_acumulado = round(100 * acumulado / total_ventas, 1) if total_ventas else 0.0
        clase = "A" if pct_acumulado <= 80 else ("B" if pct_acumulado <= 95 else "C")
        detalle.append({
            "platillo": f["platillo"] or "(без названия)",
            "ventas": round(f["ventas"], 2),
            "unidades": round(f["unidades"], 2),
            "pct_acumulado": pct_acumulado,
            "clase": clase,
        })

    clases = {}
    for clase in ("A", "B", "C"):
        items_clase = [d for d in detalle if d["clase"] == clase]
        ventas_clase = sum(d["ventas"] for d in items_clase)
        clases[clase] = {
            "n_posiciones": len(items_clase),
            "pct_posiciones": round(100 * len(items_clase) / len(detalle), 1) if detalle else 0.0,
            "ventas": round(ventas_clase, 2),
            "pct_ventas": round(100 * ventas_clase / total_ventas, 1) if total_ventas else 0.0,
        }

    return {
        "total_ventas": round(total_ventas, 2),
        "n_posiciones_total": len(detalle),
        "clases": clases,
        "detalle": detalle,
    }


# Ventana usada para comparar "ahora" contra "antes" en platillos_en_tendencia
# -- 14 días (dos semanas completas) en vez de 7: una sola semana es más
# sensible a qué día cayó un feriado o un clima raro; dos semanas promedian
# ese ruido sin diluir tanto el cambio real como para dejar de verlo.
_DIAS_TENDENCIA = 14


def platillos_en_tendencia(engine: Engine, sucursal: str | None = None, hasta: str | None = None,
                            dias: int = _DIAS_TENDENCIA, n: int = 8) -> dict:
    """¿Qué posiciones de menú están CRECIENDO o CAYENDO ahora mismo,
    comparando los últimos `dias` días contra los `dias` inmediatamente
    anteriores? -- pregunta que analisis_abc (arriba) no contesta: ABC es
    una foto fija de todo el rango (qué posiciones pesan), esto es la
    PELÍCULA (qué posiciones están cambiando de peso ahora mismo, antes de
    que el cambio se note en el ABC del mes completo).

    Solo se consideran posiciones de clase A o B (ver analisis_abc) sobre
    la ventana combinada -- una posición de clase C (cola larga, casi sin
    venta) puede mostrar un cambio de +300% con una sola venta de más, sin
    que signifique nada para el negocio; filtrar a A/B deja solo cambios
    que sí pesan en la caja.

    También devuelve, aparte, "nuevas" -- posiciones con CERO venta en el
    período pasado y venta ya relevante (clase A/B) en el actual: la
    comparación porcentual de arriba no puede mostrarlas (dividir entre
    cero), así que sin esto quedarían invisibles -- justo las que más
    interesa ver (una posición de menú nueva, o reactivada, que ya está
    vendiendo bien)."""
    hasta_date = dt.date.fromisoformat(hasta) if hasta else (tiempo.hoy() - dt.timedelta(days=1))
    fin_actual = hasta_date
    ini_actual = fin_actual - dt.timedelta(days=dias - 1)
    fin_pasado = ini_actual - dt.timedelta(days=1)
    ini_pasado = fin_pasado - dt.timedelta(days=dias - 1)

    abc = analisis_abc(engine, sucursal=sucursal, desde=ini_pasado.isoformat(), hasta=fin_actual.isoformat())
    relevantes = {d["platillo"] for d in abc["detalle"] if d["clase"] in ("A", "B")}

    sql = (
        "SELECT platillo, "
        "SUM(CASE WHEN fecha >= :ini_actual THEN importe ELSE 0 END) AS ventas_actual, "
        "SUM(CASE WHEN fecha < :ini_actual THEN importe ELSE 0 END) AS ventas_pasada "
        "FROM sales_lines WHERE fecha >= :ini_pasado AND fecha <= :fin_actual" + EXCLUIR_BOLSA_SQL
    )
    params: dict = {
        "ini_actual": ini_actual.isoformat(), "ini_pasado": ini_pasado.isoformat(),
        "fin_actual": fin_actual.isoformat(),
    }
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    sql += " GROUP BY platillo"

    filas = []
    nuevas = []
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            clave = row["platillo"] or "(без названия)"
            if clave not in relevantes:
                continue
            ventas_actual = row["ventas_actual"] or 0.0
            ventas_pasada = row["ventas_pasada"] or 0.0
            if ventas_pasada == 0.0:
                if ventas_actual > 0:
                    nuevas.append({"platillo": clave, "ventas_actual": round(ventas_actual, 2)})
                continue
            cambio_pct = _delta_pct(ventas_actual, ventas_pasada)
            filas.append({
                "platillo": clave,
                "ventas_actual": round(ventas_actual, 2),
                "ventas_pasada": round(ventas_pasada, 2),
                "cambio_pct": cambio_pct,
            })

    filas.sort(key=lambda f: f["cambio_pct"], reverse=True)
    subiendo = [f for f in filas if f["cambio_pct"] > 0][:n]
    bajando = sorted((f for f in filas if f["cambio_pct"] < 0), key=lambda f: f["cambio_pct"])[:n]
    nuevas.sort(key=lambda f: f["ventas_actual"], reverse=True)

    return {
        "desde_actual": ini_actual.isoformat(), "hasta_actual": fin_actual.isoformat(),
        "desde_pasado": ini_pasado.isoformat(), "hasta_pasado": fin_pasado.isoformat(),
        "dias": dias, "subiendo": subiendo, "bajando": bajando, "nuevas": nuevas[:n],
    }


def platillos_acompanantes(engine: Engine, sucursal: str, platillo: str, desde: str | None = None,
                            hasta: str | None = None, n: int = 8) -> dict | None:
    """Con qué OTRAS posiciones aparece más seguido `platillo` en el MISMO
    chequeo (ticket) -- pregunta que ningún top de ventas por separado
    contesta, porque esos miran cada posición sola, no el chequeo
    completo. Sirve para sugerencias de venta cruzada en mostrador
    ("¿le agrego un X?").

    Requiere UNA sucursal concreta (no None/"todas") -- el número de
    chequeo (movimiento_pdv) es único DENTRO de una sucursal pero se
    repite ENTRE sucursales (ver comentario en db.py, tabla sales_lines);
    mezclar las dos sin distinguir juntaría, por accidente, chequeos de
    negocios distintos que comparten número.

    "Bolsa*" nunca aparece como acompañante (casi cualquier compra lleva
    una -- eso no es una sugerencia útil de venta cruzada, es ruido) ni
    como ancla (si `platillo` mismo es "Bolsa*", no hay nada que analizar
    -- devuelve None).

    Self-join agregado en SQL (no fila por fila en Python) -- mismo motivo
    que el resto de funciones sobre esta tabla: cientos de miles de filas
    es demasiado para traer completas solo para contar coincidencias."""
    sql_total = (
        "SELECT COUNT(DISTINCT movimiento_pdv) AS n FROM sales_lines "
        "WHERE sucursal = :sucursal AND platillo = :platillo AND movimiento_pdv IS NOT NULL"
        + EXCLUIR_BOLSA_SQL
    )
    params_total: dict = {"sucursal": sucursal, "platillo": platillo}
    if desde:
        sql_total += " AND fecha >= :desde"
        params_total["desde"] = desde
    if hasta:
        sql_total += " AND fecha <= :hasta"
        params_total["hasta"] = hasta

    sql_juntos = (
        "SELECT b.platillo AS platillo, COUNT(DISTINCT a.movimiento_pdv) AS n_tickets "
        "FROM sales_lines a JOIN sales_lines b "
        "ON a.sucursal = b.sucursal AND a.movimiento_pdv = b.movimiento_pdv "
        "WHERE a.sucursal = :sucursal AND a.platillo = :platillo "
        "AND a.movimiento_pdv IS NOT NULL AND b.platillo != :platillo "
        "AND b.platillo NOT LIKE 'BOLSA%'"
    )
    params_juntos: dict = {"sucursal": sucursal, "platillo": platillo}
    if desde:
        sql_juntos += " AND a.fecha >= :desde"
        params_juntos["desde"] = desde
    if hasta:
        sql_juntos += " AND a.fecha <= :hasta"
        params_juntos["hasta"] = hasta
    sql_juntos += " GROUP BY b.platillo"

    with engine.connect() as conn:
        n_tickets_total = conn.execute(text(sql_total), params_total).scalar_one()
        if not n_tickets_total:
            return None
        filas = [
            {
                "platillo": row["platillo"] or "(без названия)",
                "n_tickets_juntos": row["n_tickets"],
                "pct_de_tickets": round(100 * row["n_tickets"] / n_tickets_total, 1),
            }
            for row in conn.execute(text(sql_juntos), params_juntos).mappings()
        ]

    filas.sort(key=lambda f: f["n_tickets_juntos"], reverse=True)
    return {"platillo": platillo, "n_tickets_total": n_tickets_total, "acompanantes": filas[:n]}


def serie_dia_por_sucursal(engine: Engine, desde: str, hasta: str) -> list[dict]:
    """Ventas totales por DÍA y por SUCURSAL en el rango -- para comparar
    la TENDENCIA de cada punto lado a lado (no solo un día, como
    resumen_dia_por_sucursal, que es de la página "Главная"). Siempre
    TODAS las sucursales -- no tiene filtro de punto, es justamente para
    compararlos."""
    sql = ("SELECT fecha, sucursal, SUM(importe) AS ventas_totales FROM sales_lines "
           "WHERE fecha >= :desde AND fecha <= :hasta GROUP BY fecha, sucursal")
    with engine.connect() as conn:
        filas = [
            {"fecha": r["fecha"], "sucursal": r["sucursal"], "ventas_totales": round(r["ventas_totales"], 2)}
            for r in conn.execute(text(sql), {"desde": desde, "hasta": hasta}).mappings()
        ]
    filas.sort(key=lambda r: (r["fecha"], r["sucursal"]))
    return filas


def patron_semana_por_hora(engine: Engine, sucursal: str | None = None, desde: str | None = None,
                            hasta: str | None = None) -> list[dict]:
    """Ventas y unidades sumadas por (día de semana, hora), con TODAS las
    categorías del menú -- la matriz completa de tráfico (mapa de calor),
    no un patrón promedio de un solo día como patron_horario_bebidas o
    patron_horario_panaderia (esas son por categoría; esta es el negocio
    completo, pensada para decidir HORARIOS DE PERSONAL, no producción de
    una sola categoría). Requiere hora_cierre -- igual que el resto de
    patrones por hora, filas viejas sin hora quedan fuera.

    Agregado en el SQL por (fecha, hora) primero -- no directo por (día de
    semana, hora): eso necesitaría una función de fecha específica de cada
    motor (Postgres vs SQLite). Agregar por fecha es portable y ya reduce
    de cientos de miles de filas a unos pocos miles antes de clasificar el
    día de semana en Python (mismo truco que patron_horario_panaderia)."""
    sql = (
        "SELECT fecha, SUBSTR(hora_cierre, 12, 2) AS hora_str, "
        "SUM(importe) AS ventas, SUM(cantidad) AS unidades "
        "FROM sales_lines WHERE hora_cierre IS NOT NULL AND hora_cierre != ''"
    )
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
    sql += " GROUP BY fecha, SUBSTR(hora_cierre, 12, 2)"

    ventas: dict[tuple[int, int], float] = defaultdict(float)
    unidades: dict[tuple[int, int], float] = defaultdict(float)
    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            try:
                hora = int(row["hora_str"])
            except (ValueError, TypeError):
                continue
            weekday = dt.date.fromisoformat(row["fecha"]).weekday()
            ventas[(weekday, hora)] += row["ventas"]
            unidades[(weekday, hora)] += row["unidades"]

    return [
        {
            "dia_semana_idx": wd, "dia_semana": DIAS_SEMANA_RU[wd], "hora": h,
            "ventas": round(ventas.get((wd, h), 0.0), 2),
            "unidades": round(unidades.get((wd, h), 0.0), 2),
        }
        for wd in range(7) for h in range(24)
    ]


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

    sql = ("SELECT tipo_grupo, platillo, importe, cantidad, movimiento_pdv "
           "FROM sales_lines WHERE fecha = :fecha")
    params: dict = {"fecha": fecha}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal

    ventas_totales = 0.0
    unidades_totales = 0.0
    ordenes: set = set()
    por_categoria: dict[str, float] = defaultdict(float)

    with engine.connect() as conn:
        for row in conn.execute(text(sql), params).mappings():
            ventas_totales += row["importe"]
            unidades_totales += row["cantidad"] or 0
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
        "unidades_totales": round(unidades_totales, 2),
        "unidades_por_cheque": round(unidades_totales / num_ordenes, 2) if num_ordenes else 0.0,
        "categorias": categorias,
    }


def resumen_dia_por_sucursal(engine: Engine, fecha: str) -> list[dict]:
    """resumen_dia, pero para TODAS las sucursales a la vez, una fila por
    punto -- para comparar "quién cómo le fue hoy" en la página "Главная"
    sin cambiar el filtro de la página (que sigue controlando la tarjeta
    principal). Solo lo esencial (ventas, cheques, ticket) -- el desglose
    por categoría ya está arriba, para la sucursal elegida."""
    sql = ("SELECT sucursal, COUNT(DISTINCT movimiento_pdv) AS num_ordenes, "
           "SUM(importe) AS ventas_totales FROM sales_lines "
           "WHERE fecha = :fecha GROUP BY sucursal")
    with engine.connect() as conn:
        filas = list(conn.execute(text(sql), {"fecha": fecha}).mappings())
    salida = [
        {
            "sucursal": f["sucursal"],
            "num_ordenes": f["num_ordenes"],
            "ventas_totales": round(f["ventas_totales"], 2),
            "cheque_promedio": round(f["ventas_totales"] / f["num_ordenes"], 2) if f["num_ordenes"] else 0.0,
        }
        for f in filas
    ]
    salida.sort(key=lambda r: r["ventas_totales"], reverse=True)
    return salida


# Una categoría que se movió menos de esto (en puntos porcentuales) contra
# lo típico de ese día de semana no vale la pena destacarla -- es la
# variación normal de un día a otro, no algo que merezca una frase aparte.
_UMBRAL_DIF_CATEGORIA_PT = 5.0


def analizar_mezcla_categorias(resumen: dict) -> dict | None:
    """¿Alguna categoría (Panadería/Pastelería/Café/Остальное) se movió más
    de lo normal hoy, comparado con lo típico de ese día de semana (ver
    resumen_dia_con_tipico)? Devuelve la que más se movió si pasa
    _UMBRAL_DIF_CATEGORIA_PT, o None si ninguna se movió lo suficiente
    para que valga la pena mencionarla."""
    candidatas = [c for c in resumen.get("categorias", []) if c.get("dif_pt") is not None]
    if not candidatas:
        return None
    peor = max(candidatas, key=lambda c: abs(c["dif_pt"]))
    if abs(peor["dif_pt"]) < _UMBRAL_DIF_CATEGORIA_PT:
        return None
    return {
        "categoria": peor["categoria"], "pct": peor["pct"], "tipico_pct": peor["tipico_pct"],
        "dif_pt": peor["dif_pt"], "festivo": resumen.get("festivo"),
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


def serie_dia_resumen(engine: Engine, desde: str, hasta: str,
                       sucursal: str | None = None) -> list[dict]:
    """Lo mismo que resumen_dia, pero para CADA día de un rango -- fuente
    para las mini-tendencias (sparklines) y para calcular "lo típico de
    este día de semana" en la página "Главная" (ver resumen_dia_con_tipico).

    Dos consultas, ambas agregadas en SQL (GROUP BY), no fila por fila:
      - cheques (movimiento_pdv únicos) y ventas totales, por fecha --
        agregable directo, no depende de la clasificación por categoría.
      - ventas por (fecha, tipo_grupo, platillo) -- el mínimo detalle que
        necesita is_coffee() para clasificar, agregado de todas formas
        (miles de filas, no millones, incluso con 90 días de rango)."""
    keywords = [row["palabra"] for row in get_coffee_keywords(engine)]

    sql_totales = ("SELECT fecha, COUNT(DISTINCT movimiento_pdv) AS num_ordenes, "
                   "SUM(importe) AS ventas_totales, SUM(cantidad) AS unidades_totales "
                   "FROM sales_lines "
                   "WHERE fecha >= :desde AND fecha <= :hasta")
    params: dict = {"desde": desde, "hasta": hasta}
    if sucursal:
        sql_totales += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    sql_totales += " GROUP BY fecha"

    sql_cat = ("SELECT fecha, tipo_grupo, platillo, SUM(importe) AS importe "
               "FROM sales_lines WHERE fecha >= :desde AND fecha <= :hasta")
    if sucursal:
        sql_cat += " AND sucursal = :sucursal"
    sql_cat += " GROUP BY fecha, tipo_grupo, platillo"

    totales: dict[str, dict] = {}
    with engine.connect() as conn:
        for row in conn.execute(text(sql_totales), params).mappings():
            totales[row["fecha"]] = {
                "num_ordenes": row["num_ordenes"], "ventas_totales": row["ventas_totales"],
                "unidades_totales": row["unidades_totales"] or 0.0,
            }

    por_categoria: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    with engine.connect() as conn:
        for row in conn.execute(text(sql_cat), params).mappings():
            tg = (row["tipo_grupo"] or "").upper()
            if is_coffee(row["platillo"], row["tipo_grupo"], keywords):
                cat = "Café"
            elif tg == "PANADERIA":
                cat = "Panadería"
            elif tg == "PASTELERIA":
                cat = "Pastelería"
            else:
                cat = "Остальное"
            por_categoria[row["fecha"]][cat] += row["importe"]

    salida = []
    for fecha, t in sorted(totales.items()):
        ventas_totales = t["ventas_totales"]
        num_ordenes = t["num_ordenes"]
        unidades_totales = t["unidades_totales"]
        cats_dia = por_categoria.get(fecha, {})

        def _pct(cat: str) -> float:
            return round(100 * cats_dia.get(cat, 0.0) / ventas_totales, 1) if ventas_totales else 0.0

        salida.append({
            "fecha": fecha,
            "num_ordenes": num_ordenes,
            "ventas_totales": round(ventas_totales, 2),
            "cheque_promedio": round(ventas_totales / num_ordenes, 2) if num_ordenes else 0.0,
            "unidades_totales": round(unidades_totales, 2),
            "unidades_por_cheque": round(unidades_totales / num_ordenes, 2) if num_ordenes else 0.0,
            "panaderia_pct": _pct("Panadería"),
            "pasteleria_pct": _pct("Pastelería"),
            "cafe_pct": _pct("Café"),
            "otras_pct": _pct("Остальное"),
        })
    return salida


def _tipico_recencia(valores_por_fecha: dict[dt.date, float], target: dt.date) -> float | None:
    """Promedio ponderado por recencia del MISMO día de semana que
    `target` (nunca incluye `target` mismo), con outliers suavizados --
    mismo método que panaderia_real_y_pronostico/ventas_por_hora,
    generalizado aquí para cualquier serie diaria (ventas, ticket
    promedio, % de categoría...), no solo unidades de Panadería."""
    historicos = [
        (f, v) for f, v in valores_por_fecha.items()
        if f.weekday() == target.weekday() and f != target
    ]
    if not historicos:
        return None
    valores = _recortar_atipicos([v for _, v in historicos])
    pesos = [_peso_recencia(f, target) for f, _ in historicos]
    peso_total = sum(pesos)
    if not peso_total:
        return None
    return sum(v * p for v, p in zip(valores, pesos)) / peso_total


# Días máximos hacia atrás que se revisan para la racha -- una racha más
# larga que esto ya es un cambio de tendencia sostenido, no algo que
# necesite destacarse como "racha" puntual en la página "Главная".
_RACHA_MAX_DIAS = 14


def _racha_desviacion(valores_por_fecha: dict[dt.date, float], target: dt.date) -> dict | None:
    """Cuántos días SEGUIDOS (terminando en `target`, contando hacia
    atrás) quedaron del MISMO lado (arriba o abajo) de lo típico para su
    propio día de semana -- una racha de varios días en la misma
    dirección es una señal de tendencia más fuerte que comparar un solo
    día contra la semana pasada (que ya existe en el panel "День к дню").
    Reutiliza `valores_por_fecha` ya cargado (sin consultas nuevas a la
    base) -- por eso vive junto a _tipico_recencia, que usa el mismo
    diccionario. None si la racha es de 1 día o menos (nada que destacar)
    o si no hay suficiente historial."""
    racha = 0
    direccion = None
    d = target
    for _ in range(_RACHA_MAX_DIAS):
        real = valores_por_fecha.get(d)
        if real is None:
            break
        tipico = _tipico_recencia(valores_por_fecha, d)
        if not tipico:
            break
        delta_pct = 100 * (real - tipico) / tipico
        if abs(delta_pct) < _UMBRAL_DESVIACION_PCT:
            break
        lado = "por_encima" if delta_pct > 0 else "por_debajo"
        if direccion is None:
            direccion = lado
        elif lado != direccion:
            break
        racha += 1
        d -= dt.timedelta(days=1)
    if racha < 2:
        return None
    return {"dias": racha, "direccion": direccion}


_DIAS_HISTORIA_TIPICO_DIA = 90


def resumen_dia_con_tipico(engine: Engine, fecha: str, sucursal: str | None = None) -> dict:
    """resumen_dia + "¿es esto normal para un {día de semana}?" -- sin
    esto, la página "Главная" muestra números sueltos sin con qué
    compararlos (un lunes con 54.5% Panadería, ¿es alto o el de siempre?).
    Añade, sobre el mismo resumen:
      - tipico_ventas_totales / ventas_vs_tipico_pct
      - tipico_cheque_promedio / cheque_vs_tipico_pct
      - tipico_unidades_por_cheque / unidades_por_cheque_vs_tipico_pct -- el
        MISMO chequeo promedio, pero en piezas en vez de pesos: un chequeo
        puede crecer en dinero por vender más piezas, o solo por vender
        piezas más caras -- esto separa las dos causas.
      - por cada categoría: tipico_pct / dif_pt (puntos porcentuales)
      - serie_reciente -- los últimos días del rango de historia, para
        dibujar mini-tendencias (sparklines) en el dashboard.

    "Típico" sale de _DIAS_HISTORIA_TIPICO_DIA días ANTES de `fecha`,
    filtrado al mismo día de semana y ponderado por recencia (ver
    _tipico_recencia) -- igual que el resto de pronósticos de este
    archivo, no una comparación inventada aparte."""
    resumen = resumen_dia(engine, fecha, sucursal=sucursal)
    target = dt.date.fromisoformat(fecha)
    desde_historia = (target - dt.timedelta(days=_DIAS_HISTORIA_TIPICO_DIA)).isoformat()
    hasta_historia = (target - dt.timedelta(days=1)).isoformat()
    serie = serie_dia_resumen(engine, desde_historia, hasta_historia, sucursal=sucursal)

    ventas_por_fecha = {dt.date.fromisoformat(d["fecha"]): d["ventas_totales"] for d in serie}
    ordenes_por_fecha = {dt.date.fromisoformat(d["fecha"]): d["num_ordenes"] for d in serie}
    ticket_por_fecha = {
        dt.date.fromisoformat(d["fecha"]): d["cheque_promedio"] for d in serie if d["num_ordenes"]
    }
    unidades_cheque_por_fecha = {
        dt.date.fromisoformat(d["fecha"]): d["unidades_por_cheque"] for d in serie if d["num_ordenes"]
    }

    tipico_ventas = _tipico_recencia(ventas_por_fecha, target)
    tipico_ordenes = _tipico_recencia(ordenes_por_fecha, target)
    tipico_ticket = _tipico_recencia(ticket_por_fecha, target)
    tipico_unidades_cheque = _tipico_recencia(unidades_cheque_por_fecha, target)

    resumen["tipico_ventas_totales"] = round(tipico_ventas, 2) if tipico_ventas is not None else None
    resumen["ventas_vs_tipico_pct"] = (
        _delta_pct(resumen["ventas_totales"], tipico_ventas) if tipico_ventas else None
    )
    resumen["tipico_num_ordenes"] = round(tipico_ordenes, 1) if tipico_ordenes is not None else None
    resumen["ordenes_vs_tipico_pct"] = (
        _delta_pct(resumen["num_ordenes"], tipico_ordenes) if tipico_ordenes else None
    )
    resumen["tipico_cheque_promedio"] = round(tipico_ticket, 2) if tipico_ticket is not None else None
    resumen["cheque_vs_tipico_pct"] = (
        _delta_pct(resumen["cheque_promedio"], tipico_ticket) if tipico_ticket else None
    )
    resumen["tipico_unidades_por_cheque"] = (
        round(tipico_unidades_cheque, 2) if tipico_unidades_cheque is not None else None
    )
    resumen["unidades_por_cheque_vs_tipico_pct"] = (
        _delta_pct(resumen["unidades_por_cheque"], tipico_unidades_cheque)
        if tipico_unidades_cheque else None
    )

    campo_pct = {
        "Panadería": "panaderia_pct", "Pastelería": "pasteleria_pct",
        "Café": "cafe_pct", "Остальное": "otras_pct",
    }
    for cat in resumen["categorias"]:
        campo = campo_pct.get(cat["categoria"])
        valores_cat = (
            {dt.date.fromisoformat(d["fecha"]): d[campo] for d in serie} if campo else {}
        )
        tipico_pct = _tipico_recencia(valores_cat, target) if valores_cat else None
        cat["tipico_pct"] = round(tipico_pct, 1) if tipico_pct is not None else None
        cat["dif_pt"] = round(cat["pct"] - tipico_pct, 1) if tipico_pct is not None else None

    # Racha -- solo tiene sentido para un día YA CERRADO (un día abierto
    # compararía ventas de medio día contra lo típico de un día
    # completo, la misma trampa ya resuelta para ventas_vs_tipico_pct
    # arriba). Se agrega el día de hoy al diccionario -- serie_dia_resumen
    # ya trae todo lo ANTERIOR, pero no el día que se está resumiendo.
    if resumen["dia_cerrado"]:
        ventas_por_fecha[target] = resumen["ventas_totales"]
        resumen["racha"] = _racha_desviacion(ventas_por_fecha, target)
    else:
        resumen["racha"] = None

    # Últimos 14 días de la ventana de historia -- suficientes para una
    # sparkline legible sin saturarla de puntos.
    resumen["serie_reciente"] = serie[-14:]
    resumen["festivo"] = festivo_cercano(target)
    return resumen


def panaderia_real_y_pronostico(engine: Engine, desde: str, hasta: str,
                                 sucursal: str | None = None,
                                 categorias: tuple[str, ...] = ("PANADERIA",)) -> list[dict]:
    """Producción de Panadería (unidades) DÍA por día, para la página
    "Планирование" -- compara "cuánto se vendió" contra "cuánto se
    esperaba vender" y (aparte, en la tabla de plan_produccion) contra
    "cuánto se planeó producir". Mismo método que el pronóstico por hora de
    ventas_por_hora (promedio del mismo día de semana, ponderado por
    recencia -- ver _peso_recencia --, con outliers suavizados -- ver
    _recortar_atipicos), pero agregando POR DÍA COMPLETO en vez de por
    hora, y solo tipo_grupo en `categorias` (por defecto solo PANADERIA)
    en vez de todo el menú.

    `categorias` -- qué tipo_grupo incluir. Por defecto solo Panadería
    (como el resto de "Планирование"); el gráfico "Физический план vs
    факт" pasa ("PANADERIA", "PASTELERIA") para que el pronóstico cubra
    LO MISMO que el plan físico en papel (que junta ambas categorías).

    desde/hasta puede incluir fechas FUTURAS (para planear producción de
    días que todavía no pasaron) -- ahí "real_unidades" sale None (no hay
    venta todavía), pero "pronostico_unidades" sí se calcula igual, a
    partir de todo el historial disponible del mismo día de semana."""
    # Agregado en el SQL (GROUP BY fecha), no fila por fila en Python -- esta
    # tabla tiene cientos de miles de líneas de Panadería; traerlas todas
    # para sumar en Python tardaba ~30s por el tráfico de red hacia la base
    # en la nube, contra <1s agregando del lado del servidor.
    sql = ("SELECT fecha, SUM(cantidad) AS total FROM sales_lines "
           "WHERE tipo_grupo = ANY(:categorias)" + EXCLUIR_BOLSA_SQL)
    params: dict = {"categorias": list(categorias)}
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
           "FROM sales_lines WHERE tipo_grupo = 'PANADERIA'" + EXCLUIR_BOLSA_SQL)
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
           "AND hora_cierre != ''" + EXCLUIR_BOLSA_SQL)
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


# Personal fijo por turno -- todavía no hay horario de turnos en la base
# (ni fuente externa para eso), así que se usa directamente el número que
# dio Roman en la conversación: 5 personas entre semana y sábado, 6 los
# domingos, igual en TODAS las horas del día (el personal no varía por
# hora en este modelo, solo por día de la semana). Si el personal real
# cambia, o empieza a variar por punto/hora, esta es la constante a
# tocar -- por ahora es la ÚNICA fuente de este dato.
PERSONAL_ENTRE_SEMANA = 5
PERSONAL_DOMINGO = 6


def personal_del_dia(fecha: dt.date) -> int:
    return PERSONAL_DOMINGO if fecha.weekday() == 6 else PERSONAL_ENTRE_SEMANA


def carga_por_hora_panaderia(engine: Engine, sucursal: str | None = None,
                              desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """patron_horario_panaderia (unidades por hora, sumadas en TODO el
    rango) dividido entre el personal disponible -- responde la pregunta
    real detrás de "¿cuántas unidades por hora?": ¿esa carga es mucha o
    poca PARA LA GENTE QUE HAY?

    El personal es constante durante todo el día (ver personal_del_dia) --
    por eso el total de persona-horas disponibles para cualquier hora del
    día, sumado en todo el rango, es EL MISMO número (la suma del
    personal de cada día del rango): a las 8am hay tantas personas
    trabajando como a las 8pm. Así, unidades_por_persona de la hora H =
    unidades de esa hora (sumadas en el rango) / ese mismo total -- sin
    necesitar saber turnos por hora, que no existen en la base."""
    horas = patron_horario_panaderia(engine, sucursal=sucursal, desde=desde, hasta=hasta)

    personal_dias_total = 0
    if desde and hasta:
        d = dt.date.fromisoformat(desde)
        fin = dt.date.fromisoformat(hasta)
        while d <= fin:
            personal_dias_total += personal_del_dia(d)
            d += dt.timedelta(days=1)

    for h in horas:
        h["unidades_por_persona"] = (
            round(h["unidades"] / personal_dias_total, 2) if personal_dias_total else 0.0
        )
    return horas


def _redondear_a_multiplo(valor: float, base: int) -> int:
    """Redondea HACIA ARRIBA al múltiplo de `base` más cercano -- para un
    plan de producción por charolas/lotes (p. ej. 6 piezas por charola),
    quedarse corto de una charola completa (redondear hacia abajo o al más
    cercano) significa faltante real en el mostrador; sobrar un poco de
    algún producto es preferible a que falte."""
    if valor <= 0 or base <= 0:
        return 0
    return math.ceil(valor / base) * base


# Ventana de historia usada para calcular el REPARTO (qué % del día va a
# cada hora, qué % a cada producto) -- necesita varias semanas de patrón
# estable, no un solo día. Nunca incluye la fecha que se está planeando
# (evita depender circularmente del día que aún no pasó, o volver a
# contar el mismo día dos veces si ya pasó).
_DIAS_HISTORIA_PLAN_TAREA = 90


def plan_tarea_dia(engine: Engine, fecha: str, sucursal: str | None = None,
                    n_productos: int = 10, multiplo: int = 6) -> dict:
    """Plan-tarea de producción de Panadería para UN día concreto: cuántas
    piezas hacer en total, repartidas por HORA y por POSICIÓN DE MENÚ, en
    múltiplos de `multiplo` (charolas/lotes de horneado).

    El TOTAL del día sale, en este orden de preferencia:
      1. El plan manual de ese día (tabla plan_produccion), si existe.
      2. Si no, el pronóstico de ese día (panaderia_real_y_pronostico) --
         así la tarea se puede descargar incluso para un día que todavía
         no se llenó a mano en la tabla de arriba.

    Los REPARTOS (por hora, por producto) salen de _DIAS_HISTORIA_PLAN_TAREA
    días ANTES de la fecha pedida (ver esa constante) -- el mix reciente de
    qué se vende y a qué hora, no el de la fecha misma."""
    target = dt.date.fromisoformat(fecha)
    desde_historia = (target - dt.timedelta(days=_DIAS_HISTORIA_PLAN_TAREA)).isoformat()
    hasta_historia = (target - dt.timedelta(days=1)).isoformat()

    plan_filas = get_plan_produccion(engine, desde=fecha, hasta=fecha)
    plan_dia = plan_filas[0]["unidades_plan"] if plan_filas else None

    if plan_dia is not None:
        total_dia = plan_dia
        fuente_total = "план (введён вручную)"
    else:
        dias_pron = panaderia_real_y_pronostico(engine, desde=fecha, hasta=fecha, sucursal=sucursal)
        total_dia = dias_pron[0]["pronostico_unidades"] if dias_pron else None
        fuente_total = "прогноз (плана на этот день ещё нет)"

    if total_dia is None:
        return {
            "fecha": fecha, "total_dia": None, "total_dia_redondeado": None,
            "fuente_total": fuente_total, "multiplo": multiplo,
            "por_hora": [], "por_producto": [],
        }

    por_hora = []
    patron_horas = patron_horario_panaderia(engine, sucursal=sucursal,
                                             desde=desde_historia, hasta=hasta_historia)
    # Solo horas de operación (6-22, mismo rango que el resto del
    # dashboard) -- sin este filtro, una venta aislada de madrugada (un
    # cheque mal cerrado, un reloj distinto) redondea hacia arriba a una
    # charola entera (6 piezas) para una hora en la que el punto ni
    # siquiera abre.
    patron_horas = [h for h in patron_horas if 6 <= h["hora"] <= 22]
    total_historico_horas = sum(h["unidades"] for h in patron_horas)
    for h in patron_horas:
        if h["unidades"] <= 0:
            continue
        pct = h["unidades"] / total_historico_horas if total_historico_horas else 0.0
        por_hora.append({
            "hora": h["hora"],
            "pct_historico": round(100 * pct, 1),
            "unidades_plan": _redondear_a_multiplo(total_dia * pct, multiplo),
        })

    por_producto = []
    top_productos = top_platillos_panaderia(engine, sucursal=sucursal,
                                             desde=desde_historia, hasta=hasta_historia,
                                             n=n_productos)
    for p in top_productos:
        pct = p["pct_unidades"] / 100
        por_producto.append({
            "platillo": p["platillo"],
            "pct_historico": p["pct_unidades"],
            "unidades_plan": _redondear_a_multiplo(total_dia * pct, multiplo),
        })

    return {
        "fecha": fecha,
        "total_dia": round(total_dia, 1),
        "total_dia_redondeado": _redondear_a_multiplo(total_dia, multiplo),
        "fuente_total": fuente_total,
        "multiplo": multiplo,
        "por_hora": por_hora,
        "por_producto": por_producto,
    }


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
    festivo_peor_dia = festivo_cercano(dt.date.fromisoformat(peor["fecha"]))

    return {
        "n_dias": len(con_ambos),
        "total_real": round(total_real, 0),
        "total_comparado": round(total_comparado, 0),
        "desviacion_pct": desviacion_pct,
        "tendencia_pct": tendencia_pct,
        "peor_dia": peor["fecha"],
        "peor_dia_real": round(peor["real_unidades"], 0),
        "peor_dia_comparado": round(peor[campo], 0),
        "festivo_peor_dia": festivo_peor_dia,
    }


def precision_pronostico(dias: list[dict], campo_pronostico: str = "pronostico_unidades",
                          campo_real: str = "real_unidades") -> dict | None:
    """Qué tan preciso viene siendo el pronóstico DÍA A DÍA -- a diferencia
    de analizar_desviacion_produccion (arriba), que suma TODO el rango y
    solo distingue "tendencia sostenida" de "un día puntual", esto mide el
    error de CADA día por separado con MAPE (error porcentual absoluto
    medio -- métrica estándar de pronóstico, no inventada para este
    negocio) y parte la serie en dos mitades para ver si el modelo viene
    ERRANDO MÁS en las semanas recientes que antes -- un promedio único
    puede esconder un empeoramiento reciente detrás de meses viejos donde
    acertaba mejor.

    Recibe cualquier lista de dicts con fecha/`campo_real`/`campo_pronostico`
    -- pensada para el resultado de panaderia_real_y_pronostico, pero sin
    depender de él (función pura, sin acceso a la base)."""
    con_ambos = [
        d for d in dias
        if d.get(campo_real) is not None and d.get(campo_pronostico) not in (None, 0)
    ]
    if not con_ambos:
        return None

    serie = []
    for d in con_ambos:
        real = d[campo_real]
        pron = d[campo_pronostico]
        serie.append({
            "fecha": d["fecha"], "real": real, "pronostico": pron,
            "error_pct": round(100 * (real - pron) / pron, 1),
        })

    mape = sum(abs(f["error_pct"]) for f in serie) / len(serie)
    mitad = len(serie) // 2
    primera, segunda = serie[:mitad] or serie, serie[mitad:] or serie

    return {
        "n_dias": len(serie),
        "mape": round(mape, 1),
        "mape_anterior": round(sum(abs(f["error_pct"]) for f in primera) / len(primera), 1),
        "mape_reciente": round(sum(abs(f["error_pct"]) for f in segunda) / len(segunda), 1),
        "serie": serie,
    }


def _normaliza_nombre(s: str) -> str:
    """Para comparar el nombre de un producto del plan FÍSICO (papel/PDF,
    escrito a mano por quien arma el plan) contra el nombre real en la
    base (Wansoft) -- acentos, mayúsculas/minúsculas y un punto final
    suelto (la base tiene alguno, ej. "MACARONS.") no deberían contar
    como "otro producto"."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.upper().strip().rstrip(".").strip()
    return " ".join(s.split())


def comparar_plan_fisico(engine: Engine, sucursal: str, plan_por_dia: dict[str, float]) -> list[dict]:
    """Plan de producción FÍSICO (en papel, foto/PDF) contra ventas reales
    -- Panadería + Pastelería juntas (así se plane en papel, no solo
    Panadería como el resto de "Планирование"), excluyendo "Bolsa*"
    (empaque, ver EXCLUIR_BOLSA_SQL). `plan_por_dia` -- fecha ISO -> piezas
    planeadas, ya agregado desde la tabla plan_fisico_produccion (ver
    db.get_plan_fisico_por_dia; esa tabla se llena sola -- ver
    extractors/plan_fisico.py y auto_carga.procesar_planes).

    Agregado en SQL (GROUP BY fecha), no fila por fila -- mismo motivo que
    el resto de funciones de este archivo con tablas grandes."""
    if not plan_por_dia:
        return []
    fechas = sorted(plan_por_dia)
    sql = (
        "SELECT fecha, SUM(cantidad) AS unidades FROM sales_lines "
        "WHERE sucursal = :sucursal AND tipo_grupo IN ('PANADERIA', 'PASTELERIA')"
        + EXCLUIR_BOLSA_SQL + " AND fecha = ANY(:fechas) GROUP BY fecha"
    )
    with engine.connect() as conn:
        filas = list(conn.execute(text(sql), {"sucursal": sucursal, "fechas": fechas}).mappings())
    real_por_fecha = {f["fecha"]: f["unidades"] for f in filas}

    salida = []
    for fecha in fechas:
        plan = plan_por_dia[fecha]
        real = real_por_fecha.get(fecha)
        salida.append({
            "fecha": fecha, "plan": round(plan, 1),
            "real": round(real, 1) if real is not None else None,
            "delta_pct": _delta_pct(real, plan) if real is not None else None,
        })
    return salida


def comparar_plan_fisico_por_producto(engine: Engine, sucursal: str, fechas: list[str],
                                       plan_por_producto: dict[str, float], n: int = 15) -> dict:
    """Lo mismo que comparar_plan_fisico, pero por POSICIÓN DE MENÚ en vez
    de por día, sumado sobre TODO el período -- "¿qué posiciones se
    producen de más (podrían recortarse) y cuáles de menos (se agotan
    antes de lo planeado)?". El emparejamiento es por NOMBRE normalizado
    (ver _normaliza_nombre) -- una posición que no aparece en ambos lados
    queda en "solo_en_plan" o "solo_en_real" en vez de forzarse a un
    emparejamiento dudoso; esto último puede incluir productos con otro
    nombre en la base (no solo productos realmente ausentes del plan)."""
    plan_normalizado: dict[str, float] = defaultdict(float)
    for nombre, cantidad in plan_por_producto.items():
        plan_normalizado[_normaliza_nombre(nombre)] += cantidad

    sql = (
        "SELECT platillo, SUM(cantidad) AS unidades FROM sales_lines "
        "WHERE sucursal = :sucursal AND tipo_grupo IN ('PANADERIA', 'PASTELERIA')"
        + EXCLUIR_BOLSA_SQL + " AND fecha = ANY(:fechas) GROUP BY platillo"
    )
    with engine.connect() as conn:
        filas = list(conn.execute(text(sql), {"sucursal": sucursal, "fechas": fechas}).mappings())

    real_normalizado: dict[str, float] = defaultdict(float)
    nombre_real_de = {}
    for f in filas:
        clave = _normaliza_nombre(f["platillo"] or "")
        real_normalizado[clave] += f["unidades"]
        nombre_real_de[clave] = f["platillo"]

    claves = set(plan_normalizado) | set(real_normalizado)
    emparejados = []
    solo_en_plan = []
    solo_en_real = []
    for clave in claves:
        en_plan = clave in plan_normalizado
        en_real = clave in real_normalizado
        if en_plan and en_real:
            plan_val, real_val = plan_normalizado[clave], real_normalizado[clave]
            emparejados.append({
                "platillo": clave, "plan": round(plan_val, 1), "real": round(real_val, 1),
                "diff": round(plan_val - real_val, 1),
            })
        elif en_plan:
            solo_en_plan.append({"platillo": clave, "plan": round(plan_normalizado[clave], 1)})
        else:
            solo_en_real.append({
                "platillo": nombre_real_de[clave], "real": round(real_normalizado[clave], 1),
            })

    sobreproducidos = sorted(emparejados, key=lambda f: -f["diff"])[:n]
    subproducidos = sorted(emparejados, key=lambda f: f["diff"])[:n]
    solo_en_plan.sort(key=lambda f: -f["plan"])
    solo_en_real.sort(key=lambda f: -f["real"])

    # Cuánto del volumen REAL corresponde a posiciones que ni siquiera
    # aparecen en el plan de papel (no "menos de lo planeado" -- CERO
    # planeado) -- la prueba más directa de que la cocina no está
    # restringida por ese papel: si lo estuviera, esas ventas no podrían
    # existir (no hay de dónde sacar un producto que nunca se planeó).
    suma_real_total = sum(f["real"] for f in emparejados) + sum(f["real"] for f in solo_en_real)
    suma_solo_en_real = sum(f["real"] for f in solo_en_real)
    pct_solo_en_real = round(100 * suma_solo_en_real / suma_real_total, 1) if suma_real_total else 0.0

    return {
        "n_emparejados": len(emparejados),
        "sobreproducidos": sobreproducidos,
        "subproducidos": subproducidos,
        "solo_en_plan": solo_en_plan[:n],
        "solo_en_real": solo_en_real[:n],
        "suma_real_total": round(suma_real_total, 1),
        "suma_solo_en_real": round(suma_solo_en_real, 1),
        "pct_solo_en_real": pct_solo_en_real,
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


def pronostico_dia_total(engine: Engine, fecha: str, sucursal: str | None = None) -> dict | None:
    """Suma del pronóstico por hora (ventas_por_hora) para UN día completo
    -- "cuánto se espera vender" en dinero y en piezas. Sirve para fechas
    FUTURAS (todavía sin "real"), como el bloque "Ожидается завтра" en la
    página "Главная" -- ahí no hace falta el detalle por hora, solo el
    total del día. None si no hay historial suficiente para pronosticar
    ese día de semana."""
    datos = ventas_por_hora(engine, fecha, sucursal=sucursal)
    if not datos["n_dias_promedio"]:
        return None
    con_pronostico = [h for h in datos["horas"] if h["tipico"] is not None]
    if not con_pronostico:
        return None
    total_tipico = sum(h["tipico"] for h in con_pronostico)
    con_pronostico_u = [h for h in datos["horas"] if h["tipico_unidades"] is not None]
    total_tipico_unidades = sum(h["tipico_unidades"] for h in con_pronostico_u) if con_pronostico_u else 0.0
    return {
        "fecha": fecha,
        "dia_semana": datos["dia_semana"],
        "ventas_totales": round(total_tipico, 2),
        "unidades": round(total_tipico_unidades, 2),
    }


# Con una desviación dentro de este margen (en cualquier sentido) el día se
# considera "en línea" con el pronóstico -- no vale la pena diagnosticar
# ruido normal como si fuera un problema real.
_UMBRAL_DESVIACION_PCT = 5.0


def delta_color_significativo(pct: float | None) -> str:
    """Para el parámetro delta_color de st.metric: 'off' (gris, sin
    flecha verde/roja) si la desviación es chica (dentro de
    _UMBRAL_DESVIACION_PCT) -- una diferencia de +2% contra lo típico es
    ruido normal día a día, no una tendencia, y pintarla de color exagera
    su importancia. 'normal' (colores de siempre) si la desviación ya es
    grande."""
    if pct is None:
        return "off"
    return "normal" if abs(pct) >= _UMBRAL_DESVIACION_PCT else "off"

# Si menos de esta fracción de las horas activas terminó por debajo del
# pronóstico, el problema se etiqueta "concentrado" (una franja horaria
# puntual, el resto del día normal) -- si son más, es "distribuido" (el día
# entero flojo por igual). Se mide por CANTIDAD de horas afectadas, no por
# cuánto suman las peores -- con pocas horas activas, tomar "las 3 peores"
# explica casi todo el déficit aunque las 5 horas del día estén parejas
# hacia abajo, lo que daba falsos "concentrado" con muestras chicas.
_UMBRAL_CONCENTRACION = 0.4


def analizar_desempeno_por_hora(horas: list[dict], fecha: str | None = None) -> dict | None:
    """Diagnóstico corto de un día ya cerrado, comparando el mismo bloque de
    horas activas que se ve en el gráfico "Прогноз и факт" (viene de
    ventas_por_hora, ya recortado a horas con movimiento -- ver
    dashboard._horas_activas): cuánto se desvió la venta real del
    pronóstico, si la desviación viene de menos CLIENTES (unidades) o de un
    ticket promedio más bajo (unidades en línea pero dinero no), en qué
    horas se concentra la desviación (por ENCIMA o por DEBAJO -- antes
    solo se calculaba para "por debajo", dejando sin explicar los días
    inusualmente BUENOS, que es justo cuando más vale la pena entender
    qué pasó para poder repetirlo), y si coincide con un festivo mexicano
    conocido (ver festivo_cercano). Devuelve None cuando no hay pronóstico
    con el que comparar (día sin historial suficiente) -- en ese caso no
    hay nada que diagnosticar todavía.

    No es una IA explicando el día -- son reglas aritméticas simples y
    transparentes sobre los mismos números que ya están en el gráfico, más
    un dato de calendario verificable (no inventado); dashboard.py solo
    convierte este diccionario en las frases que ve Roman."""
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
    # encontrar las horas que más pesan -- ahora en AMBOS sentidos: qué
    # horas cargan con el déficit (por_debajo) o cuáles impulsan el
    # excedente (por_encima). "Concentrado" = pocas horas cargan con
    # (casi) toda la desviación (el resto del día anduvo normal);
    # "distribuido" = la mayoría de las horas activas se movieron igual --
    # un factor del día completo, no de un momento puntual.
    horas_criticas: list[dict] = []
    concentrado = False
    if estado == "por_debajo":
        diffs = sorted(
            ({"hora": h["hora"], "diff": round(h["real"] - h["tipico"], 2)} for h in con_pronostico),
            key=lambda d: d["diff"],
        )
        negativas = [d for d in diffs if d["diff"] < 0]
        concentrado = bool(negativas) and (len(negativas) / len(con_pronostico)) <= _UMBRAL_CONCENTRACION
        horas_criticas = negativas[:3]
    elif estado == "por_encima":
        diffs = sorted(
            ({"hora": h["hora"], "diff": round(h["real"] - h["tipico"], 2)} for h in con_pronostico),
            key=lambda d: -d["diff"],
        )
        positivas = [d for d in diffs if d["diff"] > 0]
        concentrado = bool(positivas) and (len(positivas) / len(con_pronostico)) <= _UMBRAL_CONCENTRACION
        horas_criticas = positivas[:3]

    festivo = festivo_cercano(dt.date.fromisoformat(fecha)) if fecha else None

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
        "festivo": festivo,
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
