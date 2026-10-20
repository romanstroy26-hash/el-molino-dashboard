"""Reglas de la vitrina del reglamento del dueño, pero con números SACADOS DE LAS VENTAS (no de una tabla fija).

Tipos de día con normas separadas (el dueño: viernes y fin de semana no se mezclan con los días entre semana): lunes-jueves, viernes, sáb-dom.
  - ABC: ranking por unidades vendidas por día del mismo tipo (últimas 8 semanas); A hasta el 79 % acumulado, B hasta el 94 %, C el resto
    (los cortes del reglamento: 79 / 15 / 5 %). Cambia solo cuando cambian las ventas.
  - Reserva: lo que se vende de cada producto entre las 18:00 y las 20:30 (promedio del mismo tipo de día) + 15 %, redondeado hacia arriba.
    También el ranking de candidatos: qué productos venden más de noche (el reglamento solo reserva 4 croissants, ~12 % de la noche).
  - Indicador del reglamento «vitrina llena»: en cuántos días-producto del grupo A se acabó el producto antes de las 20:30 (con la hora
    anotada en «Остатки»).
Puro: recibe diccionarios ya calculados (plan_propio.Insumos.ventas / ventas_hora).
"""

from __future__ import annotations

import datetime as dt
import math

TIPOS = ("будни", "пятница", "выходные")
ETIQUETAS = {"будни": "Пн–Чт", "пятница": "Пятница", "выходные": "Сб–Вс"}
CORTE_A, CORTE_B = 0.79, 0.94
HORA_FIN_VITRINA = 20.5
MARGEN_RESERVA = 0.15
SEMANAS = 8
RESERVA_DEL_REGLAMENTO = ("croissant chocolate", "croissant frambuesa", "croissant frutos rojos", "croissant pistache")


def tipo_de_dia(fecha: dt.date) -> str:
    dia = fecha.weekday()
    return "пятница" if dia == 4 else "выходные" if dia >= 5 else "будни"


def _dias(fechas, hoy: dt.date, tipo: str, semanas: int) -> list:
    """Fechas del mismo tipo de día en las últimas `semanas` semanas, sin hoy."""
    return sorted(d for d in fechas if d < hoy and (hoy - d).days <= semanas * 7 and tipo_de_dia(d) == tipo)


def abc(ventas: dict, hoy: dt.date, tipo: str, semanas: int = SEMANAS) -> dict:
    """{'dias': n, 'filas': [{clave, por_dia, parte, acumulado, clase}]} -- `ventas` = {fecha: {clave: unidades}}."""
    dias = _dias(ventas, hoy, tipo, semanas)
    if not dias:
        return {"dias": 0, "filas": []}
    suma: dict = {}
    for d in dias:
        for k, u in ventas[d].items():
            suma[k] = suma.get(k, 0.0) + u
    total = sum(suma.values())
    filas, acum = [], 0.0
    for k, u in sorted(suma.items(), key=lambda kv: -kv[1]):
        if u <= 0:
            continue
        clase = "A" if acum < CORTE_A else "B" if acum < CORTE_B else "C"
        acum += u / total
        filas.append({"clave": k, "por_dia": u / len(dias), "parte": u / total, "acumulado": acum, "clase": clase})
    return {"dias": len(dias), "filas": filas}


def resumen_abc(filas: list) -> dict:
    """{clase: (número de productos, % del volumen)}."""
    salida = {}
    for c in "ABC":
        sel = [f for f in filas if f["clase"] == c]
        salida[c] = (len(sel), sum(f["parte"] for f in sel))
    return salida


def ventas_de_noche(ventas_hora: dict, hoy: dt.date, tipo: str, semanas: int = SEMANAS, fin: float = HORA_FIN_VITRINA) -> dict:
    """{clave: unidades por día entre las 18:00 y `fin` (la hora 20 cuenta por su fracción)} -- `ventas_hora` = {fecha: {clave: [24]}}."""
    dias = _dias(ventas_hora, hoy, tipo, semanas)
    if not dias:
        return {}
    suma: dict = {}
    for d in dias:
        for k, horas in ventas_hora[d].items():
            suma[k] = suma.get(k, 0.0) + sum(horas[18:20]) + horas[20] * max(0.0, min(1.0, fin - 20.0))
    return {k: v / len(dias) for k, v in suma.items()}


def reserva(noche: dict, claves: list, margen: float = MARGEN_RESERVA) -> dict:
    """{clave: piezas de reserva} = venta nocturna del tipo de día + margen, hacia arriba."""
    return {k: int(math.ceil(noche.get(k, 0.0) * (1 + margen) - 1e-9)) for k in claves}


def candidatos(noche: dict, n: int = 10) -> list:
    """[(clave, unidades por noche, % de la noche)] de los n productos que más venden entre las 18:00 y las 20:30."""
    total = sum(noche.values())
    if total <= 0:
        return []
    return [(k, v, v / total) for k, v in sorted(noche.items(), key=lambda kv: -kv[1])[:n] if v > 0]


def _hora(texto: str | None) -> float | None:
    try:
        h, m = str(texto).split(":")[:2]
        return int(h) + int(m) / 60.0
    except (ValueError, AttributeError):
        return None


def vitrina_llena(filas_sobras: list, claves_a: set, clave_de, limite: float = HORA_FIN_VITRINA) -> dict:
    """De los conteos de cierre (db.get_sobrantes): {'registros': días-producto del grupo A con hora anotada, 'agotados': los que se acabaron
    antes del `limite`, 'pct': agotados / registros o None}. `clave_de` convierte el nombre de caja en clave del catálogo."""
    registros = agotados = 0
    for f in filas_sobras:
        if clave_de(f["platillo"]) not in claves_a:
            continue
        h = _hora(f.get("agotado_a"))
        if h is None:
            continue
        registros += 1
        agotados += h < limite
    return {"registros": registros, "agotados": agotados, "pct": agotados / registros if registros else None}
