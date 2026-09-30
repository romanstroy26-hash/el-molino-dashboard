#!/usr/bin/env python3
"""
auto_carga.py -- автоматическая загрузка выгрузок Wansoft.

Убирает ручную часть после скачивания отчёта. Раньше было так: скачал
файл в "Загрузки" -> скопировал в папку data -> запустил Start.bat ->
выбрал пункт 1 -> выбрал файл. Теперь: скачал файл -- и всё, остальное
программа делает сама.

Что делает:
  - смотрит в папку "Загрузки" и в папку data этой программы;
  - берёт оттуда файлы Wansoft "Reporte Detalle De Ventas" (остальные
    отчёты -- "Ventas por Sucursal", "Por Horario" и прочие -- молча
    пропускает: в них нет нужных колонок);
  - загружает всё новое в базу (в ту же, что и Start.bat -- локальную
    или облачную, смотря что написано в .env);
  - запоминает, что уже загружено, чтобы не перечитывать одни и те же
    файлы каждый раз;
  - пишет отчёт о каждом запуске в data/carga.log.

Повторов можно не бояться: загрузка идёт по чекам (см. db.insert_lines),
поэтому один и тот же файл, скачанный дважды, или два файла с
пересекающимися датами дадут ровно один результат.

Как запускать:

    py auto_carga.py            -- разово (или двойным кликом Autoload.bat)
    py auto_carga.py --todo     -- заново перечитать ВСЕ файлы, даже уже
                                   загруженные (если надо достроить
                                   неполный день свежей выгрузкой)

Чтобы это происходило само, по расписанию -- см. раздел
"Автоматическая загрузка" в README.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import tiempo
from db import DEFAULT_DB_PATH, get_engine, insert_lines, insert_plan_fisico, resumen_carga
from extractors import plan_fisico, wansoft

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / DEFAULT_DB_PATH
DATA_DIR = HERE / "data"

# Planes de producción físicos (PDF, ver extractors/plan_fisico.py): una
# subcarpeta por punto de venta, el NOMBRE de la subcarpeta es la sucursal
# -- el PDF en sí no dice de forma confiable a qué punto pertenece. Poner
# fotos nuevas aquí (o sincronizar aquí la carpeta de Drive del punto) es
# la única acción manual que queda; el resto -- igual que con las ventas --
# lo hace solo el vigilante.
PLANES_DIR = DATA_DIR / "planes_produccion"

# Файл-память: какие файлы уже загружены. Лежит рядом с данными, обычный
# текст -- можно открыть и посмотреть, а если удалить, программа просто
# перечитает всё заново (дублей от этого не будет).
ESTADO = DATA_DIR / "cargados.json"
LOG = DATA_DIR / "carga.log"

load_dotenv(HERE / ".env")


def _carpetas_vigiladas() -> list[Path]:
    """Где искать новые выгрузки.

    По умолчанию -- папка data и папка "Загрузки" (туда браузер кладёт
    скачанное из Wansoft, копировать оттуда руками больше не нужно).

    Плюс любые свои папки из строки CARPETAS_EXTRA в .env, через точку с
    запятой. Смысл в облачных папках: если положить сюда папку Google
    Drive или OneDrive, которая синхронизируется с этим компьютером, то
    выгрузку можно будет скачать где угодно -- с телефона, из пекарни, с
    чужого ноутбука -- просто кинуть файл в эту папку, и он приедет сюда
    сам. Скачивать обязательно с ЭТОГО компьютера станет не нужно."""
    carpetas = [DATA_DIR, Path.home() / "Downloads"]
    for extra in os.getenv("CARPETAS_EXTRA", "").split(";"):
        extra = extra.strip()
        if extra:
            carpetas.append(Path(extra))
    return carpetas


def _huella(p: Path) -> str:
    """Опознавательный знак файла: имя + размер + время изменения. Если
    скачать отчёт заново (он стал полнее), знак поменяется -- и файл
    загрузится снова, как и должно."""
    st = p.stat()
    return f"{p.name}|{st.st_size}|{int(st.st_mtime)}"


def _cargar_estado() -> dict:
    if not ESTADO.exists():
        return {}
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Память повреждена -- не беда: перечитаем файлы заново, дублей
        # это не создаст.
        return {}


def _guardar_estado(estado: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")


def _registrar(lineas: list[str]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        for linea in lineas:
            f.write(linea + "\n")


def buscar_archivos() -> list[Path]:
    """Все .xlsx из отслеживаемых папок. Временные файлы Excel (~$...)
    пропускаем -- это не отчёты, а следы открытого окна."""
    encontrados: dict[str, Path] = {}
    for carpeta in _carpetas_vigiladas():
        if not carpeta.exists():
            continue
        for p in sorted(carpeta.glob("*.xlsx")):
            if p.name.startswith("~$"):
                continue
            # Один и тот же отчёт может лежать и в "Загрузках", и в data --
            # берём любой, содержимое одинаковое.
            encontrados.setdefault(p.name, p)
    return list(encontrados.values())


def archivos_nuevos(estado: dict) -> list[Path]:
    """Файлы, которых ещё нет в памяти загруженного."""
    return [p for p in buscar_archivos() if _huella(p) not in estado]


def buscar_archivos_plan() -> list[tuple[Path, str]]:
    """Todos los PDF de plan físico -- (ruta, sucursal), donde sucursal es
    el nombre de la subcarpeta de PLANES_DIR que contiene el archivo (ver
    comentario junto a PLANES_DIR)."""
    if not PLANES_DIR.exists():
        return []
    encontrados = []
    for carpeta_sucursal in sorted(PLANES_DIR.iterdir()):
        if not carpeta_sucursal.is_dir():
            continue
        for p in sorted(carpeta_sucursal.glob("*.pdf")):
            encontrados.append((p, carpeta_sucursal.name))
    return encontrados


def archivos_plan_nuevos(estado: dict) -> list[tuple[Path, str]]:
    """Igual que archivos_nuevos(), para los PDF de plan físico. Comparte
    el mismo diccionario `estado` que las ventas -- los nombres nunca
    chocan (.pdf contra .xlsx), así que no hace falta un archivo aparte."""
    return [(p, suc) for p, suc in buscar_archivos_plan() if _huella(p) not in estado]


def procesar(engine, rutas: list[Path], estado: dict, sello: str,
             hablar: bool = True) -> tuple[int, list[str]]:
    """Грузит указанные файлы, обновляет память и возвращает
    (сколько загружено, строки для журнала).

    Отдельной функцией -- потому что этим пользуются двое: разовый запуск
    (main ниже) и фоновый сторож vigilar.py. Логика загрузки должна быть
    одна на обоих, иначе они рано или поздно разойдутся."""
    lineas_log = []
    cargados = 0

    for path in rutas:
        huella = _huella(path)

        # Разбор файла и загрузка в базу -- РАЗНЫЕ по природе шаги, и
        # ошибку на каждом из них надо помнить по-разному.
        #
        # Разбор (открыть .xlsx, найти нужный лист, прочитать строки) --
        # если он падает, дело в САМОМ ФАЙЛЕ: это не тот отчёт, файл
        # битый, или его записал openpyxl другой версии, с которым наш
        # openpyxl не дружит. Повторная попытка ничего не изменит -- байты
        # файла те же самые. Такую ошибку запоминаем, чтобы не пытаться
        # заново каждые 15 секунд бесконечно (обнаружено вживую: рядом с
        # выгрузками Wansoft в "Загрузках" лежат сотни чужих .xlsx, и
        # несколько из них падали именно так -- без этой развилки сторож
        # долбил бы одни и те же безнадёжные файлы вечно).
        try:
            filas = list(wansoft.extract(path))
        except Exception as e:  # noqa: BLE001 -- любая ошибка РАЗБОРА
            motivo = "другой отчёт" if isinstance(e, ValueError) else str(e)
            estado[huella] = {"resultado": f"не читается: {motivo}", "cuando": sello}
            if hablar:
                print(f"  пропуск  {path.name} -- {motivo}")
            lineas_log.append(f"{sello}  пропуск {path.name}: {motivo}")
            continue

        # Запись в базу -- если она падает, дело может быть во ВРЕМЕННОЙ
        # недоступности (сеть, облачная база на минуту легла) -- файл
        # прочитался нормально, значит имеет смысл повторить позже. В
        # память НЕ пишем -- пусть попробует ещё раз на следующем цикле.
        try:
            r = insert_lines(engine, filas)
        except Exception as e:  # noqa: BLE001
            if hablar:
                print(f"  ОШИБКА   {path.name}: {e}")
            lineas_log.append(f"{sello}  ОШИБКА (повторим позже) {path.name}: {e}")
            continue

        nuevos_tickets = r["tickets"] - r["tickets_ya_estaban"]
        estado[huella] = {
            "resultado": f"{r['lineas']} строк, {r['tickets']} чеков",
            "cuando": sello,
        }
        cargados += 1
        if hablar:
            print(f"  загружен {path.name}: {r['lineas']} строк / {r['tickets']} чеков "
                  f"-> {nuevos_tickets} новых, {r['tickets_ya_estaban']} обновлено")
        lineas_log.append(
            f"{sello}  загружен {path.name}: {r['lineas']} строк, "
            f"{r['tickets']} чеков ({nuevos_tickets} новых)")

    _guardar_estado(estado)
    return cargados, lineas_log


def procesar_planes(engine, archivos: list[tuple[Path, str]], estado: dict, sello: str,
                     hablar: bool = True) -> tuple[int, list[str]]:
    """Igual que procesar(), para los PDF de plan físico -- ver el
    comentario de esa función sobre por qué es una sola función compartida
    entre el run manual y el vigilante, y por qué se distingue error de
    LECTURA (archivo malo, no reintentar) de error de ESCRITURA (base
    caída, reintentar en el próximo ciclo)."""
    lineas_log = []
    cargados = 0

    for path, sucursal in archivos:
        huella = _huella(path)

        try:
            resultado = plan_fisico.extract(path)
        except Exception as e:  # noqa: BLE001 -- error de LECTURA, no reintentar
            # A diferencia de wansoft.extract (donde ValueError SIEMPRE
            # significa "otro tipo de reporte"), aquí ValueError puede ser
            # por nombre no reconocido O por tabla/columna TOTAL no
            # encontrada dentro de un PDF con nombre válido -- son cosas
            # distintas, no colapsar el mensaje, para que el registro diga
            # cuál de las dos pasó.
            motivo = str(e)
            estado[huella] = {"resultado": f"не читается: {motivo}", "cuando": sello}
            if hablar:
                print(f"  пропуск  {path.name} -- {motivo}")
            lineas_log.append(f"{sello}  пропуск (план) {path.name}: {motivo}")
            continue

        if resultado is None:  # _PRUEBA -- se ignora a propósito, no es un día real
            estado[huella] = {"resultado": "prueba (ignorado)", "cuando": sello}
            lineas_log.append(f"{sello}  пропуск (план, PRUEBA) {path.name}")
            continue

        try:
            estado_carga = insert_plan_fisico(
                engine, sucursal, resultado["fecha"], resultado["productos"],
                archivo_origen=path.name, archivo_mtime=path.stat().st_mtime,
            )
        except Exception as e:  # noqa: BLE001 -- error de ESCRITURA, reintentar después
            if hablar:
                print(f"  ОШИБКА   {path.name}: {e}")
            lineas_log.append(f"{sello}  ОШИБКА (план, повторим позже) {path.name}: {e}")
            continue

        estado[huella] = {"resultado": f"план {resultado['fecha']} ({sucursal}): {estado_carga}", "cuando": sello}
        cargados += 1
        if hablar:
            print(f"  загружен (план) {path.name}: {resultado['fecha']} ({sucursal}) -> {estado_carga}")
        lineas_log.append(f"{sello}  загружен (план) {path.name}: {resultado['fecha']} ({sucursal}) -> {estado_carga}")

    _guardar_estado(estado)
    return cargados, lineas_log


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--todo", action="store_true",
                    help="перечитать все файлы, даже уже загруженные")
    args = ap.parse_args()

    estado = {} if args.todo else _cargar_estado()

    sello = tiempo.sello_de_tiempo()
    print("=" * 60)
    print("  El Molino -- автоматическая загрузка")
    print(f"  Время (Сан-Луис-Потоси): {tiempo.etiqueta()}")
    print("=" * 60)

    nuevos = archivos_nuevos(estado)
    nuevos_plan = archivos_plan_nuevos(estado)
    if not nuevos and not nuevos_plan:
        print("\nНовых выгрузок нет.\n")
        _registrar([f"{sello}  новых выгрузок нет"])
        return

    engine = get_engine(str(DB_PATH))
    lineas_log = [f"{sello}  запуск, новых файлов: {len(nuevos)}, новых планов: {len(nuevos_plan)}"]
    cargados = 0

    if nuevos:
        print(f"\nНайдено новых файлов (продажи): {len(nuevos)}\n")
        c, l = procesar(engine, nuevos, estado, sello)
        cargados += c
        lineas_log += l

    if nuevos_plan:
        print(f"\nНайдено новых файлов (план): {len(nuevos_plan)}\n")
        c, l = procesar_planes(engine, nuevos_plan, estado, sello)
        cargados += c
        lineas_log += l

    print(f"\nЗагружено файлов: {cargados}")
    print("\nЧто сейчас в базе:")
    for row in resumen_carga(engine):
        print(f"  {row['sucursal']:<20} {row['renglones']:>7} строк   "
              f"{row['desde']} -> {row['hasta']}")
    print()
    _registrar(lineas_log)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(0)
