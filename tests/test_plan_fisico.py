"""
test_plan_fisico.py -- pruebas de la parte PURA de extractors/plan_fisico.py
(reconocimiento de nombre de archivo). El parseo del PDF en sí (pdfplumber,
columna TOTAL) no se cubre aquí -- mismo criterio que wansoft.extract en
tests/test_metrics.py: se verifica a mano contra archivos reales antes de
publicar, una base de prueba con PDFs de muestra sería mantenimiento aparte
para un beneficio menor.
"""

from pathlib import Path

from extractors import plan_fisico


def test_es_plan_fisico_nombre_valido():
    assert plan_fisico.es_plan_fisico(Path("Plan_Miércoles_2026-09-30.pdf"))


def test_es_plan_fisico_con_sufijo_numerico():
    assert plan_fisico.es_plan_fisico(Path("Plan_Lunes_2026-09-14(3).pdf"))


def test_es_plan_fisico_prueba_tambien_reconocido():
    # _PRUEBA sigue siendo un nombre reconocido -- extract() lo filtra
    # después (devuelve None), no es tarea de es_plan_fisico() rechazarlo.
    assert plan_fisico.es_plan_fisico(Path("Plan_Lunes_2026-08-10_PRUEBA.pdf"))


def test_es_plan_fisico_nombre_no_coincide():
    assert not plan_fisico.es_plan_fisico(Path("Reporte Detalle De Ventas.xlsx"))
    assert not plan_fisico.es_plan_fisico(Path("otra_cosa.pdf"))


def test_extract_prueba_devuelve_none(tmp_path):
    ruta = tmp_path / "Plan_Lunes_2026-08-10_PRUEBA.pdf"
    ruta.write_bytes(b"")  # PRUEBA se filtra por nombre, antes de abrir el PDF
    assert plan_fisico.extract(ruta) is None


def test_extract_nombre_no_reconocido_levanta_valueerror(tmp_path):
    ruta = tmp_path / "otra_cosa.pdf"
    ruta.write_bytes(b"")
    try:
        plan_fisico.extract(ruta)
        assert False, "debería haber levantado ValueError"
    except ValueError:
        pass
