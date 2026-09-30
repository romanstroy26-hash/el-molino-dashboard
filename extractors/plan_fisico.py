"""
extractors/plan_fisico.py -- lee un PDF de plan de producción físico (foto
del papel de la cocina, escaneada/exportada como PDF con el nombre
"Plan_{día en español}_{fecha}.pdf") y devuelve un dict normalizado con la
fecha y las piezas planeadas por producto.

Mismo principio que extractors/wansoft.py: separar "leer el archivo" de
"guardarlo en la base" (ver db.insert_plan_fisico) -- si mañana cambia el
formato del PDF, solo se toca este módulo.

Reglas de nombre de archivo (confirmadas a mano sobre ~50 PDFs reales,
carpeta de Drive "El Molino Ruso - Planes de Producción", sep. 2026):
  - "_PRUEBA" en el nombre -- archivo de prueba, no es un día real -> se
    ignora (extract devuelve None).
  - Un sufijo numérico "(1)", "(2)"... NO indica cuál es la revisión más
    reciente (comprobado: a veces el sufijo más alto es el más VIEJO) --
    quien llama debe decidir por fecha de modificación del archivo, no por
    el sufijo. Este módulo solo expone `es_plan_fisico()` para reconocer el
    patrón; auto_carga.py hace el des-duplicado.

Estructura de la tabla dentro del PDF (confirmada con pdfplumber en el
mismo lote): 18 columnas -- CODIGO, PRODUCTO, 7,8,9,10,11,12,"13\n1PM",
14,15,16,17,"TOTAL\n5PM",1,2,3,"RESERVA(refri)". La columna de índice 13
(0-based) es el TOTAL de piezas de ese producto para el día completo --
la única que importa aquí (no se abre por hora).
"""

from pathlib import Path
import re

import pdfplumber

_NOMBRE_RE = re.compile(
    r"^Plan_[^_]+_(\d{4}-\d{2}-\d{2})(_PRUEBA)?(\(\d+\))?\.pdf$", re.IGNORECASE
)

COL_TOTAL_DIA = 13
FILAS_MIN = COL_TOTAL_DIA + 1

SOURCE_NAME = "plan_fisico"


def es_plan_fisico(path: Path) -> bool:
    """¿El nombre de archivo sigue el patrón "Plan_<día>_<fecha>.pdf"?
    Quien llama usa esto para decidir si vale la pena intentar extraer."""
    return bool(_NOMBRE_RE.match(path.name))


def extract(path: str | Path) -> dict | None:
    """Devuelve {"fecha": "YYYY-MM-DD", "productos": {nombre: piezas, ...}}
    o None si el archivo es de PRUEBA (se ignora a propósito, no es un día
    real). Levanta ValueError si el nombre no calza con el patrón esperado,
    o si no se encontró la tabla/columna TOTAL -- mismo contrato que
    wansoft.extract: quien llama decide qué hacer con el error (ver
    auto_carga.procesar_planes)."""
    path = Path(path)
    m = _NOMBRE_RE.match(path.name)
    if not m:
        raise ValueError(f"{path.name} no sigue el patrón 'Plan_<día>_<fecha>.pdf'")
    fecha, prueba, _sufijo = m.groups()
    if prueba:
        return None

    productos: dict[str, float] = {}
    total_dia = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for tabla in page.extract_tables():
                for fila in tabla:
                    if not fila or len(fila) < FILAS_MIN:
                        continue
                    nombre = (fila[1] or "").strip()
                    if not nombre or nombre.upper() == "PRODUCTO":
                        continue
                    total_str = (fila[COL_TOTAL_DIA] or "").strip()
                    if not total_str:
                        continue
                    try:
                        total = float(total_str)
                    except ValueError:
                        continue
                    if nombre.upper() == "TOTAL":
                        total_dia = total
                    else:
                        productos[nombre] = productos.get(nombre, 0.0) + total

    if not productos or total_dia is None:
        raise ValueError(f"{path.name}: no se encontró la tabla con columna TOTAL esperada")

    return {"fecha": fecha, "productos": productos}
