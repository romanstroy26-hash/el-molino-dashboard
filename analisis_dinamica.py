"""Texto para los gráficos de dinámica de Cafeteria: dice POR QUÉ las líneas de dinero y de participación (%) se van en direcciones distintas.

Dos causas, comprobables con los mismos números del gráfico:
  1. el último punto es un día INCOMPLETO (hoy, exportado a media jornada): el dinero cae porque el día no terminó y la participación del café
     sube porque por la mañana se vende más bebida que pan; no es una tendencia;
  2. entre dos puntos completos, la categoría y el total se movieron distinto: la participación es un cociente, así que puede subir
     mientras el dinero baja si el total cayó todavía más (y al revés).
Puro: recibe las filas ya calculadas (las del gráfico), sin base de datos. Los textos salen en ruso, como el resto del dashboard.
"""

from __future__ import annotations

UMBRAL_PT = 0.3        # puntos de participación que ya se cuentan como cambio
UMBRAL_PCT = 1.0       # % de dinero que ya se cuenta como cambio


def _pct(a: float, b: float) -> float | None:
    return 100 * (b - a) / a if a else None


def _divergencias(a: dict, b: dict, categorias: dict) -> list:
    """Frases de las categorías cuyo dinero y participación se movieron en sentido contrario entre las filas `a` -> `b`."""
    frases = []
    total = _pct(a["ventas_totales"], b["ventas_totales"])
    for nombre, (col_dinero, col_pct) in categorias.items():
        dinero = _pct(a[col_dinero], b[col_dinero])
        dpt = b[col_pct] - a[col_pct]
        if dinero is None or total is None or abs(dpt) < UMBRAL_PT or abs(dinero) < UMBRAL_PCT or (dpt > 0) == (dinero > 0):
            continue
        if dpt > 0:
            causa = f"общие продажи упали ещё сильнее ({total:+.0f}%)"
        else:
            causa = f"общие продажи выросли ещё сильнее ({total:+.0f}%)"
        frases.append(
            f"«{nombre}», {a['etiqueta']} → {b['etiqueta']}: выручка {dinero:+.0f}%, доля {dpt:+.1f} пт -- {causa}, "
            f"поэтому доля (отношение к общим продажам) пошла в другую сторону, чем выручка.")
    return frases


def frases(filas: list, categorias: dict, ultimo_incompleto: bool = False, corte: str | None = None) -> list:
    """`filas`: puntos del gráfico en orden (con 'etiqueta', 'ventas_totales' y las columnas de `categorias`: {nombre: (col_dinero, col_%)}).
    `ultimo_incompleto`: el último punto es un día a medias; `corte`: hasta qué hora hay ventas ('15:40')."""
    if len(filas) < 2:
        return []
    ultimo, previo = filas[-1], filas[-2]
    salida = []
    if ultimo_incompleto:
        hasta = f" (продажи только до {corte})" if corte else ""
        salida.append(
            f"⏳ Последняя точка ({ultimo['etiqueta']}) -- НЕПОЛНЫЙ день{hasta}: выручка падает ({ultimo['ventas_totales']:,.0f} $ против "
            f"{previo['ventas_totales']:,.0f} $ накануне), потому что день ещё не закончился, а доля кофе и напитков растёт, потому что "
            f"с утра напитков продаётся больше, чем выпечки к вечеру. Это не тренд -- сравнивайте с последним полным днём.")
        if len(filas) >= 3:
            salida += _divergencias(filas[-3], filas[-2], categorias)
        return salida
    return _divergencias(previo, ultimo, categorias)
