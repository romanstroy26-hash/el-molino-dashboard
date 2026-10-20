"""Pronóstico diario de unidades de Panadería, con tres correcciones sobre el promedio del mismo día de la semana.

Base: promedio del MISMO día de la semana, los días recientes pesan más (semivida 8 semanas), valores extremos recortados
(el mismo método de metrics.panaderia_real_y_pronostico). Encima, tres correcciones -- cada una medida con una prueba histórica
honesta (cada día se pronostica SOLO con los días anteriores; el pronóstico que el dashboard mostraba para días pasados usaba
también los días de después y por eso salía más optimista):

  1. NIVEL: promedio (geométrico) de real/base de los últimos 7 días normales cerrados (sin festivos ni vísperas, cada día
     recortado a +-30 %), entre 0.85 y 1.20. Sigue al negocio cuando cambia de ritmo (octubre, estacionalidad, apertura).
  2. TEMPERATURA: cuánto más caliente (o frío) está el día que la última semana. Con 560 días de El Molino Ruso, cada grado de más
     resta ~3 % a la venta de panadería; la pendiente se aprende sola de los residuos pasados y no pasa de +-20 %.
  3. FESTIVOS: lo que pasó la última vez que cayó el mismo festivo (Madres, Independencia, Nochebuena...), con prudencia: cada
     festivo ocurre una vez al año y su efecto se acerca a 0 mientras haya pocas observaciones (tope +-50 %).

Con 559 días de prueba el error medio pasó de 13.5 % a 9.5 % (con la temperatura del día conocida; con un error de 1.5 C en la
temperatura prevista, 9.8 %). Lo que NO ayudó y por eso no está: quincena / día de pago (efecto dentro del ruido), la lluvia
(+0.16 puntos y un pronóstico de lluvia poco fiable). Los festivos siguen siendo difíciles (~22 % de error): se avisa.

Puro, sin base de datos: la serie diaria y las temperaturas llegan como diccionarios.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import metrics

SEMIVIDA_SEMANAS = 8.0
MIN_HISTORIA = 4              # días del mismo día de la semana necesarios para pronosticar
NIVEL_DIAS = 7
NIVEL_MIN, NIVEL_MAX = 0.85, 1.20
NIVEL_RECORTE = 0.30          # log-residuo máximo que un solo día aporta al nivel
NIVEL_MIN_DIAS = 4
DIA_INCOMPLETO = 0.5          # un día con menos de la mitad de lo previsto no está cerrado: no cuenta para el nivel
TEMP_VENTANA = 7              # días anteriores contra los que se compara la temperatura
TEMP_MIN_OBS = 60             # observaciones para fiarse de la pendiente
TEMP_TOPE = 0.20
FESTIVO_PRIOR = 0.5           # "observaciones de duda": con 1 sola vez que cayó el festivo se aplica 2/3 del efecto
FESTIVO_TOPE = 0.50


def festivo(fecha: dt.date) -> str | None:
    return metrics._festivo_exacto(fecha)


def es_especial(fecha: dt.date) -> bool:
    """Festivo o víspera de festivo: los días donde el nivel y la pendiente de temperatura no deben aprender."""
    return bool(festivo(fecha) or festivo(fecha + dt.timedelta(days=1)))


@dataclass
class Pronostico:
    fecha: dt.date
    total: float
    base: float
    nivel: float = 1.0
    temperatura: float = 1.0          # multiplicador por la temperatura
    festivo_mult: float = 1.0
    temp_max: float | None = None
    anomalia: float | None = None     # grados contra el promedio de los 7 días anteriores
    festivo: str | None = None
    especial: bool = False
    festivo_previo: tuple | None = None     # (fecha, unidades) la última vez que cayó el mismo festivo


@dataclass
class _Estado:
    n: int = 0
    sx: float = 0.0
    sy: float = 0.0
    sxx: float = 0.0
    sxy: float = 0.0


class Modelo:
    """Se alimenta día por día (en orden) con `observar`; `predecir` solo usa lo observado antes de la fecha pedida."""

    def __init__(self, temperaturas: dict | None = None):
        self.temp = temperaturas or {}
        self.real: dict = {}
        self.por_dia_semana: dict = {i: [] for i in range(7)}
        self.residuos: list = []                  # (fecha, log(real/base)) de días normales y completos
        self.reg = _Estado()
        self.festivos: dict = {}                  # nombre -> [residuo tras nivel y temperatura]
        self.festivos_fechas: dict = {}           # nombre -> [(fecha, real)]

    # -------------------------------------------------------------------------- piezas
    def base(self, fecha: dt.date) -> float | None:
        historia = [d for d in self.por_dia_semana[fecha.weekday()] if d < fecha]
        if len(historia) < MIN_HISTORIA:
            return None
        valores = metrics._recortar_atipicos([self.real[d] for d in historia])
        pesos = [0.5 ** ((fecha - d).days / 7 / SEMIVIDA_SEMANAS) for d in historia]
        return sum(v * w for v, w in zip(valores, pesos)) / sum(pesos)

    def nivel(self, fecha: dt.date) -> float:
        previos = [r for d, r in self.residuos if d < fecha][-NIVEL_DIAS:]
        if len(previos) < NIVEL_MIN_DIAS:
            return 1.0
        media = sum(max(-NIVEL_RECORTE, min(NIVEL_RECORTE, r)) for r in previos) / len(previos)
        return min(NIVEL_MAX, max(NIVEL_MIN, math.exp(media)))

    def anomalia(self, fecha: dt.date, temp_dia: float | None) -> float | None:
        if temp_dia is None:
            return None
        previas = [self.temp[d] for d in (fecha - dt.timedelta(days=i) for i in range(1, TEMP_VENTANA + 1)) if self.temp.get(d) is not None]
        if len(previas) < 4:
            return None
        return temp_dia - sum(previas) / len(previas)

    def _pendiente(self) -> float | None:
        r = self.reg
        if r.n < TEMP_MIN_OBS:
            return None
        den = r.n * r.sxx - r.sx * r.sx
        return (r.n * r.sxy - r.sx * r.sy) / den if den > 1e-9 else None

    def _efecto_festivo(self, nombre: str) -> float:
        previos = self.festivos.get(nombre, [])
        if not previos:
            return 0.0
        efecto = sum(previos) / len(previos) * len(previos) / (len(previos) + FESTIVO_PRIOR)
        return max(-FESTIVO_TOPE, min(FESTIVO_TOPE, efecto))

    # -------------------------------------------------------------------------- uso
    def predecir(self, fecha: dt.date, temp_dia: float | None = None) -> Pronostico | None:
        b = self.base(fecha)
        if b is None:
            return None
        if temp_dia is None:
            temp_dia = self.temp.get(fecha)
        nivel = self.nivel(fecha)
        anom = self.anomalia(fecha, temp_dia)
        pend = self._pendiente()
        adj = max(-TEMP_TOPE, min(TEMP_TOPE, pend * anom)) if pend is not None and anom is not None else 0.0
        nombre = festivo(fecha)
        efecto = self._efecto_festivo(nombre) if nombre else 0.0
        previo = self.festivos_fechas.get(nombre, [None])[-1] if nombre else None
        return Pronostico(fecha=fecha, total=b * nivel * math.exp(adj + efecto), base=b, nivel=nivel, temperatura=math.exp(adj),
                          festivo_mult=math.exp(efecto), temp_max=temp_dia, anomalia=anom, festivo=nombre,
                          especial=es_especial(fecha), festivo_previo=previo)

    def observar(self, fecha: dt.date, real: float, temp_dia: float | None = None) -> Pronostico | None:
        """Pronostica `fecha` con lo anterior (se devuelve: es el pronóstico honesto de ese día) y después aprende de su venta real."""
        if temp_dia is None:
            temp_dia = self.temp.get(fecha)
        p = self.predecir(fecha, temp_dia)
        if p is not None and real > 0:
            r = math.log(real / p.base)
            nombre = festivo(fecha)
            if not p.especial and real >= DIA_INCOMPLETO * p.total:
                self.residuos.append((fecha, r))
                if p.anomalia is not None:
                    y = r - math.log(p.nivel)
                    e = self.reg
                    e.n, e.sx, e.sy, e.sxx, e.sxy = e.n + 1, e.sx + p.anomalia, e.sy + y, e.sxx + p.anomalia ** 2, e.sxy + p.anomalia * y
            if nombre:
                self.festivos.setdefault(nombre, []).append(r - math.log(p.nivel) - math.log(p.temperatura))
        if festivo(fecha):
            self.festivos_fechas.setdefault(festivo(fecha), []).append((fecha, real))
        self.real[fecha] = real
        self.por_dia_semana[fecha.weekday()].append(fecha)
        return p


HORA_CIERRE_MINIMA = 19.0       # un día cuya última venta fue antes de esta hora quedó cargado a medias (la exportación se hizo en la mañana)
DIAS_REVISADOS = 3


def es_dia_incompleto(ultima_hora: float) -> bool:
    return ultima_hora < HORA_CIERRE_MINIMA


def dias_incompletos(engine, sucursal: str | None, hoy: dt.date, dias: int = DIAS_REVISADOS, incluir_hoy: bool = False) -> set:
    """Fechas de los últimos `dias` días anteriores a `hoy` que están cargadas a medias (última venta antes de las 19:00). Un día así no debe
    entrar en el historial: su venta es una fracción y torcería el promedio del día de la semana y las partes de cada producto.
    Con `incluir_hoy` también cuenta hoy (para marcar el último punto de los gráficos)."""
    from sqlalchemy import text

    sql = ("SELECT fecha, MAX(hora_cierre) AS ult FROM sales_lines WHERE hora_cierre IS NOT NULL AND hora_cierre != '' "
           "AND fecha >= :d AND fecha " + ("<=" if incluir_hoy else "<") + " :h")
    params: dict = {"d": (hoy - dt.timedelta(days=dias)).isoformat(), "h": hoy.isoformat()}
    if sucursal:
        sql += " AND sucursal = :s"
        params["s"] = sucursal
    sql += " GROUP BY fecha"
    salida = set()
    with engine.connect() as conn:
        for r in conn.execute(text(sql), params).mappings():
            u = str(r["ult"])
            if len(u) >= 16 and es_dia_incompleto(int(u[11:13]) + int(u[14:16]) / 60.0):
                salida.add(dt.date.fromisoformat(str(r["fecha"])[:10]))
    return salida


HORA_CIERRE_DIA = 20.5          # con una venta a las 20:30 o después el día ya está cerrado (los días completos del último trimestre acaban entre 20:34 y 21:07)


def hora_ultima_venta(engine, sucursal: str | None, fecha: dt.date) -> float | None:
    """Hora decimal de la última venta del día (None si no hay ventas con hora)."""
    from sqlalchemy import text

    sql = "SELECT MAX(hora_cierre) AS ult FROM sales_lines WHERE fecha = :f AND hora_cierre IS NOT NULL AND hora_cierre != ''"
    params: dict = {"f": fecha.isoformat()}
    if sucursal:
        sql += " AND sucursal = :s"
        params["s"] = sucursal
    with engine.connect() as conn:
        u = str(conn.execute(text(sql), params).scalar() or "")
    return int(u[11:13]) + int(u[14:16]) / 60.0 if len(u) >= 16 else None


def serie_diaria(engine, sucursal: str | None, categorias: tuple = ("PANADERIA",), excluir: set | frozenset = frozenset()) -> dict:
    """{fecha: unidades vendidas} de todo el historial de la sucursal (None = todas), sin bolsas. `excluir` = días cargados a medias
    (plan_propio.dias_incompletos): no entran, para no meter una venta parcial como si fuera un día entero."""
    from sqlalchemy import text

    sql = "SELECT fecha, SUM(cantidad) AS total FROM sales_lines WHERE tipo_grupo = ANY(:categorias)" + metrics.EXCLUIR_BOLSA_SQL
    params: dict = {"categorias": list(categorias)}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    sql += " GROUP BY fecha"
    with engine.connect() as conn:
        serie = {dt.date.fromisoformat(str(r["fecha"])[:10]): float(r["total"]) for r in conn.execute(text(sql), params).mappings()}
    return {d: v for d, v in serie.items() if d not in excluir}


def serie_total(engine, sucursal: str | None, campo: str = "cantidad", excluir: set | frozenset = frozenset()) -> dict:
    """{fecha: suma de `campo` ('cantidad' o 'importe')} con TODAS las categorías y solo líneas con hora (el mismo universo que el gráfico
    por horas de metrics.ventas_por_hora), para escalar ese gráfico con el pronóstico mejorado."""
    from sqlalchemy import text

    if campo not in ("cantidad", "importe"):
        raise ValueError(campo)
    sql = f"SELECT fecha, SUM({campo}) AS total FROM sales_lines WHERE hora_cierre IS NOT NULL AND hora_cierre != ''"
    params: dict = {}
    if sucursal:
        sql += " AND sucursal = :sucursal"
        params["sucursal"] = sucursal
    sql += " GROUP BY fecha"
    with engine.connect() as conn:
        serie = {dt.date.fromisoformat(str(r["fecha"])[:10]): float(r["total"]) for r in conn.execute(text(sql), params).mappings()}
    return {d: v for d, v in serie.items() if d not in excluir}


def escalar_por_hora(datos_hora: dict, total_importe: float | None, total_unidades: float | None, tope: float = 1.5) -> dict:
    """Copia de `datos_hora` (metrics.ventas_por_hora) con la curva de 'tipico' multiplicada por (pronóstico mejorado del día / suma de la
    curva): la FORMA por hora sigue siendo la del historial, el NIVEL del día lo da pronostico.py (nivel reciente, temperatura, festivos).
    Agrega 'factor_importe' / 'factor_unidades' (None si no se pudo escalar). Factores fuera de 1/tope..tope se ignoran (dato dudoso)."""
    horas = [dict(h) for h in datos_hora["horas"]]
    factores = {}
    for campo_total, campo_hora, total in (("factor_importe", "tipico", total_importe), ("factor_unidades", "tipico_unidades", total_unidades)):
        suma = sum(h[campo_hora] for h in horas if h[campo_hora] is not None)
        f = total / suma if total and suma > 0 else None
        if f is not None and not (1 / tope <= f <= tope):
            f = None
        factores[campo_total] = f
        if f is not None:
            for h in horas:
                if h[campo_hora] is not None:
                    h[campo_hora] = round(h[campo_hora] * f, 2)
    return {**datos_hora, "horas": horas, **factores}


def pronosticar_rango(real_por_dia: dict, temperaturas: dict, hoy: dt.date, desde: dt.date, hasta: dt.date) -> list:
    """Lista de {fecha, real_unidades, pronostico_unidades, ...} como metrics.panaderia_real_y_pronostico, pero con el pronóstico
    corregido. Los días ANTERIORES a `hoy` llevan su pronóstico honesto (solo con lo anterior a ellos); `hoy` y los siguientes, el de
    hoy con todo lo cerrado. Hoy, aunque tenga ventas parciales, no se usa para aprender."""
    modelo = Modelo(temperaturas)
    pasado: dict = {}
    for d in sorted(real_por_dia):
        if d >= hoy:
            break
        pasado[d] = modelo.observar(d, real_por_dia[d], temperaturas.get(d))
    salida = []
    d = desde
    while d <= hasta:
        p = pasado.get(d) if d < hoy else modelo.predecir(d, temperaturas.get(d))
        salida.append({
            "fecha": d.isoformat(),
            "real_unidades": round(real_por_dia[d], 2) if d in real_por_dia else None,
            "pronostico_unidades": round(p.total, 2) if p is not None else None,
            "detalle": p,
        })
        d += dt.timedelta(days=1)
    return salida


def error_historico(real_por_dia: dict, temperaturas: dict, hoy: dt.date, dias_calentamiento: int = 84) -> dict | None:
    """Error medio |real/pronóstico - 1| del modelo completo y de la base sola, ambos honestos, desde que hay `dias_calentamiento` días."""
    modelo = Modelo(temperaturas)
    primero = min(real_por_dia) if real_por_dia else None
    solo_base, completo = [], []
    for d in sorted(real_por_dia):
        if d >= hoy:
            break
        p = modelo.observar(d, real_por_dia[d], temperaturas.get(d))
        if p is None or (d - primero).days < dias_calentamiento or real_por_dia[d] <= 0:
            continue
        solo_base.append(abs(real_por_dia[d] / p.base - 1))
        completo.append(abs(real_por_dia[d] / p.total - 1))
    if not completo:
        return None
    return {"n_dias": len(completo), "error_base": sum(solo_base) / len(solo_base), "error_completo": sum(completo) / len(completo)}


# --------------------------------------------------------------------------------------------- por ritmo del día (a media jornada)
#
# A media jornada el día ya "habla": se sabe cuánto se vendió hasta esa hora, y qué parte del día suele estar vendida a esa hora
# (en El Molino Ruso, antes de las 14:00 solo el ~37 % de las piezas de Panadería: la tarde pesa más que la mañana). Pronóstico por
# ritmo = vendido / parte habitual de ese día de la semana; mezclado 50/50 con el pronóstico de la mañana. Prueba histórica honesta
# a las 14:00 (559 días): mañana 9.2 %, solo ritmo 9.1 %, mezcla 5.9 %.

CORTE_MIN = 11.0              # antes de esta hora el día aún dice muy poco
PARTE_MIN = 0.05
PESO_RITMO = 0.5
SEMIVIDA_RITMO_DIAS = 60.0


@dataclass
class PorRitmo:
    total: float                  # mezcla (lo que se recomienda usar)
    por_ritmo: float              # vendido / parte habitual
    manana: float                 # pronóstico de la mañana
    vendido: float
    parte: float                  # parte habitual del día ya vendida a esa hora (0..1)
    corte: float                  # hora decimal hasta la que se vendió (14.5 = 14:30)
    error_esperado: float | None = None     # error medio de esta mezcla a esa hora en la historia (prueba honesta)


def parte_habitual(parciales: dict, totales: dict, fecha: dt.date, semivida: float = SEMIVIDA_RITMO_DIAS) -> float | None:
    """Parte del día ya vendida a la hora de corte en los últimos mismos días de la semana (más recientes pesan más).
    `parciales[d]` = unidades vendidas antes del corte, `totales[d]` = unidades del día completo."""
    previos = [d for d in parciales if d < fecha and d.weekday() == fecha.weekday() and totales.get(d)]
    if len(previos) < MIN_HISTORIA:
        return None
    pesos = [0.5 ** ((fecha - d).days / semivida) for d in previos]
    return sum(w * parciales[d] / totales[d] for w, d in zip(pesos, previos)) / sum(pesos)


def por_ritmo(parciales: dict, totales: dict, fecha: dt.date, vendido: float, corte: float, manana: float) -> PorRitmo | None:
    if corte < CORTE_MIN or vendido <= 0 or manana <= 0:
        return None
    parte = parte_habitual(parciales, totales, fecha)
    if parte is None or parte < PARTE_MIN:
        return None
    ritmo = vendido / parte
    return PorRitmo(total=PESO_RITMO * ritmo + (1 - PESO_RITMO) * manana, por_ritmo=ritmo, manana=manana, vendido=vendido, parte=parte, corte=corte)


def error_por_ritmo(parciales: dict, totales: dict, mananas: dict, hoy: dt.date, dias_calentamiento: int = 84) -> dict | None:
    """Prueba histórica honesta a la misma hora de corte: error medio del pronóstico de la mañana, del ritmo solo y de la mezcla.
    `mananas` = {fecha: pronóstico de la mañana de ese día} (los honestos de Modelo.observar)."""
    dias = sorted(d for d in parciales if d < hoy and d in totales and d in mananas and totales[d] > 0)
    if not dias:
        return None
    primero = dias[0]
    e_man, e_rit, e_mez = [], [], []
    for d in dias:
        if (d - primero).days < dias_calentamiento:
            continue
        parte = parte_habitual({x: parciales[x] for x in dias if x < d}, totales, d)
        if parte is None or parte < PARTE_MIN or parciales[d] <= 0:
            continue
        ritmo = parciales[d] / parte
        mezcla = PESO_RITMO * ritmo + (1 - PESO_RITMO) * mananas[d]
        e_man.append(abs(totales[d] / mananas[d] - 1))
        e_rit.append(abs(totales[d] / ritmo - 1))
        e_mez.append(abs(totales[d] / mezcla - 1))
    if not e_mez:
        return None
    n = len(e_mez)
    return {"n_dias": n, "error_manana": sum(e_man) / n, "error_ritmo": sum(e_rit) / n, "error_mezcla": sum(e_mez) / n}


def ventas_hasta_hora(engine, sucursal: str | None, corte: float, desde: dt.date, hasta: dt.date) -> dict:
    """{fecha: unidades de Panadería vendidas ANTES de la hora decimal `corte`} para los días desde..hasta-1 (fecha < hasta)."""
    from sqlalchemy import text

    sql = ("SELECT fecha, SUM(CASE WHEN CAST(substr(hora_cierre, 12, 2) AS INTEGER) + CAST(substr(hora_cierre, 15, 2) AS INTEGER) / 60.0 < :corte "
           "THEN cantidad ELSE 0 END) AS u FROM sales_lines WHERE tipo_grupo = 'PANADERIA'" + metrics.EXCLUIR_BOLSA_SQL +
           " AND hora_cierre IS NOT NULL AND hora_cierre != '' AND fecha >= :d AND fecha < :h")
    params: dict = {"corte": corte, "d": desde.isoformat(), "h": hasta.isoformat()}
    if sucursal:
        sql += " AND sucursal = :s"
        params["s"] = sucursal
    sql += " GROUP BY fecha"
    with engine.connect() as conn:
        return {dt.date.fromisoformat(str(r["fecha"])[:10]): float(r["u"] or 0) for r in conn.execute(text(sql), params).mappings()}


def ventas_de_hoy(engine, sucursal: str | None, hoy: dt.date) -> dict | None:
    """Lo vendido hoy hasta ahora: {unidades (Panadería), importe (todo el menú), corte (hora decimal de la última venta)}; None si no hay."""
    from sqlalchemy import text

    sql = ("SELECT SUM(CASE WHEN tipo_grupo = 'PANADERIA'" + metrics.EXCLUIR_BOLSA_SQL +
           " THEN cantidad ELSE 0 END) AS u, SUM(importe) AS imp, MAX(hora_cierre) AS ultima FROM sales_lines "
           "WHERE fecha = :f AND hora_cierre IS NOT NULL AND hora_cierre != ''")
    params: dict = {"f": hoy.isoformat()}
    if sucursal:
        sql += " AND sucursal = :s"
        params["s"] = sucursal
    with engine.connect() as conn:
        fila = conn.execute(text(sql), params).mappings().first()
    if not fila or not fila["ultima"]:
        return None
    ultima = str(fila["ultima"])
    return {"unidades": float(fila["u"] or 0), "importe": float(fila["imp"] or 0),
            "corte": int(ultima[11:13]) + int(ultima[14:16]) / 60.0 + 1 / 60.0}


def opcion_de_tarde(importe_miles: float, umbrales: tuple) -> int:
    """Opción 1/2/3 de las 2pm más cercana a lo vendido hasta esa hora (en miles de pesos), con las cifras de la hoja (p. ej. 32/40/45)."""
    return min(range(len(umbrales)), key=lambda i: abs(umbrales[i] - importe_miles)) + 1


def explicacion(p: Pronostico) -> list:
    """Frases para el usuario (ruso) de lo que sumó cada corrección; vacío si no hay nada que explicar."""
    partes = [f"база {p.base:.0f} шт (среднее по таким же дням недели, свежие недели весят больше)"]
    if abs(p.nivel - 1) >= 0.01:
        partes.append(f"×{p.nivel:.2f} -- последние дни продавали {'больше' if p.nivel > 1 else 'меньше'}, чем по базе")
    if abs(p.temperatura - 1) >= 0.01 and p.anomalia is not None and p.temp_max is not None:
        partes.append(f"×{p.temperatura:.2f} -- макс. {p.temp_max:.0f}°C, на {abs(p.anomalia):.0f}° {'жарче' if p.anomalia > 0 else 'холоднее'} прошлой недели")
    if p.festivo and abs(p.festivo_mult - 1) >= 0.01:
        partes.append(f"×{p.festivo_mult:.2f} -- {p.festivo}: так было в прошлый раз")
    return partes
