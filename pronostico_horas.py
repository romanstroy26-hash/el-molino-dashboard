"""Pronóstico del día para las pantallas «Главная» y «Продажи по часам» (local y nube): la curva por hora conserva la forma histórica del
mismo día de la semana, pero su NIVEL sale de pronostico.py (últimos 7 días, temperatura, festivos). Solo necesita las ventas, así que
funciona igual en el dashboard de la nube (sin planes en PDF ni módulos del plan)."""

from __future__ import annotations

import datetime as dt

import streamlit as st

import clima
import metrics
import pronostico
import tiempo

CACHE_TTL = 300


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def _temperaturas(desde: str, hoy: str) -> dict:
    return clima.temperaturas(dt.date.fromisoformat(desde), dt.date.fromisoformat(hoy))


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def totales_mejorados(_engine, sucursal, fecha: str, hoy: str):
    """Pronóstico del día completo (todas las categorías) con pronostico.py: (importe, unidades); None en lo que no se pueda calcular.
    Los días pasados llevan su pronóstico honesto (solo con lo anterior a ellos); hoy y los siguientes, el de hoy con todo lo cerrado."""
    f, h = dt.date.fromisoformat(fecha), dt.date.fromisoformat(hoy)
    excluir = pronostico.dias_incompletos(_engine, sucursal, h)
    series = {campo: pronostico.serie_total(_engine, sucursal, campo, excluir) for campo in ("importe", "cantidad")}
    primero = min((min(s) for s in series.values() if s), default=None)
    temps = _temperaturas(primero.isoformat(), hoy) if primero else {}
    if primero and not temps:
        _temperaturas.clear()          # sin internet no se recuerda el vacío: la próxima vez se reintenta
    salida = []
    for campo in ("importe", "cantidad"):
        fila = pronostico.pronosticar_rango(series[campo], temps, h, f, f)[0] if series[campo] else None
        salida.append(fila["pronostico_unidades"] if fila else None)
    return tuple(salida)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def dias_parciales(_engine, sucursal, hoy: str) -> frozenset:
    """Días recientes (hoy incluido) cargados a medias: su última venta fue antes de las 19:00."""
    return frozenset(pronostico.dias_incompletos(_engine, sucursal, dt.date.fromisoformat(hoy), incluir_hoy=True))


def datos_por_hora_mejorados(engine, fecha: str, sucursal, datos_hora: dict) -> dict:
    """`datos_hora` de metrics.ventas_por_hora con la curva de pronóstico llevada al nivel del día de pronostico.py (el promedio histórico
    por hora no ve la racha reciente, el clima ni los festivos y por eso quedaba por debajo de las ventas). Si algo falla, se devuelve igual."""
    if not datos_hora.get("n_dias_promedio"):
        return datos_hora
    try:
        importe, unidades = totales_mejorados(engine, sucursal, fecha, tiempo.hoy().isoformat())
        return pronostico.escalar_por_hora(datos_hora, importe, unidades)
    except Exception:              # noqa: BLE001 -- un fallo del pronóstico mejorado no debe tumbar la pantalla: queda el promedio simple
        return datos_hora


def pronostico_dia_total_mejorado(engine, fecha: str, sucursal) -> dict | None:
    """Como metrics.pronostico_dia_total (para «Ожидается завтра»), pero con el nivel de pronostico.py."""
    viejo = metrics.pronostico_dia_total(engine, fecha, sucursal=sucursal)
    if not viejo:
        return viejo
    try:
        importe, unidades = totales_mejorados(engine, sucursal, fecha, tiempo.hoy().isoformat())
    except Exception:              # noqa: BLE001
        return viejo
    return {**viejo,
            "ventas_totales": round(importe, 2) if importe else viejo["ventas_totales"],
            "unidades": round(unidades, 2) if unidades else viejo["unidades"]}


def nota_de_escala(datos_hora: dict) -> str:
    """Frase sobre cuánto se movió el nivel del día respecto al promedio simple (vacía si no se movió)."""
    f = datos_hora.get("factor_importe")
    if not f or abs(f - 1) < 0.02:
        return ""
    return f" Простое среднее по таким дням давало бы {1 / f:.0%} от этого уровня (последние недели идут {'выше' if f > 1 else 'ниже'} среднего)."
