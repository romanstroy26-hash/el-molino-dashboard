"""Plan del día en el MISMO formato que la hoja de Google Sheets de producción ("<DÍA> d/m/aaaa - HIMALAYA - PLAN DEL DIA"):
una fila por producto, columnas de horneado 7..17, TOTAL 5PM, tandas de la tarde 1/2/3 y RESERVA (refri); PDF horizontal + .xlsx.

QUÉ SE USA HOY DE ESTE ARCHIVO: el formato de la hoja (Fila/Plan, PDF y .xlsx), la lectura de los planes de papel como CATÁLOGO
(productos, orden, charola) y la clave para reconocer un producto con nombres distintos. Los números del plan los calcula
plan_propio.py solo con ventas. Lo que sigue (generar el plan a partir de un plan de papel y del plan semanal) es el modo anterior,
que ya no usa el dashboard por decisión del dueño (los planes reales no deben entrar en el cálculo); se conserva probado por si se
quisiera volver a él.

De dónde salían los números en ese modo anterior, en orden de preferencia:
  A. PLAN SEMANAL "BASES" (PDF "Plan_Panaderia_Semana_<lunes>.pdf" en data/planes_produccion/<punto>): por familia de
     producto y por día, Mañana (7am a 12pm) y Tarde (1pm a 5pm), más las OPCIONES de las 2pm (tandas 1/2/3: se hacen
     según la venta total de Wansoft a las 2pm, en miles de pesos: 32 / 40 / 45). Si la semana de la fecha existe, el
     plan del día respeta esos totales por familia; cómo se reparten entre los productos de la familia y entre las horas
     sale del último plan diario del mismo día de la semana (productos, horas, reserva).
  B. Si no hay plan semanal para esa fecha: el último plan diario del mismo día de la semana, ajustado al pronóstico:
     factor = pronóstico(fecha) x k / total de la base, k = mediana de (plan real / pronóstico) en los últimos planes.
     Con prueba histórica (24 planes) esto se desvía 7 % del total que Roman planeó; copiar la semana pasada, 12 %.
En ambos casos cada celda se redondea a la charola de su producto (máximo común divisor de sus cantidades: 12, 6, 4...).

Puro (sin base de datos): los pronósticos llegan ya calculados, como diccionario.
"""

from __future__ import annotations

import datetime as dt
import difflib
import io
import json
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from functools import reduce
from pathlib import Path

HORAS = (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17)
DIAS = ("LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO")
DESVIO_MIN = 0.03          # factor a menos de 3 % de 1: el plan base no se toca
FACTOR_MIN, FACTOR_MAX = 0.75, 1.35
PLANES_CALIBRACION = 24    # cuántos planes recientes se usan para calcular k


@dataclass
class Fila:
    codigo: str
    producto: str
    horas: dict            # {7: 24, 9: 12, ...} solo las celdas con cantidad
    total: int             # TOTAL 5PM (a veces escrito a mano sin desglose por hora)
    tandas: tuple          # (t1, t2, t3), None = celda vacía
    reserva: int | None


@dataclass
class Plan:
    fecha: dt.date
    punto: str                         # "HIMALAYA" en la hoja
    etiquetas_tandas: tuple            # ("1\n32", "2\n40", "3\n45") -- subtítulos tal como vienen en la hoja
    filas: list = field(default_factory=list)
    fuente: str = ""                   # nombre del archivo base, si viene de un PDF


def titulo(plan: Plan) -> str:
    d = plan.fecha
    return f"{DIAS[d.weekday()]} {d.day}/{d.month}/{d.year} - {plan.punto} - PLAN DEL DIA"


def nombre_archivo(plan: Plan, extension: str) -> str:
    return f"Plan_{DIAS[plan.fecha.weekday()].capitalize()}_{plan.fecha.isoformat()}.{extension}"


def totales(plan: Plan) -> dict:
    """Fila TOTAL de abajo: suma de cada columna."""
    return {
        "horas": {h: sum(f.horas.get(h, 0) for f in plan.filas) for h in HORAS},
        "total": sum(f.total for f in plan.filas),
        "tandas": tuple(sum((f.tandas[i] or 0) for f in plan.filas) for i in range(3)),
        "reserva": sum((f.reserva or 0) for f in plan.filas),
    }


