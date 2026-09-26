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
from db import DEFAULT_DB_PATH, get_engine, insert_lines, resumen_carga
from extractors import wansoft

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / DEFAULT_DB_PATH
DATA_DIR = HERE / "data"

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
        try:
            r = insert_lines(engine, wansoft.extract(path))
        except ValueError:
            # Не тот отчёт (нет листа "Detalle de ventas") -- запоминаем,
            # чтобы больше не открывать его при каждом запуске.
            estado[huella] = {"resultado": "не тот отчёт", "cuando": sello}
            if hablar:
                print(f"  пропуск  {path.name} -- это другой отчёт Wansoft")
            lineas_log.append(f"{sello}  пропуск {path.name}: другой отчёт")
            continue
        except Exception as e:  # noqa: BLE001 -- любой сбой на одном файле
            # не должен рушить загрузку остальных; в память НЕ пишем, чтобы
            # при следующем запуске попробовать снова.
            if hablar:
                print(f"  ОШИБКА   {path.name}: {e}")
            lineas_log.append(f"{sello}  ОШИБКА {path.name}: {e}")
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
    if not nuevos:
        print("\nНовых выгрузок нет.\n")
        _registrar([f"{sello}  новых выгрузок нет"])
        return

    print(f"\nНайдено новых файлов: {len(nuevos)}\n")
    engine = get_engine(str(DB_PATH))
    cargados, lineas_log = procesar(engine, nuevos, estado, sello)
    lineas_log.insert(0, f"{sello}  запуск, новых файлов: {len(nuevos)}")

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
