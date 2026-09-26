"""
extractors/wansoft.py -- Блок 1a: экстрактор источника "Wansoft".

Единственная задача этого модуля: превратить один файл Wansoft
"Reporte Detalle De Ventas" (.xlsx) в поток НОРМАЛИЗОВАННЫХ словарей --
одна и та же форма записи (sucursal, fecha, importe, cantidad, es_cafe, ...)
независимо от того, откуда взялись данные.

Почему это отдельный, маленький модуль (а не всё в одном скрипте, как
раньше в wansoft_analisis_cafe.py): когда появится второй источник данных
(например выгрузка из другой кассы, или ручной CSV со склада), для него
пишется свой extractors/<источник>.py с такой же сигнатурой
`extract(path) -> Iterator[dict]`, а db.py / metrics.py / dashboard.py
не меняются вообще -- они работают с нормализованными строками, а не
с форматом конкретной кассы.

Правила разбора идентичны предыдущим скриптам этого разговора (проверено
на реальных данных El Molino, сходится с официальными итогами Wansoft):
  - importe строки = Cantidad x "Precio unitario con modificador"
    (колонки Subtotal/Total в этом отчёте -- это итог ВСЕЙ ОРДЕРА,
    повторённый на каждой строке, для суммы по позициям не годятся).
  - строки-модификаторы (Es modificador? = "Sí") исключаются -- их
    стоимость уже включена в цену родительской позиции.
  - берутся только строки Acción = "Venta" (без аннуляций/отмен/скидок).

Этот модуль НЕ решает, что такое "кофе" -- он просто сохраняет platillo
(название позиции) и tipo_grupo как есть. Классификация "кофе / не кофе"
считается позже, в metrics.py, по списку слов из базы (таблица
coffee_keywords, редактируется через страницу "Настройки" в дашборде).
Так правка списка (добавили новый напиток в меню) сразу применяется и к
уже загруженным данным, не нужно грузить файлы заново.
"""

from pathlib import Path
from typing import Iterator

import openpyxl

import tiempo

# Índices de columna (0-based), confirmados en la hoja "Detalle de ventas".
COL_FECHA = 3
COL_HORA_CIERRE = 4    # "Hora de cierre" -- fecha+hora completos del ticket
COL_MOVIMIENTO_PDV = 6  # id numérico único por CHECK (no por línea) -- para contar "ventas" (cheques) y calcular el ticket promedio
COL_ACCION = 14
COL_CANTIDAD = 20
COL_PRECIO_CON_MOD = 22
COL_TIPO_GRUPO = 26
COL_GRUPO = 27
COL_PLATILLO = 29
COL_ES_MODIFICADOR = 33
HEADER_ROW_0BASED = 8

SOURCE_NAME = "wansoft_detalle_ventas"


def _find_sucursal(ws) -> str:
    for row in ws.iter_rows(min_row=1, max_row=6, values_only=True):
        for v in row:
            if isinstance(v, str) and v.startswith("Sucursal:"):
                return v.split(":", 1)[1].strip()
    return "SUCURSAL DESCONOCIDA"


def extract(path: str | Path) -> Iterator[dict]:
    """Lee un archivo 'Reporte Detalle De Ventas' de Wansoft y produce un
    dict normalizado por cada renglón de venta válido. No escribe nada;
    quien llama decide qué hacer con las filas (cargar a una base, sumar
    en memoria, etc.)."""
    path = Path(path)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if "Detalle de ventas" not in wb.sheetnames:
        raise ValueError(
            f"{path.name} no tiene la hoja 'Detalle de ventas' "
            f"(hojas: {wb.sheetnames}). ¿Es el reporte 'Reporte Detalle De "
            f"Ventas' de Wansoft? ('Ventas por Sucursal' no sirve aquí, "
            f"no trae fecha por renglón.)"
        )
    ws = wb["Detalle de ventas"]
    sucursal = _find_sucursal(ws)
    # Отметка "когда загрузили" -- тоже по времени Сан-Луис-Потоси, а не
    # по часам того компьютера, с которого грузят: в базе все даты и
    # времена местные, мешать их с московскими нельзя.
    cargado_en = tiempo.sello_de_tiempo()

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i <= HEADER_ROW_0BASED:
            continue
        if row[COL_ACCION] != "Venta" or row[COL_ES_MODIFICADOR] != "No":
            continue
        fecha = row[COL_FECHA]
        if fecha is None:
            continue
        d = fecha.date() if hasattr(fecha, "date") else fecha
        cantidad = row[COL_CANTIDAD] or 0
        precio = row[COL_PRECIO_CON_MOD] or 0
        tipo_grupo = row[COL_TIPO_GRUPO]
        platillo = row[COL_PLATILLO]

        hora_cierre = row[COL_HORA_CIERRE]
        hora_iso = hora_cierre.isoformat() if hasattr(hora_cierre, "isoformat") else None
        movimiento_pdv = row[COL_MOVIMIENTO_PDV]

        yield {
            "sucursal": sucursal,
            "fecha": d.isoformat(),
            "hora_cierre": hora_iso,   # fecha+hora completos, para agrupar por hora del día
            "movimiento_pdv": int(movimiento_pdv) if movimiento_pdv is not None else None,
            "anio": d.year,
            "accion": row[COL_ACCION],
            "es_modificador": row[COL_ES_MODIFICADOR],
            "tipo_grupo": tipo_grupo,
            "grupo": row[COL_GRUPO],
            "platillo": platillo,
            "cantidad": float(cantidad),
            "precio_unit_con_mod": float(precio),
            "importe": float(cantidad) * float(precio),
            "archivo_origen": path.name,
            "fila_origen": i,
            "cargado_en": cargado_en,
        }