# --------------------------------------------------------------------------------------------- lectura de los PDF

def _numero(texto) -> int | None:
    t = (texto or "").strip().replace(",", "")
    if not t:
        return None
    try:
        return int(round(float(t)))
    except ValueError:
        return None


def leer_plan_pdf(path: Path) -> Plan | None:
    """Lee el PDF de la hoja (pdfplumber). None si no tiene el formato esperado (por ejemplo, una prueba rota)."""
    import pdfplumber

    path = Path(path)
    fecha = None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", path.name)
    if m:
        fecha = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    punto, etiquetas, filas = "HIMALAYA", ("1", "2", "3"), []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for tabla in page.extract_tables():
                for r in tabla:
                    c = [(x or "").strip() for x in r]
                    if not any(c):
                        continue
                    union = " ".join(c).upper()
                    if "PLAN DEL DIA" in union:
                        mt = re.search(r"-\s*(.+?)\s*-\s*PLAN DEL DIA", union)
                        if mt:
                            punto = mt.group(1).strip()
                    elif len(c) > 1 and c[1].upper() == "PRODUCTO" and len(c) >= 17:
                        etiquetas = tuple(c[14:17])
                    elif len(c) > 1 and c[1].upper() == "TOTAL":
                        continue
                    elif len(c) >= 15 and c[1]:
                        horas = {h: _numero(c[2 + i]) for i, h in enumerate(HORAS)}
                        c = c + [""] * (18 - len(c))
                        filas.append(Fila(
                            codigo=c[0], producto=c[1], horas={h: v for h, v in horas.items() if v},
                            total=_numero(c[13]) or 0, tandas=tuple(_numero(c[14 + i]) for i in range(3)),
                            reserva=_numero(c[17])))
    if fecha is None or not filas:
        return None
    return Plan(fecha=fecha, punto=punto, etiquetas_tandas=etiquetas, filas=filas, fuente=path.name)


ARCHIVO_CACHE_PLANES = ".cache_planes.json"


def _plan_a_dict(plan: Plan | None) -> dict | None:
    if plan is None:
        return None
    return {"fecha": plan.fecha.isoformat(), "punto": plan.punto, "etiquetas": list(plan.etiquetas_tandas), "fuente": plan.fuente,
            "filas": [{"codigo": f.codigo, "producto": f.producto, "horas": {str(h): v for h, v in f.horas.items()}, "total": f.total,
                       "tandas": list(f.tandas), "reserva": f.reserva} for f in plan.filas]}


def _plan_de_dict(d: dict | None) -> Plan | None:
    if d is None:
        return None
    filas = [Fila(f["codigo"], f["producto"], {int(h): v for h, v in f["horas"].items()}, f["total"], tuple(f["tandas"]), f["reserva"])
             for f in d["filas"]]
    return Plan(fecha=dt.date.fromisoformat(d["fecha"]), punto=d["punto"], etiquetas_tandas=tuple(d["etiquetas"]), filas=filas, fuente=d["fuente"])


