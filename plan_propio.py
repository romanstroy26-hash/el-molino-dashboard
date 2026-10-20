"""Plan del día hecho SOLO con las ventas: ninguna cifra de los planes de papel entra en el cálculo.

Los PDF de planes (data/planes_produccion/<punto>) se usan únicamente como CATÁLOGO: qué productos lleva la hoja, en qué orden,
cuántas piezas trae una charola de cada uno y el formato de las columnas. Todas las cantidades las calcula el sistema:

  1. TOTAL DEL DÍA: el pronóstico de pronostico.py aplicado a las ventas de los productos de la hoja (base por día de la semana,
     últimos días, temperatura, festivos).
  2. PARTE DE CADA PRODUCTO: qué porción de la venta del catálogo fue de cada producto en los mismos días de la semana (más la de los
     últimos 120 días, 60/40), con semivida de 2 semanas: la prueba histórica eligió ese ritmo (error por producto 29 % contra
     32-33 % con 8 semanas). El aprendizaje (aprendizaje_plan.py) corrige el sesgo que aún quede.
  3. A PRODUCIR = demanda x (1 + colchón). Sin dato de sobras el colchón es un ajuste que decide el dueño (15 % por defecto); con
     el conteo de sobras al cierre (tabla sobrantes_cierre) se ajusta producto por producto.
  4. TURNOS Y HORAS: lo que el producto vende ANTES de las 18:00 se hornea en el turno matutino (7 a 12; la tanda de las 7 cubre lo
     vendido antes de las 9, cada tanda siguiente la hora que viene 1 hora después, y lo vendido de 13 a 18 sale de las últimas tres
     tandas de la mañana); lo vendido desde las 18:00 se hornea en el vespertino (15, 16 y 17). Según cómo se vendió en las últimas 8
     semanas (fin de semana aparte). Reglas de las hojas semanales del dueño: el pan de muerto va todo en la mañana; panqués y muffins
     (un sabor por día, ciclo L-M-X, todo en la mañana) se hacen una vez para los días que cubren (hasta el siguiente día de producción
     de ese sabor) y se guardan en el refri.
  5. OPCIONES 1/2/3 DE LA 1PM: cuánto más se vende desde las 18:00 cuando las ventas (todo el menú, miles de pesos) hasta las 13:00 son
     altas (pendiente de la regresión sobre los últimos 56 días), repartido entre productos según lo que vendían en la noche; salen
     después de las 5pm. Las cifras (38/42/46) salen de la cabecera de la hoja semanal. La opción 1 es la base (sin añadido). La RESERVA
     (refri) es una decisión manual: no se calcula.

Puro (sin base de datos) salvo los cargadores de ventas al final del archivo.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import plan_dia
from plan_dia import Fila, Plan

SEMIVIDA_SEMANAS = 2.0
MEZCLA_TODOS = 0.6
VENTANA_TODOS_DIAS = 120
MIN_DIAS_MISMO_DIA = 4
COLCHON_DEFECTO = 0.15
COLCHON_MAX = 0.40
HORAS_HORNEADO = tuple(range(7, 18))        # 7..17
HORAS_MATUTINO = tuple(h for h in HORAS_HORNEADO if h <= 12)
CORTE_NOCHE = 18                            # lo vendido desde las 18:00 sale del turno vespertino y de las opciones
HORA_OPCIONES = 13                          # las opciones se deciden a la 1pm con las ventas hasta esa hora
UNIDAD_OPCIONES = 6                         # las opciones se redondean a media docena (como en las hojas), no a la charola entera
FASES_CICLO = {"platano": 0, "cafe": 0, "zanahoria": 1, "blueberries": 1, "elote": 2, "manzana": 2}    # sabor de panqué/muffin -> fase del ciclo L-M-X
DIAS_PERFIL = 56
MIN_UNIDADES_PERFIL = 12


# --------------------------------------------------------------------------------------------- catálogo y nombres

@dataclass
class Item:
    clave: str
    producto: str
    charola: int


@dataclass
class Catalogo:
    items: list
    etiquetas_tandas: tuple
    punto: str

    @property
    def claves(self) -> list:
        return [i.clave for i in self.items]


def catalogo(planes: dict) -> Catalogo | None:
    """Productos, orden, charola y formato tomados de los últimos planes de papel. NO se lee ninguna cantidad para planear:
    solo el tamaño de la charola (la pieza que más se repite en las celdas de horneado; si el producto solo trae total escrito a
    mano, el máximo común divisor de sus totales)."""
    if not planes:
        return None
    recientes = [planes[d] for d in sorted(planes)[-8:]]
    ultimo = recientes[-1]
    celdas: dict = {}
    totales: dict = {}
    for plan in recientes:
        for f in plan.filas:
            k = plan_dia.clave_producto(f.producto)
            for v in f.horas.values():
                if v:
                    celdas.setdefault(k, Counter())[v] += 1
            if f.total:
                totales.setdefault(k, []).append(f.total)
    items, vistos = [], set()
    for f in ultimo.filas:
        k = plan_dia.clave_producto(f.producto)
        if k in vistos:
            continue
        vistos.add(k)
        if k in celdas:
            charola = celdas[k].most_common(1)[0][0]
        elif k in totales:
            charola = plan_dia._mcd(totales[k])
        else:
            charola = 1
        items.append(Item(k, f.producto, max(1, int(charola))))
    return Catalogo(items, ultimo.etiquetas_tandas, ultimo.punto)


def mapear_nombres(claves_catalogo: list, claves_ventas) -> dict:
    """{clave_de_venta: clave_del_catálogo}. Igual de nombre -> ese producto. Si no, el producto del catálogo (de 2 o más palabras)
    cuyas palabras están TODAS en el nombre de la caja y es el más específico ("CREMA FRESA MUERTO PAN" -> "Pan de Muerto Fresa").
    Si hay empate, no se adivina."""
    catalogo_pal = {k: frozenset(k.split()) for k in claves_catalogo}
    salida = {}
    for v in claves_ventas:
        if v in catalogo_pal:
            salida[v] = v
            continue
        palabras = frozenset(v.split())
        candidatos = sorted(((len(p), k) for k, p in catalogo_pal.items() if len(p) >= 2 and p <= palabras), reverse=True)
        if candidatos and (len(candidatos) == 1 or candidatos[0][0] > candidatos[1][0]):
            salida[v] = candidatos[0][1]
    return salida


def ventas_del_catalogo(ventas_crudas: dict, claves_catalogo: list) -> tuple[dict, list]:
    """({fecha: {clave_catálogo: unidades}}, [nombres de caja vendidos que no están en el catálogo, de más a menos unidades])."""
    mapa = mapear_nombres(claves_catalogo, {k for dia in ventas_crudas.values() for k in dia})
    ventas: dict = {}
    fuera: Counter = Counter()
    for fecha, dia in ventas_crudas.items():
        sal = ventas.setdefault(fecha, {})
        for k, v in dia.items():
            if k in mapa:
                sal[mapa[k]] = sal.get(mapa[k], 0.0) + v
            else:
                fuera[k] += v
    return ventas, [k for k, _ in fuera.most_common()]


def totales_por_dia(ventas: dict) -> dict:
    return {d: sum(dia.values()) for d, dia in ventas.items()}


# --------------------------------------------------------------------------------------------- partes y demanda

def precalcular_partes(ventas: dict, claves: list) -> dict:
    """{fecha: {clave: parte de ese día}} de los días con venta del catálogo: se calcula una vez y se reutiliza (partes tarda si se repite)."""
    salida = {}
    for d, dia in ventas.items():
        total = sum(dia.get(k, 0.0) for k in claves)
        if total > 0:
            salida[d] = {k: dia.get(k, 0.0) / total for k in claves}
    return salida


def grupo_de_dia(fecha: dt.date) -> str:
    """Lunes-jueves / viernes / sábado-domingo: las normas del viernes y del fin de semana no se mezclan con las de entre semana."""
    return "viernes" if fecha.weekday() == 4 else "finde" if fecha.weekday() >= 5 else "semana"


MEZCLA_POR_TIPO_DE_DIA = False     # ver docs/decisiones: se activa solo si la prueba honesta lo muestra mejor


def partes(ventas: dict, claves: list, fecha: dt.date, semivida: float = SEMIVIDA_SEMANAS, mezcla: float = MEZCLA_TODOS,
           precalculadas: dict | None = None, por_tipo_de_dia: bool | None = None) -> dict | None:
    """{clave: parte de la venta del catálogo} para `fecha`, usando solo días anteriores. None si faltan días del mismo día de la semana.
    `precalculadas` = precalcular_partes(ventas, claves) cuando se llama muchas veces."""
    if precalculadas is None:
        precalculadas = precalcular_partes(ventas, claves)
    dias = [d for d in precalculadas if d < fecha and (fecha - d).days <= VENTANA_TODOS_DIAS]
    mismos = [d for d in dias if d.weekday() == fecha.weekday()]
    if len(mismos) < MIN_DIAS_MISMO_DIA:
        return None

    def media(lista):
        pesos = {d: 0.5 ** ((fecha - d).days / 7 / semivida) for d in lista}
        sw = sum(pesos.values())
        acum = dict.fromkeys(claves, 0.0)
        for d, w in pesos.items():
            for k, v in precalculadas[d].items():
                acum[k] += w * v
        return {k: v / sw for k, v in acum.items()}

    if (MEZCLA_POR_TIPO_DE_DIA if por_tipo_de_dia is None else por_tipo_de_dia):
        del_tipo = [d for d in dias if grupo_de_dia(d) == grupo_de_dia(fecha)]
        if len(del_tipo) >= 2 * MIN_DIAS_MISMO_DIA:
            dias = del_tipo
    igual, todos = media(mismos), media(dias)
    return {k: (1 - mezcla) * igual[k] + mezcla * todos[k] for k in claves}


def demanda_cruda(ventas: dict, claves: list, fecha: dt.date, total: float, multiplicadores: dict | None = None,
                  precalculadas: dict | None = None) -> dict | None:
    """{clave: unidades esperadas de venta del día}: total del día x parte de cada producto (x multiplicador aprendido, renormalizado)."""
    p = partes(ventas, claves, fecha, precalculadas=precalculadas)
    if p is None:
        return None
    if multiplicadores:
        crudo = {k: v * multiplicadores.get(k, 1.0) for k, v in p.items()}
        suma = sum(crudo.values())
        p = {k: v / suma for k, v in crudo.items()} if suma else p
    return {k: total * v for k, v in p.items()}


def observaciones_virtuales(ventas: dict, claves: list, pronostico_por_dia: dict, hoy: dt.date, dias: int = 56, nombres: dict | None = None) -> list:
    """Compara, día por día, el plan CRUDO del sistema (hecho solo con lo anterior a ese día) contra lo vendido: es la materia prima del
    aprendizaje (aprendizaje_plan.aprender). No usa ningún plan de papel."""
    import aprendizaje_plan as ap

    nombres = nombres or {}
    obs = []
    pre = precalcular_partes(ventas, claves)
    for d in sorted(pronostico_por_dia):
        if d >= hoy or (hoy - d).days > dias or d not in ventas:
            continue
        crudo = demanda_cruda(ventas, claves, d, pronostico_por_dia[d], precalculadas=pre)
        if crudo is None:
            continue
        for k, v in crudo.items():
            if v > 0:
                obs.append(ap.Obs(d, k, nombres.get(k, k), float(v), float(ventas[d].get(k, 0.0))))
    return obs


# --------------------------------------------------------------------------------------------- horas y noche

def perfil_horario(ventas_hora: dict, claves: list, fecha: dt.date, dias: int = DIAS_PERFIL) -> dict:
    """{clave: [peso de horneado para las horas 7..17]} (suman 1). `ventas_hora` = {fecha: {clave: [24 unidades por hora]}}.
    Turno matutino (7-12): la tanda de las 7 cubre lo vendido antes de las 9; las de las 8 a las 11 cubren la hora siguiente (9 a 12);
    lo vendido de 13 a 18 sale de las tandas de las 10, 11 y 12 a partes iguales. Turno vespertino: lo vendido desde las 18:00 sale de
    las tandas de las 15, 16 y 17 a partes iguales. Del mismo tipo de día (fin de semana o entre semana); con poca venta propia, el
    perfil de todo el catálogo."""
    tipo = fecha.weekday() >= 5
    dias_ok = [d for d in ventas_hora if d < fecha and (fecha - d).days <= dias and (d.weekday() >= 5) == tipo]
    suma = {k: [0.0] * 24 for k in claves}
    for d in dias_ok:
        for k, horas in ventas_hora[d].items():
            if k in suma:
                for h in range(24):
                    suma[k][h] += horas[h]

    def a_pesos(horas):
        w = dict.fromkeys(HORAS_HORNEADO, 0.0)
        w[7] = sum(horas[:9])
        for h in (8, 9, 10, 11):
            w[h] += horas[h + 1]
        for h in (10, 11, 12):
            w[h] += sum(horas[13:CORTE_NOCHE]) / 3
        for h in (15, 16, 17):
            w[h] += sum(horas[CORTE_NOCHE:]) / 3
        t = sum(w.values())
        return [w[h] / t for h in HORAS_HORNEADO] if t > 0 else None

    general = a_pesos([sum(suma[k][h] for k in claves) for h in range(24)])
    por_defecto = general or [1.0 / len(HORAS_HORNEADO)] * len(HORAS_HORNEADO)
    salida = {}
    for k in claves:
        propio = a_pesos(suma[k]) if sum(suma[k]) >= MIN_UNIDADES_PERFIL else None
        salida[k] = propio or por_defecto
    return salida


@dataclass
class Noche:
    extra_dia: tuple = (0.0, 0.0, 0.0)          # unidades extra del catálogo para las opciones 1/2/3 (la 1 es la base: 0)
    reparto: dict = field(default_factory=dict)  # {clave: parte de la venta de la noche (desde las 18:00)}
    pendiente: float | None = None               # unidades más por cada mil pesos vendidos antes de la hora de decisión (13:00)
    n_dias: int = 0


def calcular_noche(ventas_hora: dict, importes: dict, claves: list, umbrales: tuple, hoy: dt.date, dias: int = DIAS_PERFIL) -> Noche:
    """Cuánto más se vende desde las 18:00 cuando las ventas (todo el menú, miles de pesos) hasta la 1pm son más altas (`importes` =
    {fecha: pesos antes de las 13:00}). Regresión lineal simple sobre los últimos `dias`; la opción k trae pendiente x (umbral_k -
    umbral_1) unidades extra."""
    xs, ys = [], []
    tarde = {k: 0.0 for k in claves}
    for d, dia in ventas_hora.items():
        if d >= hoy or (hoy - d).days > dias or d not in importes:
            continue
        u = 0.0
        for k, horas in dia.items():
            if k in tarde:
                t = sum(horas[CORTE_NOCHE:])
                u += t
                tarde[k] += t
        xs.append(importes[d] / 1000.0)
        ys.append(u)
    if len(xs) < 14 or len(umbrales) != 3:
        return Noche()
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    pend = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var > 1e-9 else 0.0
    pend = max(0.0, pend)
    total_tarde = sum(tarde.values())
    reparto = {k: v / total_tarde for k, v in tarde.items()} if total_tarde > 0 else {}
    return Noche(extra_dia=tuple(pend * (u - umbrales[0]) for u in umbrales), reparto=reparto, pendiente=pend, n_dias=len(xs))


# --------------------------------------------------------------------------------------------- el plan

def _charolas(cantidad: float, charola: int) -> int:
    """Piezas (múltiplo de la charola) para `cantidad`: redondeo normal, pero una charola entera si hace falta al menos el 40 %."""
    n = int(cantidad / charola + 0.5)
    if n == 0 and cantidad >= 0.4 * charola:
        n = 1
    return n * charola


@dataclass
class Insumos:
    """Todo lo que el sistema necesita para dibujar el plan de cualquier fecha (se calcula una vez y se guarda en caché)."""
    catalogo: Catalogo
    ventas: dict                       # {fecha: {clave_catálogo: unidades}} (todo el historial)
    pronosticos: dict                  # {fecha: Pronostico} del total del catálogo (honestos en el pasado)
    ventas_hora: dict                  # ventas por hora (últimas 8 semanas): {fecha: {clave_catálogo: [24]}}
    noche: Noche
    multiplicadores: dict = field(default_factory=dict)  # los que SÍ se aplican (vacío si la prueba histórica no muestra ganancia)
    ajustes: dict = field(default_factory=dict)          # lo aprendido por producto, aplique o no (para mostrarlo)
    prueba_mezcla: dict | None = None                    # prueba histórica de los multiplicadores
    colchones: dict = field(default_factory=dict)       # {clave: ajuste del colchón en puntos} aprendido de sobras y merma
    fuera_del_catalogo: list = field(default_factory=list)
    umbrales: tuple = ()                                 # (38, 42, 46): ventas (miles de pesos) a la 1pm que definen las opciones 1/2/3


def solo_manana(clave: str) -> bool:
    """Pan de muerto, panqués y muffins se hornean todo en el turno de la mañana (regla de las hojas semanales)."""
    return bool(set(clave.split()) & {"muerto", "panque", "muffin"})


def fase_ciclo(clave: str) -> int | None:
    """Fase (0, 1 o 2) del ciclo L-M-X de un panqué o muffin según su sabor; None si no es de ese ciclo. Los sabores de la fase 0 son
    plátano y café de olla, de la 1 zanahoria y blueberries, de la 2 elote y manzana."""
    palabras = clave.split()
    if "panque" not in palabras and "muffin" not in palabras:
        return None
    for p in palabras:
        if p in FASES_CICLO:
            return FASES_CICLO[p]
    return None


def dias_cubiertos(fecha: dt.date, fase: int) -> list | None:
    """Si `fecha` es día de producción de la fase (lunes a domingo = fases 0,1,2,0,1,2,0), los días que cubre lo que se hace ese día:
    desde `fecha` hasta el día anterior al siguiente día de producción de la misma fase. None si ese día no se produce."""
    if fecha.weekday() % 3 != fase:
        return None
    cubiertos = [fecha]
    d = fecha + dt.timedelta(days=1)
    while d.weekday() % 3 != fase:
        cubiertos.append(d)
        d += dt.timedelta(days=1)
    return cubiertos


def _demanda_de(ins: Insumos, fecha: dt.date, usar: bool, cache: dict, total_dia: float | None = None) -> dict | None:
    if fecha in cache:
        return cache[fecha]
    p = ins.pronosticos.get(fecha)
    total = total_dia if total_dia is not None else ((p.total if usar else p.base) if p is not None else None)
    demanda = demanda_cruda(ins.ventas, ins.catalogo.claves, fecha, total, ins.multiplicadores if usar else None) if total is not None else None
    cache[fecha] = demanda
    return demanda


def plan_del_dia(ins: Insumos, fecha: dt.date, colchon: float = COLCHON_DEFECTO, usar_aprendizaje: bool = True,
                 total_dia: float | None = None) -> tuple[Plan, dict] | None:
    """(Plan, detalle) del día `fecha` con la hoja del catálogo. `detalle` = {"total": pronóstico, "demanda": {clave: unidades},
    "colchon": {clave: colchón usado}}. None si aún no hay historia suficiente."""
    claves = ins.catalogo.claves
    cache: dict = {}
    demanda = _demanda_de(ins, fecha, usar_aprendizaje, cache, total_dia)
    if demanda is None:
        return None
    total = total_dia if total_dia is not None else (ins.pronosticos[fecha].total if usar_aprendizaje else ins.pronosticos[fecha].base)
    perfiles = perfil_horario(ins.ventas_hora, claves, fecha)
    colchones = {k: min(COLCHON_MAX, max(0.0, colchon + (ins.colchones.get(k, 0.0) if usar_aprendizaje else 0.0))) for k in claves}
    extra = ins.noche.extra_dia
    elegibles = [i for i in ins.catalogo.items if not solo_manana(i.clave) and fase_ciclo(i.clave) is None]
    por_opcion = []
    for e in extra:                  # cada opción: el extra del día repartido entre productos por lo que vendían de noche, en media docena/docena
        ideales = {i.clave: e * ins.noche.reparto.get(i.clave, 0.0) * (1 + colchones[i.clave]) for i in elegibles}
        unidades = {i.clave: min(i.charola, UNIDAD_OPCIONES) for i in elegibles}
        por_opcion.append(plan_dia._asignar(ideales, unidades, int(round(sum(ideales.values())))) if sum(ideales.values()) > 0 else {})
    filas = []
    for item in ins.catalogo.items:
        k = item.clave
        fase = fase_ciclo(k)
        solo_am = solo_manana(k)
        opciones = [po.get(k, 0) for po in por_opcion] if (por_opcion and not solo_am and fase is None) else [0, 0, 0]
        if fase is not None:                                   # panqués y muffins: una producción para varios días, guardada en el refri
            cubiertos = dias_cubiertos(fecha, fase)
            total_5 = 0
            if cubiertos is not None:
                necesita = 0.0
                for dj in cubiertos:
                    dem = demanda if dj == fecha else _demanda_de(ins, dj, usar_aprendizaje, cache)
                    if dem is not None:
                        necesita += dem[k] * (1 + colchones[k])
                total_5 = _charolas(necesita, item.charola)
        else:
            producir = demanda[k] * (1 + colchones[k])
            total_5 = _charolas(max(0.0, producir - opciones[1]), item.charola)
        horas = {}
        if total_5:
            pesos = list(perfiles[k])
            if solo_am or fase is not None:
                pesos = [p if h in HORAS_MATUTINO else 0.0 for h, p in zip(HORAS_HORNEADO, pesos)]
            n = total_5 // item.charola
            # primero el turno (con pocas charolas, repartir hora por hora mandaría todo a una hora cualquiera), luego las horas de cada turno
            peso_mat = sum(p for h, p in zip(HORAS_HORNEADO, pesos) if h in HORAS_MATUTINO)
            peso_vesp = sum(pesos) - peso_mat
            n_vesp = int(n * peso_vesp / (peso_mat + peso_vesp) + 0.5) if peso_mat + peso_vesp > 0 else 0
            horas = {}
            for horas_turno, cuantas in ((HORAS_MATUTINO, n - n_vesp), (tuple(h for h in HORAS_HORNEADO if h not in HORAS_MATUTINO), n_vesp)):
                if cuantas <= 0:
                    continue
                w = [pesos[HORAS_HORNEADO.index(h)] for h in horas_turno]
                if sum(w) <= 0:
                    w = [1.0] * len(horas_turno)
                for h, c in zip(horas_turno, plan_dia._repartir(cuantas, w)):
                    if c:
                        horas[h] = c * item.charola
        tandas = tuple(opciones) if any(opciones) else (None, None, None)
        filas.append(Fila("", item.producto, horas, sum(horas.values()), tandas, None))
    plan = Plan(fecha=fecha, punto=ins.catalogo.punto, etiquetas_tandas=ins.catalogo.etiquetas_tandas, filas=filas, fuente="sistema")
    return plan, {"total": total, "demanda": demanda, "colchon": colchones}


def evaluar_colchones(ins: Insumos, hoy: dt.date, dias: int = 56, colchones: tuple = (0.0, 0.10, 0.15, 0.20, 0.30)) -> list:
    """Con la historia de los últimos `dias` (el plan crudo de cada día hecho solo con lo anterior): para cada colchón, qué porción de las
    posiciones-día alcanzó para lo que se vendió y cuánto de lo producido sobraría (aproximado: producido - vendido, sin tope por
    stock). Sirve para elegir el colchón con datos."""
    claves = ins.catalogo.claves
    filas = {c: [0, 0, 0.0, 0.0] for c in colchones}
    pre = precalcular_partes(ins.ventas, claves)
    for d in sorted(ins.pronosticos):
        if d >= hoy or (hoy - d).days > dias or d not in ins.ventas:
            continue
        crudo = demanda_cruda(ins.ventas, claves, d, ins.pronosticos[d].total, precalculadas=pre)
        if crudo is None:
            continue
        for k in claves:
            vendido = ins.ventas[d].get(k, 0.0)
            if crudo[k] <= 0 and vendido <= 0:
                continue
            for c in colchones:
                producido = crudo[k] * (1 + c)
                f = filas[c]
                f[0] += 1
                f[1] += producido >= vendido
                f[2] += producido
                f[3] += max(0.0, producido - vendido)
    return [{"colchon": c, "alcanza": f[1] / f[0] if f[0] else None, "sobra": f[3] / f[2] if f[2] else None} for c, f in filas.items()]


# --------------------------------------------------------------------------------------------- sobras al cierre

SOBRAS_DIAS = 56
SOBRAS_MIN_DIAS = 5


MERMA_BAJA, MERMA_ALTA = 0.10, 0.20        # merma / vendido (en 8 semanas) a partir del cual se recorta el colchón 5 y 10 puntos


def colchones_por_sobras(sobras: dict, ventas: dict, hoy: dt.date, merma: dict | None = None) -> dict:
    """{clave: ajuste del colchón EN PUNTOS} (+0.05 = cinco puntos más que el colchón base; solo aparecen los productos con ajuste distinto
    de cero). El colchón base lo da el deslizador del dashboard, así el ajuste lo respeta en vez de pisarlo.

    1. Conteo manual de sobras (`sobras` = {fecha: {clave: piezas}}), productos con al menos 5 días contados en las últimas 8 semanas: se
       agotó (sobra 0) en 25-40 % de los días: +5 puntos; en más del 40 %: +10. Sobra en promedio 15-25 % de lo vendido: -5 puntos; más de 25 %:
       -10 (si se agota poco).
    2. Merma del chat (`merma` = {fecha: {clave: piezas}} SOLO de días con reporte; lo que no aparece cuenta como 0), para los productos que no
       tienen conteo manual y tienen al menos 5 días con reporte y venta: merma/vendido de 10-20 %: -5 puntos; más de 20 %: -10. La merma NUNCA
       sube el colchón: que no haya merma no dice que se agotó (para eso está el conteo manual con la hora en que se acabó).
    Se asume que se hornea según el plan del sistema; sin dato de producción real esa es la mejor lectura de una sobra."""
    por_producto: dict = {}
    for d, dia in sobras.items():
        if d >= hoy or (hoy - d).days > SOBRAS_DIAS or d not in ventas:
            continue
        for k, quedo in dia.items():
            if quedo is None:                          # solo se anotó otra cosa (lo horneado, la hora): no es un conteo de sobras
                continue
            vendido = ventas[d].get(k, 0.0)
            por_producto.setdefault(k, []).append((quedo, vendido))
    salida: dict = {}
    contados = set()
    for k, lista in por_producto.items():
        if len(lista) < SOBRAS_MIN_DIAS:
            continue
        contados.add(k)
        agotado = sum(1 for q, _ in lista if q <= 0) / len(lista)
        con_venta = [(q, v) for q, v in lista if v > 0]
        exceso = statistics.fmean(q / v for q, v in con_venta) if con_venta else 0.0
        ajuste = 0.0
        if agotado > 0.40:
            ajuste = 0.10
        elif agotado >= 0.25:
            ajuste = 0.05
        elif exceso > 0.25:
            ajuste = -0.10
        elif exceso >= 0.15:
            ajuste = -0.05
        if ajuste:
            salida[k] = ajuste
    if merma:
        tirado: dict = {}
        vendido_t: dict = {}
        dias_rep: dict = {}
        for d, dia in merma.items():
            if d >= hoy or (hoy - d).days > SOBRAS_DIAS or d not in ventas:
                continue
            for k, v in ventas[d].items():
                if v > 0:
                    vendido_t[k] = vendido_t.get(k, 0.0) + v
                    tirado[k] = tirado.get(k, 0.0) + dia.get(k, 0.0)
                    dias_rep[k] = dias_rep.get(k, 0) + 1
        for k, v in vendido_t.items():
            if k in contados or dias_rep[k] < SOBRAS_MIN_DIAS:
                continue
            r = tirado[k] / v
            ajuste = -0.10 if r >= MERMA_ALTA else (-0.05 if r >= MERMA_BAJA else 0.0)
            if ajuste:
                salida[k] = ajuste
    return salida


# --------------------------------------------------------------------------------------------- cargadores (base de datos)

def ventas_por_hora(engine, sucursal: str | None, desde: dt.date, hasta: dt.date) -> dict:
    """{fecha: {clave_de_caja: [unidades por hora 0..23]}} de Panadería + Pastelería (sin bolsas) para desde <= fecha < hasta."""
    from sqlalchemy import text

    import metrics

    sql = ("SELECT fecha, platillo, CAST(substr(hora_cierre, 12, 2) AS INTEGER) AS h, SUM(cantidad) AS u FROM sales_lines "
           "WHERE tipo_grupo IN ('PANADERIA', 'PASTELERIA')" + metrics.EXCLUIR_BOLSA_SQL +
           " AND hora_cierre IS NOT NULL AND hora_cierre != '' AND fecha >= :d AND fecha < :h")
    params: dict = {"d": desde.isoformat(), "h": hasta.isoformat()}
    if sucursal:
        sql += " AND sucursal = :s"
        params["s"] = sucursal
    sql += " GROUP BY fecha, platillo, h"
    salida: dict = {}
    with engine.connect() as conn:
        for r in conn.execute(text(sql), params).mappings():
            h = int(r["h"])
            if not 0 <= h <= 23:
                continue
            dia = salida.setdefault(dt.date.fromisoformat(str(r["fecha"])[:10]), {})
            horas = dia.setdefault(plan_dia.clave_producto(r["platillo"] or ""), [0.0] * 24)
            horas[h] += float(r["u"] or 0)
    return salida


def importes_antes_de(engine, sucursal: str | None, desde: dt.date, hasta: dt.date, hora: int = HORA_OPCIONES) -> dict:
    """{fecha: pesos vendidos (todo el menú) antes de las `hora`:00}: lo que la hoja usa para elegir la opción 1/2/3 (a la 1pm)."""
    from sqlalchemy import text

    sql = ("SELECT fecha, SUM(importe) AS i FROM sales_lines WHERE hora_cierre IS NOT NULL AND hora_cierre != '' "
           "AND CAST(substr(hora_cierre, 12, 2) AS INTEGER) < :hora AND fecha >= :d AND fecha < :h")
    params: dict = {"d": desde.isoformat(), "h": hasta.isoformat(), "hora": int(hora)}
    if sucursal:
        sql += " AND sucursal = :s"
        params["s"] = sucursal
    sql += " GROUP BY fecha"
    with engine.connect() as conn:
        return {dt.date.fromisoformat(str(r["fecha"])[:10]): float(r["i"] or 0) for r in conn.execute(text(sql), params).mappings()}


# viven en pronostico.py (el dashboard en la nube las usa sin cargar el módulo del plan); aquí se reexportan
from pronostico import DIAS_REVISADOS, HORA_CIERRE_MINIMA, dias_incompletos, es_dia_incompleto  # noqa: E402,F401


def _con_cache(ruta, sucursal: str, tipo: str, cargar, desde: dt.date, hasta: dt.date, rehacer_dias: int = 7) -> dict:
    """Ventas por día con caché en disco: los días viejos no cambian, así que solo se consulta a la base desde `rehacer_dias` antes del
    último día guardado (por si un archivo llegó tarde). `cargar(desde, hasta)` devuelve {fecha: carga}. Sin `ruta`, sin caché. Para
    empezar de cero, borrar el archivo."""
    if ruta is None:
        return cargar(desde, hasta)
    ruta = Path(ruta)
    try:
        estado = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        estado = {}
    suc = estado.setdefault(sucursal, {})
    dias = suc.setdefault(tipo, {})
    marca = suc.get(tipo + "_desde")
    inicio = desde
    if dias and marca and dt.date.fromisoformat(marca) <= desde:
        inicio = max(desde, dt.date.fromisoformat(max(dias)) - dt.timedelta(days=rehacer_dias))
    cambio = marca is None or desde < dt.date.fromisoformat(marca)
    if cambio:
        suc[tipo + "_desde"] = desde.isoformat()
    for d, carga in cargar(inicio, hasta).items():
        if dias.get(d.isoformat()) != carga:
            dias[d.isoformat()] = carga
            cambio = True
    for viejo in [k for k in dias if k < (desde - dt.timedelta(days=14)).isoformat()]:      # lo anterior a la ventana ya no se pide
        del dias[viejo]
        cambio = True
    if cambio:
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return {dt.date.fromisoformat(k): v for k, v in dias.items() if desde <= dt.date.fromisoformat(k) < hasta}


def horas_del_catalogo(horas_crudas: dict, claves_catalogo: list) -> dict:
    """Lo mismo que ventas_del_catalogo, para las ventas por hora: suma las líneas de caja que son el mismo producto del catálogo."""
    mapa = mapear_nombres(claves_catalogo, {k for dia in horas_crudas.values() for k in dia})
    salida: dict = {}
    for fecha, dia in horas_crudas.items():
        sal = salida.setdefault(fecha, {})
        for k, horas in dia.items():
            if k in mapa:
                acum = sal.setdefault(mapa[k], [0.0] * 24)
                for h in range(24):
                    acum[h] += horas[h]
    return salida


def preparar(engine, sucursal: str, planes: dict, hoy: dt.date, temperaturas: dict, sobras: dict | None = None,
             ruta_cache: Path | str | None = None, umbrales: tuple | None = None, merma: dict | None = None) -> Insumos | None:
    """Junta todo lo necesario para dibujar el plan de cualquier fecha (ver Insumos). `planes` solo aporta el catálogo.
    `ruta_cache`: archivo donde se guardan las ventas ya consultadas (sin él, cada vez se consulta todo: ~20 s).
    `umbrales`: las cifras de las opciones 1/2/3 (de la hoja semanal); sin ellas, las de la cabecera del plan diario."""
    import aprendizaje_plan as ap
    import pronostico

    cat = catalogo(planes)
    if cat is None:
        return None
    crudas = _con_cache(ruta_cache, sucursal, "dia", lambda d, h: ap.vendido_por_dia(engine, sucursal, d, h), dt.date(2024, 1, 1), hoy)
    incompletos = dias_incompletos(engine, sucursal, hoy)
    for d in incompletos:
        crudas.pop(d, None)
    if not crudas:
        return None
    ventas, _ = ventas_del_catalogo(crudas, cat.claves)
    reciente = {d: v for d, v in crudas.items() if (hoy - d).days <= SOBRAS_DIAS}
    _, fuera = ventas_del_catalogo(reciente, cat.claves)
    serie = {d: t for d, t in totales_por_dia(ventas).items() if t > 0}
    filas = pronostico.pronosticar_rango(serie, temperaturas, hoy, min(serie), hoy + dt.timedelta(days=14))
    pronosticos = {dt.date.fromisoformat(f["fecha"]): f["detalle"] for f in filas if f.get("detalle") is not None}
    desde_horas = hoy - dt.timedelta(days=DIAS_PERFIL + 7)
    horas_crudas = _con_cache(ruta_cache, sucursal, "hora", lambda d, h: ventas_por_hora(engine, sucursal, d, h), desde_horas, hoy)
    for d in incompletos:
        horas_crudas.pop(d, None)
    ventas_hora = horas_del_catalogo(horas_crudas, cat.claves)
    umbrales = tuple(umbrales) if umbrales else umbrales_de_etiquetas(cat.etiquetas_tandas)
    noche = calcular_noche(ventas_hora, importes_antes_de(engine, sucursal, desde_horas, hoy), cat.claves, umbrales, hoy)
    nombres = {i.clave: i.producto for i in cat.items}
    obs = observaciones_virtuales(ventas, cat.claves, {d: p.total for d, p in pronosticos.items()}, hoy, nombres=nombres)
    ajustes = ap.aprender(obs, hoy)
    prueba = ap.prueba_historica(obs)
    # los multiplicadores solo se usan si la prueba histórica honesta muestra que mejoran al plan del sistema (al menos 1 % menos error)
    util = bool(prueba and prueba["error_corregido"] < 0.99 * prueba["error_base"])
    return Insumos(catalogo=cat, ventas=ventas, pronosticos=pronosticos, ventas_hora=ventas_hora, noche=noche,
                   multiplicadores=ap.multiplicadores(ajustes) if util else {}, ajustes=ajustes, prueba_mezcla=prueba,
                   colchones=colchones_por_sobras(sobras or {}, ventas, hoy, merma), fuera_del_catalogo=fuera, umbrales=umbrales)


def umbrales_de_etiquetas(etiquetas: tuple) -> tuple:
    """(32.0, 40.0, 45.0) a partir de las etiquetas de las columnas de la hoja ("1\\n32", ...); () si no se pueden leer."""
    import re

    salida = []
    for e in etiquetas:
        n = re.findall(r"\d+(?:[.,]\d+)?", str(e).split("\n")[-1])
        if n and "\n" in str(e):
            salida.append(float(n[0].replace(",", ".")))
    return tuple(salida) if len(salida) == 3 else ()
