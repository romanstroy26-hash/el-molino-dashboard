"""Nivel de llenado de la vitrina (programa «Vitrina» con cámara, en la red privada Tailscale): lectura, guardado en la base y análisis.

El programa de la cámara mide cada minuto qué porcentaje de la mesa de pan está llena (100 % = la mesa llena en un día normal) y lo ofrece por
HTTP: /api/dias (fechas con datos) y /api/dia?fecha=AAAA-MM-DD (un punto por minuto: {"m": "HH:MM", "n": nivel o null, "e": "ok"|"noche"|"cerrada"}).
La nube no está en esa red: sync_nube.py (en el computador del dueño, con Tailscale prendido) trae los días y los guarda aquí en tramos de 5 minutos;
el dashboard lee de la base.

Definiciones (las mismas del programa de la cámara):
  - surtida: desde el primer tramo con 70 % o más; antes es el llenado de la mañana.
  - «baja»: ya surtida, hasta las 21:00 (cierre), con menos del límite de aviso (40 % por defecto).
  - noche (indicador del reglamento «vitrina llena», contada hasta el cierre): promedio y % del tiempo con 70 % o más entre las 19:00 y las 21:00.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request

from sqlalchemy import text

TABLA = "vitrina_nivel"
URL_POR_DEFECTO = "http://desktop-s2gb4kk.tail68ad7b.ts.net:8095"
TRAMO = 5                       # minutos por tramo guardado
LLENA = 70.0                    # % que cuenta como vitrina llena
UMBRAL_BAJO = 40.0              # % por debajo del cual hay que surtir
HORA_REGLAMENTO = 20.5            # el reglamento: vitrina llena hasta las 20:30; de 20:30 a 21:00 la vitrina se reduce a propósito
HORA_FIN = 21.0                 # se cuenta hasta el cierre (21:00); el reglamento pide vitrina llena hasta las 20:30, el dueño pidió medir hasta las 21:00
NOCHE = (19.0, 21.0)            # ventana del indicador de la noche


# ------------------------------------------------------------------------------------------------ lectura de la cámara

def _pedir(url: str, timeout: float = 20.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:        # noqa: S310 -- URL propia (red privada del dueño), no viene de un usuario
        return json.loads(r.read().decode("utf-8"))


def tramos(puntos: list, tam: int = TRAMO) -> list:
    """De los puntos por minuto del programa a tramos de `tam` minutos: [{'hora': 'HH:MM', 'nivel': promedio, 'minimo': mínimo, 'n': puntos}] solo con
    puntos medidos (estado 'ok' y nivel presente)."""
    acum: dict = {}
    for p in puntos:
        if p.get("e") != "ok" or p.get("n") is None:
            continue
        h, m = p["m"].split(":")
        inicio = int(h) * 60 + (int(m) // tam) * tam
        a = acum.setdefault(inicio, [0.0, 0, 100.0])
        a[0] += float(p["n"])
        a[1] += 1
        a[2] = min(a[2], float(p["n"]))
    return [{"hora": f"{i // 60:02d}:{i % 60:02d}", "nivel": round(s / n, 1), "minimo": round(mn, 1), "n": n} for i, (s, n, mn) in sorted(acum.items())]


def traer_dia(url: str, fecha: dt.date) -> list:
    datos = _pedir(f"{url.rstrip('/')}/api/dia?fecha={fecha.isoformat()}")
    return tramos(datos.get("puntos", []))


def traer_fechas(url: str) -> list:
    return [dt.date.fromisoformat(x) for x in _pedir(f"{url.rstrip('/')}/api/dias")]


# ------------------------------------------------------------------------------------------------ base de datos

def _asegurar_tabla(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE IF NOT EXISTS {TABLA} (sucursal VARCHAR NOT NULL, fecha VARCHAR NOT NULL, hora VARCHAR NOT NULL, '
                          'nivel REAL NOT NULL, minimo REAL NOT NULL, puntos INTEGER NOT NULL, PRIMARY KEY (sucursal, fecha, hora))'))
    if engine.dialect.name == "postgresql":
        try:                                           # Supabase publica las tablas por su API: sin políticas, RLS la cierra
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{TABLA}" ENABLE ROW LEVEL SECURITY'))
        except Exception:  # noqa: BLE001 -- sin permiso o ya hecho: no debe impedir guardar
            pass


def guardar_dia(engine, sucursal: str, fecha: dt.date, trs: list) -> int:
    """Reemplaza los tramos de ese día. Devuelve cuántos quedaron."""
    _asegurar_tabla(engine)
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {TABLA} WHERE sucursal = :s AND fecha = :f"), {"s": sucursal, "f": fecha.isoformat()})
        if trs:
            conn.execute(text(f"INSERT INTO {TABLA} (sucursal, fecha, hora, nivel, minimo, puntos) VALUES (:s, :f, :h, :n, :m, :p)"),
                         [{"s": sucursal, "f": fecha.isoformat(), "h": t["hora"], "n": t["nivel"], "m": t["minimo"], "p": t["n"]} for t in trs])
    return len(trs)


def fechas_guardadas(engine, sucursal: str) -> set:
    try:
        with engine.connect() as conn:
            return {dt.date.fromisoformat(r[0]) for r in conn.execute(text(f"SELECT DISTINCT fecha FROM {TABLA} WHERE sucursal = :s"), {"s": sucursal})}
    except Exception:  # noqa: BLE001 -- la tabla aún no existe
        return set()


def leer(engine, sucursal: str, desde: dt.date, hasta: dt.date) -> dict:
    """{fecha: [tramos]} entre `desde` y `hasta` (incluidos)."""
    try:
        with engine.connect() as conn:
            filas = conn.execute(text(f"SELECT fecha, hora, nivel, minimo, puntos FROM {TABLA} WHERE sucursal = :s AND fecha >= :d AND fecha <= :h "
                                      "ORDER BY fecha, hora"), {"s": sucursal, "d": desde.isoformat(), "h": hasta.isoformat()}).all()
    except Exception:  # noqa: BLE001 -- la tabla aún no existe
        return {}
    salida: dict = {}
    for f, h, n, m, p in filas:
        salida.setdefault(dt.date.fromisoformat(f), []).append({"hora": h, "nivel": float(n), "minimo": float(m), "n": int(p)})
    return salida


def sincronizar(engine, sucursal: str, url: str, hoy: dt.date, dias_atras: int = 21) -> int:
    """Trae de la cámara los días que faltan en la base (y siempre hoy y ayer, que siguen cambiando). Devuelve cuántos días escribió."""
    disponibles = [d for d in traer_fechas(url) if (hoy - d).days <= dias_atras]
    ya = fechas_guardadas(engine, sucursal)
    escritos = 0
    for d in sorted(disponibles):
        if d in ya and (hoy - d).days > 1:
            continue
        guardar_dia(engine, sucursal, d, traer_dia(url, d))
        escritos += 1
    return escritos


# ------------------------------------------------------------------------------------------------ análisis (puro)

def _minutos(hora: str) -> float:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def resumen_dia(trs: list, umbral: float = UMBRAL_BAJO) -> dict | None:
    """Resumen de un día a partir de sus tramos. None si no hay tramos."""
    if not trs:
        return None
    llena_en = next((t["hora"] for t in trs if t["nivel"] >= LLENA), None)
    surtidos = [t for t in trs if llena_en and t["hora"] >= llena_en and _minutos(t["hora"]) < HORA_FIN * 60]
    bajos = [t for t in surtidos if t["nivel"] < umbral]
    noche = [t for t in trs if NOCHE[0] * 60 <= _minutos(t["hora"]) < NOCHE[1] * 60]
    return {
        "llena_en": llena_en,
        "promedio": sum(t["nivel"] for t in surtidos) / len(surtidos) if surtidos else None,       # ya surtida y hasta las 21:00
        "minimo": min((t["nivel"] for t in surtidos), default=None),
        "minutos_bajo": len(bajos) * TRAMO,
        "noche_promedio": sum(t["nivel"] for t in noche) / len(noche) if noche else None,
        "noche_llena_pct": sum(t["nivel"] >= LLENA for t in noche) / len(noche) if noche else None,
        "cierre": trs[-1]["nivel"], "cierre_hora": trs[-1]["hora"],
        "primera": trs[0]["hora"],
    }


def por_hora(dias: dict) -> dict:
    """{hora entera: nivel promedio} de todos los días dados (solo tramos ya surtidos de cada día)."""
    suma: dict = {}
    for trs in dias.values():
        llena_en = next((t["hora"] for t in trs if t["nivel"] >= LLENA), None)
        for t in trs:
            if llena_en and t["hora"] >= llena_en:
                h = int(t["hora"][:2])
                a = suma.setdefault(h, [0.0, 0])
                a[0] += t["nivel"]
                a[1] += 1
    return {h: s / n for h, (s, n) in sorted(suma.items())}


def mapa_calor(dias: dict) -> dict:
    """{fecha: {hora entera: nivel promedio}} para dibujar el mapa día x hora."""
    salida = {}
    for d, trs in dias.items():
        horas: dict = {}
        for t in trs:
            a = horas.setdefault(int(t["hora"][:2]), [0.0, 0])
            a[0] += t["nivel"]
            a[1] += 1
        salida[d] = {h: s / n for h, (s, n) in horas.items()}
    return salida


def frases_del_periodo(resumenes: dict, umbral: float = UMBRAL_BAJO) -> list:
    """Lectura en palabras (en ruso, como el dashboard) de varios días ({fecha: resumen_dia}): qué tan llena estuvo la vitrina de noche y cuándo bajó."""
    validos = {d: r for d, r in resumenes.items() if r}
    noches = {d: r["noche_promedio"] for d, r in validos.items() if r["noche_promedio"] is not None}
    frases = []
    if noches:
        prom = sum(noches.values()) / len(noches)
        malos = sorted(d for d, v in noches.items() if v < umbral + 10)
        frases.append(f"С 19:00 до 21:00 витрина в среднем заполнена на {prom:.0f}% (дней: {len(noches)}). Цель регламента -- полная (≥{LLENA:.0f}%) до закрытия.")
        if malos:
            frases.append(f"Вечера с почти пустой витриной (в среднем меньше {umbral + 10:.0f}%): " + ", ".join(d.strftime("%d.%m") for d in malos) + ".")
    conbajo = {d: r["minutos_bajo"] for d, r in validos.items() if r["minutos_bajo"]}
    if conbajo:
        frases.append(f"Ниже {umbral:.0f}% после выкладки: " + ", ".join(f"{d:%d.%m} -- {m} мин" for d, m in sorted(conbajo.items())) + ".")
    return frases


# ------------------------------------------------------------------------------------------------ pérdida por vitrina vacía

SENSIBILIDAD = 1.0              # 1.0 = si la vitrina está al 35 % se pierde la mitad de lo que se vendería con ella llena (lineal hasta el 70 %)


def base_de_ingresos(ingresos: dict, hoy: dt.date, semanas: int = 8) -> dict:
    """{tipo de día: {hora entera: ingreso medio en esa hora}} con los días COMPLETOS de las últimas `semanas` semanas. `ingresos` = {fecha: {hora: $}}.
    Es lo que se vende «normalmente» (casi siempre con la vitrina llena) y sirve de referencia de lo que se habría vendido."""
    import regla_vitrina as rv

    suma: dict = {}
    dias: dict = {}
    for d, horas in ingresos.items():
        if d >= hoy or (hoy - d).days > semanas * 7:
            continue
        tipo = rv.tipo_de_dia(d)
        dias[tipo] = dias.get(tipo, 0) + 1
        for h, v in horas.items():
            suma.setdefault(tipo, {})[h] = suma.setdefault(tipo, {}).get(h, 0.0) + v
    return {tipo: {h: v / dias[tipo] for h, v in horas.items()} for tipo, horas in suma.items()}


def captura(nivel: float, sensibilidad: float = SENSIBILIDAD) -> float:
    """Qué parte de la venta normal se logra con la vitrina a ese nivel: 1 con 70 % o más; por debajo baja en línea recta (a 0 % no se vende nada
    si sensibilidad = 1)."""
    return max(0.0, min(1.0, 1.0 - sensibilidad * max(0.0, 1.0 - nivel / LLENA)))


def perdida_dia(fecha: dt.date, trs: list, base: dict, sensibilidad: float = SENSIBILIDAD) -> dict:
    """{'perdida': $ no vendidos por vitrina baja, 'minutos_bajo': minutos con menos de 70 %, más lo mismo separado en 'antes' (hasta las 20:30) y
    'cierre' (20:30-21:00)}: solo después de surtir y antes de las 21:00."""
    import regla_vitrina as rv

    horas = base.get(rv.tipo_de_dia(fecha), {})
    llena_en = next((t["hora"] for t in trs if t["nivel"] >= LLENA), None)
    parte = {"antes": [0.0, 0], "cierre": [0.0, 0]}
    for t in trs:
        if not llena_en or t["hora"] < llena_en or _minutos(t["hora"]) >= HORA_FIN * 60 or t["nivel"] >= LLENA:
            continue
        p = parte["antes"] if _minutos(t["hora"]) < HORA_REGLAMENTO * 60 else parte["cierre"]
        p[0] += horas.get(int(t["hora"][:2]), 0.0) * TRAMO / 60.0 * (1.0 - captura(t["nivel"], sensibilidad))
        p[1] += TRAMO
    return {"perdida": parte["antes"][0] + parte["cierre"][0], "minutos_bajo": parte["antes"][1] + parte["cierre"][1],
            "perdida_antes": parte["antes"][0], "minutos_antes": parte["antes"][1],
            "perdida_cierre": parte["cierre"][0], "minutos_cierre": parte["cierre"][1]}


def resumen_semana(dias: dict, ingresos: dict, base: dict, sensibilidad: float = SENSIBILIDAD) -> dict | None:
    """Resumen de varios días ({fecha: tramos}) con sus ingresos reales ({fecha: {hora: $}}): llenado medio, venta no lograda en $ y en %
    (la parte de la venta posible que no se vendió por vitrina baja)."""
    usados = {d: t for d, t in dias.items() if t and d in ingresos}
    if not usados:
        return None
    suma_nivel = n_surtido = n_llena = n_noche = 0.0
    noche_suma = 0.0
    perdida = real = 0.0
    bajos = 0
    nivel_ventana = {"antes": [0.0, 0], "cierre": [0.0, 0]}
    tot = {"perdida_antes": 0.0, "perdida_cierre": 0.0, "minutos_antes": 0, "minutos_cierre": 0}
    detalle = {}
    for d, trs in usados.items():
        llena_en = next((t["hora"] for t in trs if t["nivel"] >= LLENA), None)
        for t in trs:
            if llena_en and t["hora"] >= llena_en and _minutos(t["hora"]) < HORA_FIN * 60:
                suma_nivel += t["nivel"]
                n_surtido += 1
                n_llena += t["nivel"] >= LLENA
                v = nivel_ventana["antes"] if _minutos(t["hora"]) < HORA_REGLAMENTO * 60 else nivel_ventana["cierre"]
                v[0] += t["nivel"]
                v[1] += 1
            if NOCHE[0] * 60 <= _minutos(t["hora"]) < NOCHE[1] * 60:
                noche_suma += t["nivel"]
                n_noche += 1
        p = perdida_dia(d, trs, base, sensibilidad)
        ingreso = sum(ingresos[d].values())
        detalle[d] = {"perdida": p["perdida"], "ingreso": ingreso, "minutos_bajo": p["minutos_bajo"], "perdida_antes": p["perdida_antes"],
                      "perdida_cierre": p["perdida_cierre"]}
        for k in tot:
            tot[k] += p[k]
        perdida += p["perdida"]
        real += ingreso
        bajos += p["minutos_bajo"]
    posible = real + perdida
    return {
        "dias": len(usados), "llenado": suma_nivel / n_surtido if n_surtido else None, "tiempo_lleno": n_llena / n_surtido if n_surtido else None,
        "noche": noche_suma / n_noche if n_noche else None, "minutos_bajo": bajos,
        "ingreso": real, "perdida": perdida, "perdida_pct": perdida / posible if posible else 0.0,
        "detalle": detalle,
        "antes": {"llenado": nivel_ventana["antes"][0] / nivel_ventana["antes"][1] if nivel_ventana["antes"][1] else None,
                  "perdida": tot["perdida_antes"], "pct": tot["perdida_antes"] / posible if posible else 0.0, "minutos_bajo": tot["minutos_antes"]},
        "cierre": {"llenado": nivel_ventana["cierre"][0] / nivel_ventana["cierre"][1] if nivel_ventana["cierre"][1] else None,
                   "perdida": tot["perdida_cierre"], "pct": tot["perdida_cierre"] / posible if posible else 0.0, "minutos_bajo": tot["minutos_cierre"]},
    }
