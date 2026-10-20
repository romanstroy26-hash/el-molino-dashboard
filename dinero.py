"""«Деньги»: cuánto cuesta planear mal. Convierte el cierre del día (sobrantes, horneado, hora en que se agotó) y las ventas en dos cifras
en pesos por semana, para saber si el sistema de planeación realmente mejora el negocio:

  - MERMA: lo que sobró al cierre, a costo (precio de venta x porcentaje de costo, que decide el dueño; 35 % por defecto es un supuesto).
  - VENTAS PERDIDAS: lo que no se vendió porque el producto se agotó antes del cierre. Solo se estima cuando se anotó la hora: si se vendió S
    hasta esa hora y a partir de ella suele venderse la parte `a` del día, la demanda era S / (1 - a) y se perdió S x a / (1 - a) (como máximo S).
    Sin hora, no se inventa nada: cuenta como 0 (cifra conservadora).

El indicador que importa es COSTO DE LA IMPRECISIÓN = merma a costo + margen de las ventas perdidas: debe bajar semana a semana. Además: % de
posiciones agotadas, adherencia al plan (horneado / lo que el sistema recomendó) y error del pronóstico de la semana.

Puro salvo `precios_por_producto` (consulta a la base).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import plan_dia
import plan_propio as pp

COSTO_DEFECTO = 0.35           # costo como parte del precio de venta: SUPUESTO, el dueño lo ajusta
MIN_POSICIONES_DIA = 5         # un día cuenta como "contado" si se anotaron al menos 5 posiciones
PARTE_MAXIMA = 0.5             # una hora de agotado que implicaría perder más de la mitad del día se limita a perder lo vendido


@dataclass
class Linea:
    fecha: dt.date
    clave: str
    producto: str
    vendido: float
    sobrante: float | None = None
    horneado: float | None = None
    agotado_a: str | None = None       # "HH:MM"
    plan: float | None = None          # lo que el sistema recomendó hornear ese día
    precio: float | None = None
    agotado_fiable: bool = True        # False si el sobrante viene de la merma del chat: un 0 ahí es «no se tiró nada», no «se agotó»


def parte_del_dia_desde(horas: list, hora: str) -> float | None:
    """Parte de la venta del día que suele ocurrir desde `hora` ("HH:MM") en adelante, con `horas` = unidades por hora (24 valores)."""
    total = sum(horas)
    if total <= 0 or not hora:
        return None
    h, m = int(hora[:2]), int(hora[3:5])
    despues = sum(horas[h + 1:]) + horas[h] * (1 - m / 60.0)
    return despues / total


def ventas_perdidas(vendido: float, agotado_a: str | None, horas: list | None) -> float:
    """Unidades que se dejaron de vender por agotarse a `agotado_a`. 0 si no se anotó la hora o no hay perfil de ventas por hora."""
    if not agotado_a or not horas or vendido <= 0:
        return 0.0
    a = parte_del_dia_desde(horas, agotado_a)
    if a is None or a <= 0:
        return 0.0
    if a >= 1:
        return float(vendido)
    return min(float(vendido), vendido * a / (1 - a)) if a < PARTE_MAXIMA else float(vendido)


def lunes_de(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def resumen_semanal(lineas: list, perfiles: dict | None = None, costo: float = COSTO_DEFECTO) -> list:
    """Una fila por semana (de lunes), de la más vieja a la más nueva. `perfiles` = {(clave, fin_de_semana): [24 unidades por hora]}.

    Claves de cada fila: lunes, dias_contados, posiciones, pct_agotado, merma_unid, merma_costo, perdidas_unid, perdidas_margen, imprecision
    (= merma_costo + perdidas_margen), adherencia. Un valor es None cuando esa semana no tiene datos para calcularlo."""
    perfiles = perfiles or {}
    por_semana: dict = {}
    for ln in lineas:
        por_semana.setdefault(lunes_de(ln.fecha), []).append(ln)
    salida = []
    for lunes in sorted(por_semana):
        ls = por_semana[lunes]
        dias: dict = {}
        for ln in ls:
            if ln.sobrante is not None:
                dias.setdefault(ln.fecha, set()).add(ln.clave)
        dias_ok = {d for d, ks in dias.items() if len(ks) >= MIN_POSICIONES_DIA}
        contadas = [ln for ln in ls if ln.sobrante is not None and ln.fecha in dias_ok]
        merma_unid = sum(ln.sobrante for ln in contadas)
        merma_costo = sum(ln.sobrante * (ln.precio or 0.0) * costo for ln in contadas)
        fiables = [ln for ln in contadas if ln.agotado_fiable]
        agotadas = [ln for ln in fiables if ln.sobrante <= 0]
        perdidas_unid = perdidas_margen = 0.0
        for ln in agotadas:
            horas = perfiles.get((ln.clave, ln.fecha.weekday() >= 5)) or perfiles.get((ln.clave, None))
            p = ventas_perdidas(ln.vendido, ln.agotado_a, horas)
            perdidas_unid += p
            perdidas_margen += p * (ln.precio or 0.0) * (1 - costo)
        con_plan = [ln for ln in ls if ln.horneado is not None and ln.plan]
        salida.append({
            "lunes": lunes,
            "dias_contados": len(dias_ok),
            "posiciones": len(contadas),
            "pct_agotado": (len(agotadas) / len(fiables)) if fiables else None,
            "merma_unid": merma_unid if contadas else None,
            "merma_costo": merma_costo if contadas else None,
            "perdidas_unid": perdidas_unid if contadas else None,
            "perdidas_margen": perdidas_margen if contadas else None,
            "imprecision": (merma_costo + perdidas_margen) if contadas else None,
            "adherencia": (sum(ln.horneado for ln in con_plan) / sum(ln.plan for ln in con_plan)) if con_plan else None,
        })
    return salida


def lineas_de_merma(merma: dict, ventas: dict, claves: list, nombres: dict, precios: dict, plan_por_dia: dict | None = None,
                    excluir: set | frozenset = frozenset()) -> list:
    """Líneas para resumen_semanal a partir de la merma del chat. `merma` = {fecha: {clave: piezas}} de los días CON reporte: en esos días todo lo
    que no aparece en la lista cuenta como merma 0 (todo producto del catálogo con venta ese día). Los días en `excluir` (con conteo manual)
    se omiten para no contarlos dos veces. La hora de agotado no existe en estos datos: no se estiman ventas perdidas y el 0 no cuenta como
    «agotado»."""
    plan_por_dia = plan_por_dia or {}
    salida = []
    for fecha, dia in sorted(merma.items()):
        if fecha in excluir:
            continue
        for k in claves:
            vendido = ventas.get(fecha, {}).get(k, 0.0)
            if vendido <= 0 and dia.get(k, 0.0) <= 0:
                continue
            salida.append(Linea(fecha, k, nombres.get(k, k), vendido, dia.get(k, 0.0), None, None, plan_por_dia.get(fecha, {}).get(k) or None,
                                precios.get(k), agotado_fiable=False))
    return salida


def error_de_pronostico(ventas_por_dia: dict, pronosticos: dict, desde: dt.date, hasta: dt.date) -> float | None:
    """Error medio |real / pronóstico - 1| de los días desde..hasta (inclusive) que tienen ambos. `pronosticos` = {fecha: Pronostico}."""
    errores = []
    d = desde
    while d <= hasta:
        p, v = pronosticos.get(d), ventas_por_dia.get(d)
        if p is not None and p.total > 0 and v and v >= 0.5 * p.total:       # un día cargado a medias no mide el pronóstico
            errores.append(abs(v / p.total - 1))
        d += dt.timedelta(days=1)
    return sum(errores) / len(errores) if errores else None


def comparar(anterior: dict | None, actual: dict | None, campo: str) -> float | None:
    """Cambio relativo de una cifra entre dos filas semanales; None si falta alguna o la anterior es 0."""
    if not anterior or not actual:
        return None
    a, b = anterior.get(campo), actual.get(campo)
    if a in (None, 0) or b is None:
        return None
    return b / a - 1


def precios_por_producto(engine, sucursal: str, claves_catalogo: list, desde: dt.date, hasta: dt.date) -> dict:
    """{clave del catálogo: precio medio por pieza} = importe / unidades de Panadería + Pastelería en el periodo (sin bolsas)."""
    from sqlalchemy import text

    import metrics

    sql = ("SELECT platillo, SUM(importe) AS i, SUM(cantidad) AS u FROM sales_lines WHERE sucursal = :s "
           "AND tipo_grupo IN ('PANADERIA', 'PASTELERIA')" + metrics.EXCLUIR_BOLSA_SQL + " AND fecha >= :d AND fecha < :h GROUP BY platillo")
    importe: dict = {}
    unidades: dict = {}
    with engine.connect() as conn:
        filas = [(plan_dia.clave_producto(r["platillo"] or ""), float(r["i"] or 0), float(r["u"] or 0))
                 for r in conn.execute(text(sql), {"s": sucursal, "d": desde.isoformat(), "h": hasta.isoformat()}).mappings()]
    mapa = pp.mapear_nombres(claves_catalogo, {k for k, _, _ in filas})
    for k, i, u in filas:
        if k in mapa:
            importe[mapa[k]] = importe.get(mapa[k], 0.0) + i
            unidades[mapa[k]] = unidades.get(mapa[k], 0.0) + u
    return {k: importe[k] / unidades[k] for k in importe if unidades.get(k, 0) > 0}