def planes_en_carpeta(carpeta: Path, _cache: dict = {}) -> dict:
    """{fecha: Plan} con el archivo MÁS NUEVO de cada fecha (las descargas "(1)" suelen ser la versión corregida).
    Ignora las PRUEBA. Lee cada PDF una sola vez mientras no cambie: en memoria, y en un archivo de la propia carpeta
    (leer ~65 PDF con pdfplumber tarda ~100 s, y sin el archivo se repetiría en cada reinicio del dashboard)."""
    carpeta = Path(carpeta)
    resultado: dict = {}
    if not carpeta.exists():
        return resultado
    ruta_cache = carpeta / ARCHIVO_CACHE_PLANES
    try:
        en_disco = json.loads(ruta_cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        en_disco = {}
    cambio = False
    for p in sorted(carpeta.glob("Plan_*.pdf"), key=lambda x: x.stat().st_mtime):
        if "PRUEBA" in p.name.upper() or "SEMANA" in p.name.upper():       # las pruebas y el plan SEMANAL no son un plan diario
            continue
        st = p.stat()
        clave = (str(p), st.st_mtime)
        if clave not in _cache:
            guardado = en_disco.get(p.name)
            if guardado and guardado.get("mtime") == st.st_mtime and guardado.get("size") == st.st_size:
                _cache[clave] = _plan_de_dict(guardado["plan"])
            else:
                try:
                    _cache[clave] = leer_plan_pdf(p)
                except Exception:  # noqa: BLE001 -- un PDF dañado no debe tumbar la página
                    _cache[clave] = None
                en_disco[p.name] = {"mtime": st.st_mtime, "size": st.st_size, "plan": _plan_a_dict(_cache[clave])}
                cambio = True
        plan = _cache[clave]
        if plan is not None:
            resultado[plan.fecha] = plan          # el más nuevo gana (orden por fecha de modificación)
    if cambio:
        try:
            ruta_cache.write_text(json.dumps(en_disco, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass                                  # carpeta de solo lectura: solo se pierde la velocidad del próximo arranque
    return resultado


# --------------------------------------------------------------------------------------------- ajuste al pronóstico

def _mcd(valores) -> int:
    return reduce(math.gcd, [abs(int(v)) for v in valores if v]) if any(valores) else 1


def _repartir(destino_unidades: int, pesos: list) -> list:
    """Reparte `destino_unidades` unidades enteras en proporción a `pesos` (mayor resto): la suma es exacta."""
    suma = sum(pesos)
    if destino_unidades <= 0 or suma <= 0:
        return [0] * len(pesos)
    ideal = [p / suma * destino_unidades for p in pesos]
    base = [int(x) for x in ideal]
    for i in sorted(range(len(pesos)), key=lambda i: (ideal[i] - base[i], pesos[i]), reverse=True)[: destino_unidades - sum(base)]:
        base[i] += 1
    return base


def _escalar_fila(fila: Fila, factor: float) -> Fila:
    if fila.total <= 0 and not fila.horas:
        return fila
    if fila.horas:
        unidad = _mcd(list(fila.horas.values()))
        objetivo = max(1, round(fila.total * factor / unidad))               # en charolas, mínimo una si había producción
        horas = sorted(fila.horas)
        reparto = _repartir(objetivo, [fila.horas[h] for h in horas])
        nuevas = {h: n * unidad for h, n in zip(horas, reparto) if n}
        total = sum(nuevas.values()) if fila.total == sum(fila.horas.values()) else round(fila.total * factor / unidad) * unidad
    else:                                                                    # total escrito a mano, sin horas
        unidad = 5 if fila.total >= 10 and fila.total % 5 == 0 else 1
        total = max(unidad, round(fila.total * factor / unidad) * unidad)
        nuevas = {}
    return Fila(fila.codigo, fila.producto, nuevas, total, fila.tandas, fila.reserva)


_RUIDO_EN_NOMBRES = {"iva", "ind"}      # "CON IVA" (otra línea de caja) e "IND" (individual) no cambian de qué producto se habla
_SINONIMOS = {"ponchik": "berlina", "choco": "chocolate"}      # la caja las llama "PONCHIK" (berlinas) y "CHOCO" (chocolate)


def clave_producto(nombre: str) -> str:
    """Clave para reconocer el MISMO producto con nombres distintos (plan en papel vs Wansoft): sin acentos, sin "CON IVA",
    sin "IND", sin importar el orden de las palabras ("Croissant Mini Natural" = "Mini Croissant Natural")."""
    palabras = (_SINONIMOS.get(w, w) for w in _norm(nombre).split() if w not in _RUIDO_EN_NOMBRES)
    return " ".join(sorted(palabras))


def escalar_plan(base: Plan, factor: float, fecha: dt.date, por_producto: dict | None = None) -> Plan:
    """Mismo plan con el TOTAL 5PM multiplicado por `factor` (tandas 1/2/3 y reserva intactas).

    `por_producto` = {clave_producto: multiplicador} (lo aprendido de plan vs venta, ver aprendizaje_plan.py): mueve unidades
    de unos productos a otros SIN cambiar el total del día -- los multiplicadores se normalizan con el peso de cada producto en
    la base, así que el nivel del día lo decide solo `factor`."""
    mult = {}
    if por_producto:
        crudos = {id(f): por_producto.get(clave_producto(f.producto), 1.0) for f in base.filas}
        suma = sum(f.total for f in base.filas)
        ponderado = sum(f.total * crudos[id(f)] for f in base.filas)
        norma = suma / ponderado if ponderado else 1.0
        mult = {k: v * norma for k, v in crudos.items()}
    filas = []
    for f in base.filas:
        g = factor * mult.get(id(f), 1.0)
        filas.append(Fila(f.codigo, f.producto, dict(f.horas), f.total, f.tandas, f.reserva) if abs(g - 1) < DESVIO_MIN else _escalar_fila(f, g))
    return Plan(fecha=fecha, punto=base.punto, etiquetas_tandas=base.etiquetas_tandas, filas=filas, fuente=base.fuente)


def calcular_k(planes: dict, pronosticos: dict, antes_de: dt.date, n: int = PLANES_CALIBRACION) -> float:
    """Mediana de (total del plan real / pronóstico de ese día) en los últimos `n` planes anteriores a `antes_de`."""
    razones = []
    for fecha in sorted(d for d in planes if d < antes_de)[-n:]:
        pron = pronosticos.get(fecha)
        total = sum(f.total for f in planes[fecha].filas)
        if pron and total:
            razones.append(total / pron)
    return statistics.median(razones) if razones else 1.0


def elegir_base(planes: dict, fecha: dt.date) -> Plan | None:
    """Último plan anterior a `fecha` del mismo día de la semana; si no hay, el último plan cualquiera."""
    previos = [d for d in planes if d < fecha]
    mismos = [d for d in previos if d.weekday() == fecha.weekday()]
    elegido = max(mismos) if mismos else (max(previos) if previos else None)
    return planes[elegido] if elegido else None


@dataclass
class Propuesta:
    plan: Plan
    base: Plan
    pronostico: float | None
    k: float
    factor: float
    total_base: int
    nivel: float = 1.0          # corrección por lo que pasó en los últimos días (aprendizaje_plan.nivel_reciente)


def proponer_plan(planes: dict, fecha: dt.date, pronosticos: dict, por_producto: dict | None = None, nivel: float = 1.0) -> Propuesta | None:
    """Arma el plan de `fecha`. `pronosticos` = {fecha: unidades pronosticadas} (incluye `fecha` y los días de los planes recientes).
    `nivel` multiplica el pronóstico (si los últimos días se vendió más/menos de lo previsto); `por_producto` mueve unidades entre productos."""
    base = elegir_base(planes, fecha)
    if base is None:
        return None
    total_base = sum(f.total for f in base.filas)
    pron = pronosticos.get(fecha)
    k = calcular_k(planes, pronosticos, fecha)
    factor = 1.0
    if pron and total_base:
        factor = min(FACTOR_MAX, max(FACTOR_MIN, pron * k * nivel / total_base))
    return Propuesta(plan=escalar_plan(base, factor, fecha, por_producto), base=base, pronostico=pron, k=k, factor=factor,
                     total_base=total_base, nivel=nivel)


# --------------------------------------------------------------------------------------------- plan semanal (BASES)

_PALABRAS_VACIAS = {"de", "del", "la", "el", "con", "y"}


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return " ".join(w for w in re.sub(r"[^a-z0-9 ]+", " ", t).split() if w not in _PALABRAS_VACIAS)


@dataclass
class Semana:
    lunes: dt.date
    familias: dict          # {clave_normalizada: {"nombre": str, "manana": [7 ints], "tarde": [7 ints], "opciones": (o1, o2, o3)}}
    etiquetas: tuple        # ("1\n32", "2\n40", "3\n45")
    fuente: str = ""


def leer_semana_pdf(path: Path) -> Semana | None:
    """Lee "PLAN SEMANAL PANADERÍA — BASES" (Google Sheets -> PDF). None si no tiene ese formato."""
    import pdfplumber

    path = Path(path)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", path.name)
    if not m:
        return None
    lunes = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    familias, etiquetas = {}, ("1", "2", "3")
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for tabla in page.extract_tables():
                for r in tabla:
                    c = [(x or "").strip() for x in r]
                    if len(c) < 18:
                        continue
                    if c[1] == "Mañana" and c[15]:
                        etiquetas = tuple(c[15:18])
                        continue
                    if not c[0]:
                        continue
                    nombre = c[0].replace("\n", " ")
                    if nombre.upper() in ("BASE", "TOTAL") or nombre.upper().startswith("PLAN SEMANAL") or nombre.startswith("Mañana ="):
                        continue
                    valores = [_numero(x) or 0 for x in c[1:15]]
                    familias[_norm(re.sub(r"\(.*?\)", "", nombre))] = {"nombre": nombre, "manana": valores[0::2], "tarde": valores[1::2],
                                               "opciones": tuple(_numero(x) or 0 for x in c[15:18])}
    return Semana(lunes=lunes, familias=familias, etiquetas=etiquetas, fuente=path.name) if familias else None


def semanas_en_carpeta(carpeta: Path, _cache: dict = {}) -> dict:
    """{lunes: Semana} con el archivo más nuevo de cada semana (Plan_Panaderia_Semana_<lunes>*.pdf)."""
    carpeta, resultado = Path(carpeta), {}
    if not carpeta.exists():
        return resultado
    for p in sorted(carpeta.glob("Plan_Panaderia_Semana_*.pdf"), key=lambda x: x.stat().st_mtime):
        clave = (str(p), p.stat().st_mtime)
        if clave not in _cache:
            try:
                _cache[clave] = leer_semana_pdf(p)
            except Exception:  # noqa: BLE001
                _cache[clave] = None
        if _cache[clave] is not None:
            resultado[_cache[clave].lunes] = _cache[clave]
    return resultado


def semana_de(semanas: dict, fecha: dt.date) -> Semana | None:
    return semanas.get(fecha - dt.timedelta(days=fecha.weekday()))


def _familia_de(producto: str, claves: list) -> str | None:
    """Familia del plan semanal a la que pertenece un producto del plan diario (la coincidencia más larga; si no, la más parecida)."""
    p = _norm(producto)
    candidatas = [k for k in claves if p == k or p.startswith(k + " ") or (k.startswith(p) and len(p) >= 6)]
    if candidatas:
        return max(candidatas, key=len)
    cerca = difflib.get_close_matches(p, claves, n=1, cutoff=0.8)
    return cerca[0] if cerca else None


def _asignar(ideales: dict, unidades: dict, objetivo: int) -> dict:
    """Redondea cada cantidad ideal a la charola de su fila y reparte lo que falte por mayor resto, sin pasarse de media
    charola del objetivo. Si el objetivo es positivo y todo quedó en cero, la mayor celda recibe una charola."""
    base = {k: int(v // unidades[k]) * unidades[k] for k, v in ideales.items()}
    restante = objetivo - sum(base.values())
    for k in sorted(ideales, key=lambda k: (ideales[k] - base[k]) / unidades[k], reverse=True):
        if restante >= unidades[k] / 2 and ideales[k] - base[k] > 0:
            base[k] += unidades[k]
            restante -= unidades[k]
    if objetivo > 0 and ideales and not any(base.values()):
        k = max(ideales, key=lambda k: ideales[k])
        base[k] = unidades[k]
    return base


def _asignar_con_multiplicadores(celdas: dict, gf: dict, objetivo: int, g: int) -> dict:
    """Reparte `objetivo` (múltiplo de la charola `g`) entre los productos de la familia según su base x su multiplicador
    aprendido, y luego cada producto reparte lo suyo entre SUS horas como las tenía la base. Primero producto y después hora:
    repartir celda por celda con multiplicadores de 0.6 a 1.6 se perdería en el redondeo a charolas.
    Un producto que la base hacía y se quedaría sin ninguna charola recibe una (la quita el que más recibió): se recorta, no desaparece."""
    base_p: dict = {}
    for (fid, _), v in celdas.items():
        base_p[fid] = base_p.get(fid, 0) + v
    pesos = {fid: v * gf[fid] for fid, v in base_p.items()}
    suma = sum(pesos.values())
    ideales = {fid: w * objetivo / suma for fid, w in pesos.items()}
    por_producto = _asignar(ideales, {fid: g for fid in ideales}, objetivo)
    for fid in sorted(por_producto):
        if por_producto[fid] > 0:
            continue
        donante = max(por_producto, key=por_producto.get)
        if por_producto[donante] >= 2 * g:
            por_producto[donante] -= g
            por_producto[fid] += g
    resultado: dict = {}
    for fid, total in por_producto.items():
        propias = {c: v for c, v in celdas.items() if c[0] == fid}
        resultado.update(_asignar({c: v * total / base_p[fid] for c, v in propias.items()}, {c: g for c in propias}, total))
    return resultado


def _unidad(valores, por_defecto: int = 1) -> int:
    valores = [v for v in valores if v]
    return _mcd(valores) if valores else por_defecto


@dataclass
class DesdeSemana:
    plan: Plan
    semana: Semana
    base: Plan
    sin_familia: list           # productos de la base que el plan semanal no cubre (quedan como en la base)
    desvios: list               # [(familia, momento, objetivo, logrado)] donde la charola no permite cuadrar exacto


def plan_desde_semana(semana: Semana, base: Plan, fecha: dt.date, respaldo: Plan | None = None,
                      por_producto: dict | None = None) -> DesdeSemana:
    """Plan diario de `fecha` con los totales por familia del plan semanal; estructura (productos, horas, reserva) de `base`.

    `respaldo` = el plan diario más reciente de cualquier día: define la LISTA y el orden de los productos (así entran los
    productos nuevos, p. ej. Pan de Muerto o Ciabatta, que el plan del mismo día de la semana pasada aún no tenía); de cada
    producto se usa la fila de `base` si existe y, si no, la de `respaldo`.

    `por_producto` = {clave_producto: multiplicador} (lo aprendido de plan vs venta): cambia cómo se reparte el total de la familia
    ENTRE sus productos (más a los que se agotan, menos a los que sobran). El total de la familia sigue siendo el del plan semanal:
    esa decisión es de quien arma las BASES."""
    dia = fecha.weekday()
    pp = por_producto or {}
    dia = fecha.weekday()
    claves = list(semana.familias)
    por_familia: dict = {}
    sin_familia = []
    if respaldo is not None:
        en_base = {_norm(f.producto): f for f in base.filas}
        estructura = [en_base.get(_norm(r.producto), r) for r in respaldo.filas]
    else:
        estructura = list(base.filas)
    for f in estructura:
        k = _familia_de(f.producto, claves)
        if k is None:
            sin_familia.append(f.producto)
        por_familia.setdefault(k, []).append(f)

    nuevas: dict = {}
    desvios = []
    for k, filas in por_familia.items():
        if k is None:
            for f in filas:
                nuevas[id(f)] = Fila(f.codigo, f.producto, dict(f.horas), f.total, f.tandas, f.reserva)
            continue
        fam = semana.familias[k]
        gf = {id(f): pp.get(clave_producto(f.producto), 1.0) for f in filas}      # multiplicador aprendido de cada producto
        objetivos = {"manana": fam["manana"][dia], "tarde": fam["tarde"][dia]}
        resultado = {id(f): {"horas": {}, "tandas": [None if t is None else 0 for t in f.tandas]} for f in filas}

        if any(f.horas for f in filas):
            for momento, rango in (("manana", range(7, 13)), ("tarde", range(13, 18))):
                celdas = {(id(f), h): f.horas[h] for f in filas for h in rango if f.horas.get(h)}
                objetivo = objetivos[momento]
                if objetivo and not celdas:        # la base no tenía nada en ese momento: según el total de cada producto, a la primera hora
                    hora0 = 7 if momento == "manana" else 13
                    celdas = {(id(f), hora0): max(f.total, 1) for f in filas if f.total}
                if not celdas:
                    continue
                suma_base = sum(celdas.values())
                g = _unidad(list(celdas.values()) + [objetivo], 1)      # charola de la familia en ese momento: el objetivo es múltiplo de ella
                if any(abs(gf[c[0]] - 1) > 1e-9 for c in celdas):
                    asignado = _asignar_con_multiplicadores(celdas, gf, objetivo, g)
                else:
                    ideales = {c: v * objetivo / suma_base for c, v in celdas.items()}
                    asignado = _asignar(ideales, {c: g for c in celdas}, objetivo)
                for (fid, h), v in asignado.items():
                    if v:
                        resultado[fid]["horas"][h] = v
                if sum(asignado.values()) != objetivo:
                    desvios.append((fam["nombre"], momento, objetivo, sum(asignado.values())))
        else:                                      # familia con total escrito a mano (berlinas, panqués...)
            objetivo = objetivos["manana"] + objetivos["tarde"]
            unidad = _unidad([f.total for f in filas] + [objetivo], 1)
            pesos_fila = {id(f): f.total * gf[id(f)] for f in filas}
            base_total = max(sum(pesos_fila.values()), 1)
            ideales = {fid: w * objetivo / base_total for fid, w in pesos_fila.items()}
            asignado = _asignar(ideales, {id(f): unidad for f in filas}, objetivo)
            for f in filas:
                resultado[id(f)]["total_directo"] = asignado[id(f)]
            if sum(asignado.values()) != objetivo:
                desvios.append((fam["nombre"], "total", objetivo, sum(asignado.values())))

        # opciones de las 2pm (tandas 1/2/3): el total de la familia se reparte como lo tenía cada producto en la base
        for i in range(3):
            objetivo = fam["opciones"][i]
            pesos = {id(f): (f.tandas[i] or 0) for f in filas}
            if not any(pesos.values()) and objetivo:
                pesos = {id(f): sum(t or 0 for t in f.tandas) or f.total for f in filas}
            if not any(pesos.values()):
                continue
            unidad = _unidad([t for f in filas for t in f.tandas if t] + [objetivo], 6)
            ideales = {fid: w * objetivo / sum(pesos.values()) for fid, w in pesos.items()}
            asignado = _asignar(ideales, {fid: unidad for fid in ideales}, objetivo)
            for f in filas:
                if asignado[id(f)] or f.tandas[i] is not None:
                    resultado[id(f)]["tandas"][i] = asignado[id(f)]

        for f in filas:
            r = resultado[id(f)]
            total = r.get("total_directo", sum(r["horas"].values()))
            tandas = tuple(r["tandas"][i] if r["tandas"][i] is not None else (0 if f.tandas[i] is not None else None) for i in range(3))
            nuevas[id(f)] = Fila(f.codigo, f.producto, r["horas"], total, tandas, f.reserva)

    plan = Plan(fecha=fecha, punto=base.punto, etiquetas_tandas=tuple(semana.etiquetas),
                filas=[nuevas[id(f)] for f in estructura], fuente=semana.fuente)
    return DesdeSemana(plan=plan, semana=semana, base=base, sin_familia=sin_familia, desvios=desvios)


# --------------------------------------------------------------------------------------------- salida: xlsx y PDF

VERDE_OSCURO, VERDE_CLARO = "375623", "E2EFDA"


def _celdas_fila(f: Fila) -> list:
    return ([f.codigo, f.producto] + [f.horas.get(h) for h in HORAS] + [f.total] + list(f.tandas) + [f.reserva])


def plan_a_xlsx(plan: Plan) -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PLAN DEL DIA"
    lleno = PatternFill("solid", fgColor=VERDE_OSCURO)
    claro = PatternFill("solid", fgColor=VERDE_CLARO)
    blanco = Font(bold=True, color="FFFFFF")
    borde = Border(*(Side(style="thin", color="000000"),) * 4)
    ws.merge_cells("A1:R1")
    ws["A1"] = titulo(plan)
    ws["A1"].font, ws["A1"].fill, ws["A1"].alignment = Font(bold=True, size=13, color="FFFFFF"), lleno, Alignment(horizontal="center")
    cab = (["CODIGO", "PRODUCTO"] + [("13\n1PM" if h == 13 else str(h)) for h in HORAS] + ["TOTAL\n5PM"] + list(plan.etiquetas_tandas) + ["RESERVA\n(refri)"])
    ws.append(cab)
    for c in ws[2]:
        c.font, c.fill, c.alignment, c.border = blanco, lleno, Alignment(horizontal="center", vertical="center", wrap_text=True), borde
    for i, f in enumerate(plan.filas):
        ws.append(_celdas_fila(f))
        for c in ws[ws.max_row]:
            c.border = borde
            c.alignment = Alignment(horizontal="left" if c.column == 2 else "center")
            if i % 2 == 1:
                c.fill = claro
    t = totales(plan)
    ws.append(["", "TOTAL"] + [t["horas"][h] for h in HORAS] + [t["total"]] + list(t["tandas"]) + [t["reserva"]])
    for c in ws[ws.max_row]:
        c.font, c.fill, c.border, c.alignment = blanco, lleno, borde, Alignment(horizontal="center")
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 7, 30
    for col in "CDEFGHIJKLMNOPQR":
        ws.column_dimensions[col].width = 8
    ws.freeze_panes = "C3"
    ws.page_setup.orientation, ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = "landscape", 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _html_filas(filas: list, con_total: Plan | None) -> str:
    html = []
    for i, f in enumerate(filas):
        fondo = "alt" if i % 2 == 1 else ""
        celdas = _celdas_fila(f)
        html.append(f'<tr class="{fondo}"><td class="c">{celdas[0]}</td><td class="p">{f.producto}</td>'
                    + "".join(f'<td class="n{" sep" if h == 14 else ""}">{"" if not f.horas.get(h) else f.horas[h]}</td>' for h in HORAS)
                    + f'<td class="n">{f.total}</td>'
                    + "".join(f'<td class="n">{"" if t is None else t}</td>' for t in f.tandas)
                    + f'<td class="n">{"" if f.reserva is None else f.reserva}</td></tr>')
    if con_total is not None:
        t = totales(con_total)
        html.append('<tr class="tot"><td></td><td class="p">TOTAL</td>' + "".join(f'<td class="n">{t["horas"][h]}</td>' for h in HORAS)
                    + f'<td class="n">{t["total"]}</td>' + "".join(f'<td class="n">{x}</td>' for x in t["tandas"]) + f'<td class="n">{t["reserva"]}</td></tr>')
    return "".join(html)


_CSS = """
table { border-collapse: collapse; width: 786pt; font-family: sans-serif; font-size: 8.5pt; }
td, th { border: 0.5pt solid #000000; padding: 2.7pt 3pt; }
th { background-color: #375623; color: #ffffff; font-weight: bold; text-align: center; font-size: 8.5pt; }
th.t { font-size: 11.5pt; padding: 4pt; }
td.n { text-align: center; } td.p { text-align: left; }
td.sep { border-left: 1.2pt solid #000000; }
tr.alt td { background-color: #e2efda; }
tr.tot td { background-color: #375623; color: #ffffff; font-weight: bold; }
"""

# anchos en puntos (suman 786): CODIGO, PRODUCTO, 11 horas, TOTAL, tandas 1/2/3, RESERVA
_ANCHOS = [20, 190] + [33] * 11 + [44] + [33] * 3 + [50]


def plan_a_pdf(plan: Plan, filas_por_pagina: int = 33) -> bytes:
    """PDF horizontal A4 con la misma tabla de la hoja (encabezado repetido en cada página, TOTAL al final)."""
    import pymupdf

    w = [a - 7 for a in _ANCHOS]            # el ancho del motor HTML no incluye el relleno (3pt a cada lado) ni el borde
    cab_horas = "".join(f'<th style="width:{w[2 + i]}pt">{"13<br>1PM" if h == 13 else h}</th>' for i, h in enumerate(HORAS))
    etiquetas = "".join(f'<th style="width:{w[14 + i]}pt">{e.replace(chr(10), "<br>")}</th>' for i, e in enumerate(plan.etiquetas_tandas))
    cabecera = (f'<tr><th class="t" colspan="18">{titulo(plan)}</th></tr>'
                f'<tr><th style="width:{w[0]}pt">CO<br>DI<br>GO</th><th style="width:{w[1]}pt">PRODUCTO</th>{cab_horas}'
                f'<th style="width:{w[13]}pt">TOTAL<br>5PM</th>{etiquetas}<th style="width:{w[17]}pt">RESERVA<br>(refri)</th></tr>')
    paginas = [plan.filas[i:i + filas_por_pagina] for i in range(0, len(plan.filas), filas_por_pagina)] or [[]]
    doc = pymupdf.open()
    for n, filas in enumerate(paginas):
        page = doc.new_page(width=842, height=595)
        ultima = n == len(paginas) - 1
        cuerpo = _html_filas(filas, plan if ultima else None)
        html = f"<table>{cabecera}{cuerpo}</table>"
        page.insert_htmlbox(pymupdf.Rect(28, 24, 814, 575), html, css=_CSS)
    return doc.tobytes()
