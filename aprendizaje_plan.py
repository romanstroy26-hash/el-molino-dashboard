"""El sistema aprende de sus propios errores: compara SU plan con lo vendido y corrige los próximos planes.

Ningún plan de papel interviene. La materia prima son observaciones "lo que el sistema habría planeado para ese producto ese día
(hecho solo con lo anterior a ese día) contra lo que se vendió" (ver plan_propio.observaciones_virtuales). Como el plan crudo del
sistema se recalcula siempre igual a partir de las ventas, no hay riesgo de que aprenda sobre sus propias correcciones.

Corrige la MEZCLA entre productos (el total del día lo decide el pronóstico: ver pronostico.py). Para cada día cerrado se compara la
parte que cada producto tuvo en el plan del sistema con la parte que tuvo en la venta; un producto que SIEMPRE se vende más (o menos) de
lo que el sistema le asignaba recibe un multiplicador. Se mide en partes del día, no en piezas: así un día flojo o fuerte no confunde a
ningún producto. Los días recientes pesan más (semivida 21 días); con pocos días el multiplicador se acerca a 1 (contracción); nunca sale
de 0.6-1.6; y por debajo de 5 % de diferencia no se toca (ruido). Prueba histórica honesta: la ganancia sobre el plan crudo del sistema es
pequeña (27.9 % -> 27.3 % de error por producto; la mayor parte de la adaptación ya viene de dar más peso a las últimas semanas).

Los sobrantes al cierre (colchón por producto) se aprenden aparte: plan_propio.colchones_por_sobras.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass

import plan_dia

SEMIVIDA_DIAS = 21
PESO_PRIOR = 4.0             # "días de duda": con pocos días el multiplicador se queda cerca de 1
FACTOR_MIN, FACTOR_MAX = 0.6, 1.6
DIAS_MINIMOS = 5             # con menos días con plan y venta, un producto no se toca
ZONA_MUERTA = 0.05           # multiplicadores a menos de 5 % de 1 se ignoran
CALENTAMIENTO = 10           # días de historia mínimos antes de empezar la prueba histórica


@dataclass
class Obs:
    fecha: dt.date
    clave: str
    producto: str
    plan: float                # lo que el sistema habría asignado a este producto ese día (demanda cruda)
    vendido: float


def vendido_por_dia(engine, sucursal: str, desde: dt.date, hasta: dt.date) -> dict:
    """{fecha: {clave_producto: unidades}} de Panadería + Pastelería (sin bolsas), días desde..hasta-1. Las líneas "CON IVA" se suman."""
    from sqlalchemy import text

    from metrics import EXCLUIR_BOLSA_SQL

    sql = ("SELECT fecha, platillo, SUM(cantidad) AS unidades FROM sales_lines WHERE sucursal = :s "
           "AND tipo_grupo IN ('PANADERIA', 'PASTELERIA')" + EXCLUIR_BOLSA_SQL +
           " AND fecha >= :d AND fecha < :h GROUP BY fecha, platillo")
    resultado: dict = {}
    with engine.connect() as conn:
        for r in conn.execute(text(sql), {"s": sucursal, "d": desde.isoformat(), "h": hasta.isoformat()}).mappings():
            dia = resultado.setdefault(dt.date.fromisoformat(str(r["fecha"])[:10]), {})
            k = plan_dia.clave_producto(r["platillo"] or "")
            dia[k] = dia.get(k, 0.0) + float(r["unidades"] or 0)
    return resultado


@dataclass
class Ajuste:
    clave: str
    producto: str
    factor: float              # el que se APLICA (1.0 si no hay suficientes días o la diferencia es ruido)
    factor_bruto: float
    n_dias: int
    plan_medio: float          # unidades que el sistema asignaba por día (promedio en los días medidos)
    vendido_medio: float
    razon: float | None        # vendido / asignado, acumulado
    confianza: float           # 0..1
    aplica: bool


def _log_relativo(obs: list) -> dict:
    """Por (fecha, clave): log de (parte en la venta / parte en el plan del sistema)."""
    por_dia: dict = {}
    for o in obs:
        t = por_dia.setdefault(o.fecha, [0.0, 0.0])
        t[0] += o.plan
        t[1] += o.vendido
    salida = {}
    for o in obs:
        suma_plan, suma_venta = por_dia[o.fecha]
        if suma_plan <= 0 or suma_venta <= 0 or o.plan <= 0:
            continue
        rel = (o.vendido / suma_venta) / (o.plan / suma_plan)
        salida[(o.fecha, o.clave)] = math.log(min(5.0, max(0.2, rel)))
    return salida


def aprender(obs: list, hasta: dt.date, semivida: float = SEMIVIDA_DIAS, prior: float = PESO_PRIOR,
             minimo: float = FACTOR_MIN, maximo: float = FACTOR_MAX) -> dict:
    """{clave: Ajuste} con lo aprendido de las observaciones anteriores a `hasta`."""
    previas = [o for o in obs if o.fecha < hasta]
    logs = _log_relativo(previas)
    grupos: dict = {}
    for o in previas:
        if (o.fecha, o.clave) in logs:
            grupos.setdefault(o.clave, []).append(o)
    ajustes = {}
    for k, lista in grupos.items():
        pesos = [0.5 ** ((hasta - o.fecha).days / semivida) for o in lista]
        sw = sum(pesos)
        est = sum(w * logs[(o.fecha, k)] for w, o in zip(pesos, lista)) / sw
        confianza = sw / (sw + prior)
        bruto = math.exp(est * confianza)
        factor = min(maximo, max(minimo, bruto))
        n = len(lista)
        aplica = n >= DIAS_MINIMOS and abs(factor - 1) >= ZONA_MUERTA
        plan_t, venta_t = sum(o.plan for o in lista), sum(o.vendido for o in lista)
        ajustes[k] = Ajuste(clave=k, producto=lista[-1].producto, factor=factor if aplica else 1.0, factor_bruto=factor, n_dias=n,
                            plan_medio=plan_t / n, vendido_medio=venta_t / n, razon=(venta_t / plan_t if plan_t else None),
                            confianza=confianza, aplica=aplica)
    return ajustes


def multiplicadores(ajustes: dict) -> dict:
    """{clave: factor} solo de los productos que SÍ se corrigen."""
    return {k: a.factor for k, a in ajustes.items() if a.aplica}


def prueba_historica(obs: list, **parametros) -> dict | None:
    """Día por día, con SOLO el pasado: ¿el plan corregido se parece más a lo vendido que el plan crudo del sistema?

    Error = suma de |plan - venta| entre venta, producto por producto, con ambos planes llevados al mismo total del día
    (aquí solo se prueba la mezcla entre productos; el total del día se prueba aparte)."""
    dias = sorted({o.fecha for o in obs})
    por_dia: dict = {}
    for o in obs:
        por_dia.setdefault(o.fecha, []).append(o)
    base, corregido, mejoran = [], [], 0
    for d in dias[CALENTAMIENTO:]:
        filas = por_dia[d]
        venta = sum(o.vendido for o in filas)
        if venta <= 0:
            continue
        f = multiplicadores(aprender(obs, d, **parametros))
        plan_base = [o.plan for o in filas]
        plan_corr = [o.plan * f.get(o.clave, 1.0) for o in filas]
        c0, c1 = venta / sum(plan_base), venta / sum(plan_corr)
        e0 = sum(abs(p * c0 - o.vendido) for p, o in zip(plan_base, filas)) / venta
        e1 = sum(abs(p * c1 - o.vendido) for p, o in zip(plan_corr, filas)) / venta
        base.append(e0)
        corregido.append(e1)
        mejoran += e1 < e0
    if not base:
        return None
    return {"n_dias": len(base), "error_base": statistics.mean(base), "error_corregido": statistics.mean(corregido),
            "dias_mejoran": mejoran / len(base)}
