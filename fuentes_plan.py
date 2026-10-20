"""De dónde salen la lista de productos (catálogo) y el formato de las hojas del plan: la carpeta data/planes_produccion/<punto> del computador
y, en la NUBE (donde esa carpeta no existe), una copia guardada en la base de datos.

El computador del dueño publica la copia (publicar(), la llama sync_nube.py cada 10 minutos; solo escribe si cambió algo en la carpeta) y el
dashboard de la nube la lee (cargar()). La copia lleva los últimos 8 planes diarios (solo sirven para el catálogo: productos, orden, charola,
etiquetas; ninguna cantidad entra en el cálculo) y el formato de las dos hojas semanales (sin cantidades).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

TABLA = "config_plan"
PLANES_GUARDADOS = 8                 # los mismos que lee plan_propio.catalogo


def _asegurar_tabla(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE IF NOT EXISTS {TABLA} (sucursal VARCHAR NOT NULL, clave VARCHAR NOT NULL, valor TEXT NOT NULL, '
                          'actualizado VARCHAR NOT NULL, PRIMARY KEY (sucursal, clave))'))
    if engine.dialect.name == "postgresql":
        try:                                           # Supabase publica todas las tablas por su API: sin políticas, RLS la cierra
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{TABLA}" ENABLE ROW LEVEL SECURITY'))
        except Exception:  # noqa: BLE001 -- sin permiso o ya hecho: no debe impedir publicar
            pass


def firma_carpeta(carpeta: Path) -> str:
    """Huella de los PDF del plan (nombre, tamaño, fecha de modificación): cambia solo cuando llega o se cambia un archivo."""
    carpeta = Path(carpeta)
    partes = []
    if carpeta.exists():
        for p in sorted(list(carpeta.glob("Plan_*.pdf"))):
            st = p.stat()
            partes.append(f"{p.name}|{st.st_size}|{int(st.st_mtime)}")
    return hashlib.sha1("\n".join(partes).encode("utf-8")).hexdigest()


def _formato_a_dict(f) -> dict:
    d = dataclasses.asdict(f)
    d["etiquetas_opciones"] = list(f.etiquetas_opciones)
    d["filas"] = [list(x) for x in f.filas]
    return d


def _formato_de_dict(d: dict):
    import plan_semanal as ps
    d = dict(d)
    d["etiquetas_opciones"] = tuple(d["etiquetas_opciones"])
    d["filas"] = [tuple(x) for x in d["filas"]]
    return ps.Formato(**d)


def snapshot(carpeta: Path) -> dict:
    import plan_dia
    import plan_semanal

    planes = plan_dia.planes_en_carpeta(carpeta)
    ultimos = sorted(planes)[-PLANES_GUARDADOS:]
    formatos = plan_semanal.formatos_en_carpeta(carpeta)
    return {"planes": {d.isoformat(): plan_dia._plan_a_dict(planes[d]) for d in ultimos},
            "formatos": {t: _formato_a_dict(f) for t, f in formatos.items()}}


def publicar(engine, sucursal: str, carpeta: Path, forzar: bool = False) -> bool:
    """Guarda la copia en la base si la carpeta cambió desde la última vez. True si escribió."""
    carpeta = Path(carpeta)
    if not carpeta.exists():
        return False
    firma = firma_carpeta(carpeta)
    _asegurar_tabla(engine)
    with engine.connect() as conn:
        actual = conn.execute(text(f"SELECT valor FROM {TABLA} WHERE sucursal = :s AND clave = 'firma'"), {"s": sucursal}).scalar()
    if actual == firma and not forzar:
        return False
    datos = snapshot(carpeta)
    if not datos["planes"]:
        return False
    ahora = dt.datetime.now().isoformat(timespec="seconds")
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {TABLA} WHERE sucursal = :s AND clave IN ('firma', 'catalogo')"), {"s": sucursal})
        conn.execute(text(f"INSERT INTO {TABLA} (sucursal, clave, valor, actualizado) VALUES (:s, 'catalogo', :v, :a)"),
                     {"s": sucursal, "v": json.dumps(datos, ensure_ascii=False), "a": ahora})
        conn.execute(text(f"INSERT INTO {TABLA} (sucursal, clave, valor, actualizado) VALUES (:s, 'firma', :v, :a)"), {"s": sucursal, "v": firma, "a": ahora})
    return True


def _leer_de_la_base(engine, sucursal: str) -> tuple:
    import plan_dia

    try:
        with engine.connect() as conn:
            fila = conn.execute(text(f"SELECT valor, actualizado FROM {TABLA} WHERE sucursal = :s AND clave = 'catalogo'"), {"s": sucursal}).first()
    except Exception:  # noqa: BLE001 -- la tabla aún no existe: no hay copia
        return {}, {}, None
    if not fila:
        return {}, {}, None
    datos = json.loads(fila[0])
    planes = {}
    for d in datos.get("planes", {}).values():
        p = plan_dia._plan_de_dict(d)
        if p is not None:
            planes[p.fecha] = p
    return planes, {t: _formato_de_dict(f) for t, f in datos.get("formatos", {}).items()}, fila[1]


def cargar(engine, sucursal: str, carpeta: Path) -> tuple:
    """(planes, formatos): de la carpeta si está y tiene hojas; si no, de la copia en la base ({} si tampoco hay)."""
    import plan_dia
    import plan_semanal

    carpeta = Path(carpeta)
    planes = plan_dia.planes_en_carpeta(carpeta)
    formatos = plan_semanal.formatos_en_carpeta(carpeta)
    if planes and formatos:
        return planes, formatos
    base_planes, base_formatos, _ = _leer_de_la_base(engine, sucursal)
    return (planes or base_planes), (formatos or base_formatos)


def copia_actualizada_en(engine, sucursal: str) -> str | None:
    """Cuándo se publicó la copia del catálogo (None si no hay)."""
    return _leer_de_la_base(engine, sucursal)[2]
