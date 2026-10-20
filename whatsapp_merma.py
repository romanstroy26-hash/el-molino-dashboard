"""Merma (lo que se tira al cierre) de los mensajes del grupo de WhatsApp «Ventas El Molino».

Cada noche alguien del turno escribe algo como:
    Buenas noches merma de hoy:
    12 vatrushka
    4 danés de frutos
    3 ciabattas
Este módulo lee el archivo «Exportar chat» (_chat.txt, sin medios), saca esas listas y empareja cada nombre con un producto de la hoja de producción.

Importante: una lista de merma es lo que se TIRÓ, no el conteo de lo que quedó. Lo que no aparece en una lista de un día con reporte es merma 0,
pero NO significa que se agotó. Por eso los datos van aparte de los sobrantes contados (ver docs/decisiones).

Puro (sin base de datos).
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata
from dataclasses import dataclass, field

import plan_dia

_CABECERA = re.compile(r"^\[(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{2}):(\d{2}):(\d{2})\]\s*([^:]+?):\s?(.*)$")
_INVISIBLES = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮﻿"), None)
_MARCA_IMAGEN = re.compile(r"\s*изображение отсутствует\s*$|\s*<media omitted>\s*$|\s*imagen omitida\s*$", re.IGNORECASE)
_ITEM = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")

# palabras del personal -> palabras de la hoja
SINONIMOS = {
    "rol": "roll", "roles": "roll", "rolls": "roll", "rolles": "roll",
    "danes": "danes", "dane": "danes", "danesses": "danes",
    "chocolatines": "chocolatin", "chocolatin": "chocolatin", "dobles": "doble", "doble": "doble",
    "naturales": "natural", "conchas": "concha", "berlinas": "berlina", "vatrushkas": "vatrushka", "baguettes": "baguette",
    "ciabattas": "ciabatta", "salchichas": "salchicha", "tartaletas": "tartaleta", "focaccias": "focaccia", "canastas": "canasta",
    "croissants": "croissant", "nidos": "nido", "bostocks": "bostock", "muffins": "muffin", "panques": "panque", "orejas": "oreja",
    "tartas": "tarta", "tropeziennes": "tropezienne", "hogazas": "hogaza", "pizzas": "pizza", "croffins": "croffin", "tussons": "tusson",
    "nutella": "chocolate", "blue": "blue",
}
_RUIDO = {"ch", "chica", "chico", "grande", "gde", "de", "del", "la", "el", "con", "y"}
# «baguette» sin más es el baguette normal (decisión del dueño); «baguette serrano» sigue siendo el serrano
POR_DEFECTO = {frozenset({"baguette"}): "Baguette Ch"}


@dataclass
class Reporte:
    fecha: dt.date                 # el día al que se refiere la merma
    publicado: dt.datetime
    autor: str
    tipo: str                      # "merma" | "no_vendible_manana"
    items: list = field(default_factory=list)       # [(cantidad, texto original)]


def _sin_acentos(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def leer_mensajes(texto: str) -> list:
    """[(datetime, autor, [líneas del mensaje])] del archivo _chat.txt de WhatsApp (formato [dd.mm.aaaa, hh:mm:ss] Autor: texto)."""
    mensajes: list = []
    for linea in texto.translate(_INVISIBLES).splitlines():
        m = _CABECERA.match(linea)
        if m:
            d, mes, a, hh, mm, ss = (int(x) for x in m.group(1, 2, 3, 4, 5, 6))
            mensajes.append([dt.datetime(a, mes, d, hh, mm, ss), m.group(7).strip(), [m.group(8)]])
        elif mensajes:
            mensajes[-1][2].append(linea)
    return [(f, autor, [_MARCA_IMAGEN.sub("", x).rstrip() for x in lineas]) for f, autor, lineas in mensajes]


def extraer_reportes(texto: str) -> list:
    """Las listas de merma del chat. Un mensaje cuenta si menciona "merma" y trae al menos una línea «N producto» (los que solo traen foto se
    ignoran: sin cifras no hay nada que leer). "Merma de ayer" es del día anterior. «Tenemos ... que no podemos vender mañana» (lista de
    producto sin venta posible) se guarda como otro tipo."""
    salida = []
    for publicado, autor, lineas in leer_mensajes(texto):
        cuerpo = _sin_acentos("\n".join(lineas))
        items = [(int(m.group(1)), m.group(2)) for m in (_ITEM.match(x) for x in lineas[1:] + [lineas[0]]) if m]
        # la primera línea del mensaje puede ser «Buenas noches merma de hoy» (sin cifra) o «12 danés»; _ITEM solo acepta las que empiezan con número
        if not items:
            continue
        if "merma" in cuerpo:
            dia = publicado.date() - dt.timedelta(days=1) if "ayer" in cuerpo else publicado.date()
            salida.append(Reporte(dia, publicado, autor, "merma", items))
        elif "no podemos vender" in cuerpo or cuerpo.lstrip().startswith("tenemos"):
            salida.append(Reporte(publicado.date(), publicado, autor, "no_vendible_manana", items))
    return salida


def _tokens(nombre: str) -> list:
    t = _sin_acentos(nombre)
    t = t.replace("blue berry", "blueberry").replace("blue-berry", "blueberry")
    palabras = re.findall(r"[a-z0-9]+", t)
    return [SINONIMOS.get(p, p) for p in palabras if p not in _RUIDO]


def emparejar(nombre: str, catalogo: list) -> tuple[str | None, str]:
    """(clave del catálogo | None, cómo se llegó). `catalogo` = [plan_propio.Item]. Primero las palabras del nombre dentro de un solo producto
    de la hoja ("danés mango" -> Danes Mango Maracuya); si no, el producto de la hoja cuyas palabras están todas en el nombre (el más
    específico); si no, parecido de texto. Nada dudoso se adivina: si hay empate, devuelve None."""
    q = set(_tokens(nombre))
    if not q:
        return None, "vacío"
    claves = {i.clave: set(i.clave.split()) for i in catalogo}
    for palabras, producto in POR_DEFECTO.items():                      # reglas del dueño para nombres a medias
        clave = plan_dia.clave_producto(producto)
        if q == set(palabras) and clave in claves:
            return clave, "regla del dueño"
    dentro = [(len(p - q), k) for k, p in claves.items() if q <= p]
    if dentro:
        dentro.sort()
        if len(dentro) == 1 or dentro[0][0] < dentro[1][0]:
            return dentro[0][1], "palabras del nombre dentro de un producto"
        return None, "ambiguo: " + ", ".join(k for _, k in dentro[:3])
    contiene = [(len(p), k) for k, p in claves.items() if len(p) >= 1 and p <= q]
    if contiene:
        contiene.sort(reverse=True)
        if len(contiene) == 1 or contiene[0][0] > contiene[1][0]:
            return contiene[0][1], "producto de la hoja dentro del nombre"
    cerca = difflib.get_close_matches(" ".join(sorted(q)), list(claves), n=2, cutoff=0.85)
    if cerca and (len(cerca) == 1 or difflib.SequenceMatcher(None, " ".join(sorted(q)), cerca[0]).ratio() - difflib.SequenceMatcher(None, " ".join(sorted(q)), cerca[1]).ratio() > 0.05):
        return cerca[0], "parecido de texto"
    return None, "no está en la hoja"


def clasificar(reporte: Reporte, catalogo: list) -> tuple[list, list]:
    """([(clave, producto, cantidad, nombre original, método)], [(cantidad, nombre original, motivo)]) -- lo emparejado y lo que no."""
    nombres = {i.clave: i.producto for i in catalogo}
    bien: dict = {}
    mal = []
    for cantidad, texto in reporte.items:
        k, como = emparejar(texto, catalogo)
        if k is None:
            mal.append((cantidad, texto, como))
        elif k in bien:
            bien[k] = (bien[k][0] + cantidad, bien[k][1] + " + " + texto, bien[k][2])
        else:
            bien[k] = (cantidad, texto, como)
    return [(k, nombres[k], c, t, m) for k, (c, t, m) in bien.items()], mal
