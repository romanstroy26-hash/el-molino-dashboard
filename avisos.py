"""Avisos en pantalla de El Molino (versión LOCAL): que no se pase el momento de cargar datos ni de anotar el cierre.

  py avisos.py datos    -> a las 13:15: ¿hay ventas de hoy hasta la 1pm? (de eso dependen la opción 1/2/3 y el pronóstico por ritmo)
  py avisos.py cierre   -> a las 20:30: ¿se anotaron los sobrantes de hoy?

Si todo está bien no muestra nada. Si falta algo, abre un cuadro de Windows con el aviso (programado con el Programador de tareas:
ElMolino_AvisoDatos y ElMolino_AvisoCierre). Las reglas son funciones puras: el dashboard usa la misma `alerta_de_datos`.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MIN_POSICIONES_CIERRE = 5


def alerta_de_datos(ahora: dt.datetime, ultima_venta_hoy: dt.datetime | None, hay_ventas_de_ayer: bool) -> str | None:
    """Texto de aviso (ruso) si faltan datos a esta hora; None si todo está en orden. `ahora` en hora local de la panadería."""
    h = ahora.hour + ahora.minute / 60
    if h >= 9.5 and not hay_ventas_de_ayer:
        return "В базе нет продаж за вчера: положите выгрузку Wansoft в папку data -- прогноз и план считаются по ним."
    if 13.25 <= h < 21.5 and (ultima_venta_hoy is None or ultima_venta_hoy.hour + ultima_venta_hoy.minute / 60 < 12.5):
        return ("В базе нет продаж за сегодня до 13:00: положите выгрузку Wansoft в папку data. По ней выбирается опция 1/2/3 "
                "и уточняется прогноз дня.")
    return None


def _proceso_vivo(pid: int) -> bool | None:
    """¿Existe un proceso con ese número? Sin lanzar programas externos (tasklist abría una ventana negra y su salida cambia de codificación
    cuando no hay consola). None si no se puede saber."""
    import ctypes

    try:
        k32 = ctypes.windll.kernel32
    except AttributeError:
        return None
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    gestor = k32.OpenProcess(0x1000, 0, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not gestor:
        error = ctypes.GetLastError()
        return True if error == 5 else False if error == 87 else None      # 5 acceso denegado = existe; 87 parámetro inválido = no existe
    codigo = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(gestor, ctypes.byref(codigo))
    k32.CloseHandle(gestor)
    return (codigo.value == 259) if ok else None        # 259 = STILL_ACTIVE


def vigilante_vivo(archivo_pid: Path | None = None) -> bool | None:
    """¿Está corriendo vigilar.py (el que carga solo los archivos de Wansoft)? None si no se puede saber. Mismo criterio que vigilar.py:
    el archivo data/vigilante.pid y que ese proceso exista."""
    if archivo_pid is None and os.name != "nt":
        return None            # en la nube (Linux) no hay vigilante: la carga la hace sync_nube.py desde el computador del dueño
    archivo_pid = archivo_pid or RAIZ / "data" / "vigilante.pid"
    try:
        pid = int(archivo_pid.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return _proceso_vivo(pid)


def recordatorio_de_cierre(ahora: dt.datetime, posiciones_anotadas_hoy: int) -> str | None:
    if ahora.hour + ahora.minute / 60 >= 20.5 and posiciones_anotadas_hoy < MIN_POSICIONES_CIERRE:
        return ("Не внесены остатки за сегодня. Откройте дашборд -> Планирование -> «Остатки» и впишите, сколько осталось "
                "(0 = всё раскупили). 2-3 минуты.")
    return None


def _preparar_entorno() -> None:
    import respaldo

    url = respaldo._url_base_local()
    if url:
        os.environ["DATABASE_URL"] = url
    sys.path.insert(0, str(RAIZ))


def _puntos_con_plan() -> list[str]:
    base = RAIZ / "data" / "planes_produccion"
    return [p.name for p in base.iterdir() if p.is_dir()] if base.exists() else []


def revisar(tipo: str, ahora: dt.datetime | None = None) -> list[str]:
    """Mensajes pendientes para `tipo` ("datos" o "cierre"); lista vacía si no hay nada que avisar."""
    _preparar_entorno()
    import db
    import tiempo
    from sqlalchemy import text

    ahora = (ahora or tiempo.ahora()).replace(tzinfo=None)
    hoy, ayer = ahora.date(), ahora.date() - dt.timedelta(days=1)
    engine = db.get_engine(str(RAIZ / db.DEFAULT_DB_PATH))
    mensajes = []
    for punto in _puntos_con_plan():
        if tipo == "datos":
            with engine.connect() as conn:
                ultima = conn.execute(text("SELECT MAX(hora_cierre) FROM sales_lines WHERE sucursal = :s AND fecha = :f"), {"s": punto, "f": hoy.isoformat()}).scalar()
                ayer_n = conn.execute(text("SELECT COUNT(*) FROM sales_lines WHERE sucursal = :s AND fecha = :f"), {"s": punto, "f": ayer.isoformat()}).scalar()
            msg = alerta_de_datos(ahora, dt.datetime.fromisoformat(str(ultima)[:19]) if ultima else None, bool(ayer_n))
        else:
            n = len({f["platillo"] for f in db.get_sobrantes(engine, punto, hoy.isoformat(), hoy.isoformat()) if f["sobrante"] is not None})
            msg = recordatorio_de_cierre(ahora, n)
        if msg:
            mensajes.append(f"{punto}: {msg}")
    return mensajes


def mostrar(texto: str, titulo: str = "El Molino") -> None:
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, texto, titulo, 0x40 | 0x1000)           # ícono de información, siempre encima


def main(argv: list[str]) -> int:
    tipo = argv[0] if argv else "datos"
    if tipo not in ("datos", "cierre"):
        print(__doc__)
        return 2
    mensajes = revisar(tipo)
    if mensajes:
        mostrar("\n\n".join(mensajes), "El Molino -- " + ("данные" if tipo == "datos" else "закрытие дня"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
