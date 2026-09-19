#!/usr/bin/env python3
"""
etl_load.py -- Блок 1c: "клей" между экстрактором и базой.

Берёт один или несколько файлов Wansoft, прогоняет через
extractors/wansoft.py и складывает результат в базу (db.py). Можно
запускать сколько угодно раз на одни и те же файлы -- повторной загрузки
не будет (UNIQUE(archivo_origen, fila_origen) в схеме).

Использование:
    python etl_load.py archivo1.xlsx archivo2.xlsx --db el_molino.db

Дальше на этой базе будет работать metrics.py (следующий блок) -- уже не
важно, из скольки файлов и за сколько лет она собрана.
"""

import argparse
import sys
from pathlib import Path

from db import get_engine, insert_lines, resumen_carga
from extractors import wansoft


def load_file(engine, path: Path) -> None:
    rows = wansoft.extract(path)
    r = insert_lines(engine, rows)
    nuevos = r["tickets"] - r["tickets_ya_estaban"]
    print(f"  {path.name}: {r['lineas']} renglones / {r['tickets']} tickets -> "
          f"{nuevos} tickets nuevos, {r['tickets_ya_estaban']} ya estaban "
          f"(recargados, sin duplicar)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="Uno o más 'Reporte Detalle De Ventas' (.xlsx) de Wansoft")
    ap.add_argument("--db", default="el_molino.db", help="Archivo de base de datos SQLite (default: el_molino.db)")
    args = ap.parse_args()

    engine = get_engine(args.db)
    print(f"Base de datos: {engine.url}\n")

    for f in args.files:
        path = Path(f)
        if not path.exists():
            print(f"AVISO: no existe {path}, se omite", file=sys.stderr)
            continue
        try:
            load_file(engine, path)
        except ValueError as e:
            print(f"AVISO: {e}", file=sys.stderr)

    print("\nResumen de lo cargado en la base:")
    for row in resumen_carga(engine):
        print(f"  {row['sucursal']:<20} {row['renglones']:>6} renglones  "
              f"{row['desde']} -> {row['hasta']}  ventas totales: {row['ventas_totales']:,.2f}")


if __name__ == "__main__":
    main()
