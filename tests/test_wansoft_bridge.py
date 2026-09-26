from sqlalchemy import create_engine, func, select

from db import insert_lines, metadata, sales_lines


def test_overlapping_wansoft_exports_replace_ticket_lines():
    engine = create_engine("sqlite://", future=True)
    metadata.create_all(engine)
    base = {
        "sucursal": "Centro", "fecha": "2026-09-20", "anio": 2026,
        "movimiento_pdv": 101, "accion": "Venta", "es_modificador": "No",
        "tipo_grupo": "CAFETERIA", "grupo": "Bebidas", "platillo": "Café",
        "cantidad": 1, "precio_unit_con_mod": 40.0, "importe": 40.0,
        "cargado_en": "2026-09-21T10:00:00",
    }
    insert_lines(engine, [{**base, "archivo_origen": "first.xlsx", "fila_origen": 10}])
    insert_lines(engine, [{**base, "archivo_origen": "overlap.xlsx", "fila_origen": 22,
                           "precio_unit_con_mod": 42.5, "importe": 42.5}])

    with engine.connect() as conn:
        count, revenue = conn.execute(select(func.count(), func.sum(sales_lines.c.importe))).one()
    assert count == 1
    assert revenue == 42.5
