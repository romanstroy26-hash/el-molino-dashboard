#!/usr/bin/env python3
"""
menu.py -- один файл, одна команда для запуска, всё остальное -- меню.

Вместо того чтобы каждый раз вспоминать команду с флагами
(`py etl_load.py файл.xlsx --db el_molino.db`), запускаете один раз:

    py menu.py

...и дальше просто выбираете цифру из списка, который сама программа
и покажет. Ничего печатать руками не нужно -- файлы .xlsx она находит
сама в своей папке.
"""

import sys
from pathlib import Path

from db import (DEFAULT_DB_PATH, get_coffee_keywords, get_engine,
                 insert_lines, replace_coffee_keywords, resumen_carga)
from extractors import wansoft

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / DEFAULT_DB_PATH
DATA_DIR = HERE / "data"


def find_xlsx_files():
    """Ищет .xlsx в папке data/ (там им и место, чтобы не путаться под
    ногами у программы) и на всякий случай -- прямо в папке программы,
    если файл туда положили по старой памяти."""
    DATA_DIR.mkdir(exist_ok=True)
    files = list(DATA_DIR.glob("*.xlsx")) + list(HERE.glob("*.xlsx"))
    return sorted(p for p in files if not p.name.startswith("~$"))


def action_cargar(engine):
    files = find_xlsx_files()
    if not files:
        print(f"\nВ папке 'data' (рядом с программой) нет .xlsx файлов. "
              f"Скопируй туда выгрузку из Wansoft "
              f"('Reporte Detalle De Ventas ....xlsx') и запусти меню "
              f"заново.\n")
        return

    print("\nНайдены файлы:")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f.name}")
    print(f"  0. Загрузить ВСЕ ({len(files)} шт.)")

    choice = input("\nКакой загрузить? (номер, или Enter = все): ").strip()
    if choice == "" or choice == "0":
        chosen = files
    else:
        try:
            chosen = [files[int(choice) - 1]]
        except (ValueError, IndexError):
            print("Не понял номер, ничего не загружаю.")
            return

    print()
    for path in chosen:
        try:
            rows = wansoft.extract(path)
            intentados, insertados = insert_lines(engine, rows)
            ya_estaban = intentados - insertados
            print(f"  {path.name}: {intentados} строк продаж -> "
                  f"{insertados} новых, {ya_estaban} уже были в базе")
        except ValueError as e:
            print(f"  ПРОПУСК {path.name}: {e}")
    print("\nГотово.\n")


def action_resumen(engine):
    filas = resumen_carga(engine)
    if not filas:
        print("\nБаза пока пустая -- сначала загрузи файлы (пункт 1).\n")
        return
    print("\nЧто сейчас лежит в базе:\n")
    for row in filas:
        print(f"  {row['sucursal']:<20} {row['renglones']:>6} строк   "
              f"{row['desde']} -> {row['hasta']}   "
              f"продажи всего: {row['ventas_totales']:,.2f}")
    print()


def action_palabras(engine):
    palabras = [r["palabra"] for r in get_coffee_keywords(engine)]
    print("\nСейчас 'кофе' узнаётся по словам (в названии позиции, "
          "только в группах CAFETERIA/FRAPPES):")
    print("  " + ", ".join(palabras))
    nuevo = input(
        "\nВведи полный новый список через запятую (Enter -- оставить "
        "как есть): "
    ).strip()
    if not nuevo:
        return
    replace_coffee_keywords(engine, nuevo.split(","))
    print("Обновлено. Это сразу применится и к уже загруженным данным.\n")


def _db_label(engine) -> str:
    url = engine.url
    if url.drivername.startswith("sqlite"):
        return DB_PATH.name + " (локальный файл)"
    return f"{url.drivername}://...@{url.host}/{url.database} (облако)"


def main():
    engine = get_engine(str(DB_PATH))

    print("=" * 60)
    print("  El Molino -- система аналитики")
    print(f"  База данных: {_db_label(engine)}")
    print("=" * 60)

    while True:
        print("\nЧто сделать?")
        print("  1. Загрузить файл(ы) Wansoft из этой папки")
        print("  2. Показать, что сейчас есть в базе")
        print("  3. Список слов для распознавания кофе (посмотреть/поменять)")
        print("  0. Выход")
        choice = input("\n> ").strip()

        if choice == "1":
            action_cargar(engine)
        elif choice == "2":
            action_resumen(engine)
        elif choice == "3":
            action_palabras(engine)
        elif choice == "0":
            print("Пока!")
            break
        else:
            print("Не понял, выбери число из списка.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nПока!")
        sys.exit(0)
