#!/usr/bin/env python3
"""
limpiar_duplicados.py -- разовая уборка: убирает из базы чеки, попавшие
туда дважды из-за перекрывающихся выгрузок Wansoft.

Зачем это нужно. До сентября 2026 программа считала признаком "это уже
загружено" пару "имя файла + номер строки". Wansoft же выгружает
диапазонами дат, и диапазоны перекрываются: файл за 01.06-01.08 и файл за
01.08-15.09 содержат один и тот же первый августа. Имена у файлов разные
-- значит, для старой программы это были "разные данные", и такой день
ложился в базу дважды. Выручка за него удваивалась, а количество чеков
оставалось верным (оно считается по уникальным номерам), поэтому в
дашборде это выглядело не как ошибка, а как "средний чек вдруг вырос
вдвое".

Сама загрузка это больше не допускает (см. db.insert_lines -- теперь
единица загрузки чек, а не файл), но уже задвоенные дни надо убрать
отдельно -- этим скриптом.

Как запускать:

    py limpiar_duplicados.py              -- только ПОКАЗАТЬ, что нашлось
    py limpiar_duplicados.py --aplicar    -- показать и, после
                                             подтверждения, удалить лишнее

Работает и с локальным файлом, и с облачной базой -- с той, которая
указана в .env (то есть с той же самой, что показывает дашборд).

Что именно удаляется: если один и тот же чек пришёл из двух файлов,
остаётся копия из ОДНОГО файла -- того, где у чека больше строк (на
случай, если одна из выгрузок обрезанная), при равенстве -- из того, что
загружен позже. Сами продажи при этом не теряются: остаётся ровно одна
полная копия каждого чека.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, func, select, text

from db import DEFAULT_DB_PATH, get_engine, sales_lines

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / DEFAULT_DB_PATH

TAMANO_LOTE = 500


def _etiqueta_base(engine) -> str:
    url = engine.url
    if url.drivername.startswith("sqlite"):
        return f"{DB_PATH.name} (локальный файл на этом компьютере)"
    return f"облако: {url.drivername}, база «{url.database}» на {url.host}"


def buscar_duplicados(engine) -> list[dict]:
    """Все чеки, у которых строки пришли больше чем из одного файла --
    по одной записи на пару (чек, файл). Номер чека сквозной и не
    повторяется ни между точками, ни между днями, поэтому fecha/sucursal
    можно спокойно тащить в GROUP BY -- у одного чека они всегда одни."""
    sql = text("""
        SELECT movimiento_pdv, archivo_origen, fecha, sucursal,
               COUNT(*) AS lineas, SUM(importe) AS importe,
               MAX(cargado_en) AS cargado_en
        FROM sales_lines
        WHERE movimiento_pdv IN (
            SELECT movimiento_pdv FROM sales_lines
            WHERE movimiento_pdv IS NOT NULL
            GROUP BY movimiento_pdv
            HAVING COUNT(DISTINCT archivo_origen) > 1
        )
        GROUP BY movimiento_pdv, archivo_origen, fecha, sucursal
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql).mappings()]


def decidir_que_borrar(grupos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Делит пары (чек, файл) на "оставить" и "удалить": на каждый чек
    остаётся ровно одна пара -- с наибольшим числом строк, при равенстве
    -- загруженная последней."""
    por_ticket: dict[int, list[dict]] = defaultdict(list)
    for g in grupos:
        por_ticket[g["movimiento_pdv"]].append(g)

    conservar, borrar = [], []
    for copias in por_ticket.values():
        copias.sort(key=lambda g: (g["lineas"], g["cargado_en"] or "", g["archivo_origen"]),
                    reverse=True)
        conservar.append(copias[0])
        borrar.extend(copias[1:])
    return conservar, borrar


def _totales_por_dia(engine, fechas: list[str]) -> dict[tuple[str, str], float]:
    """Сколько выручки за эти дни лежит в базе ПРЯМО СЕЙЧАС (со всем
    задвоением) -- чтобы в отчёте показать настоящее «было -> станет», а не
    удвоенную сумму одних только дублей: в затронутом дне могут быть и
    нормальные, ни разу не задвоенные чеки."""
    if not fechas:
        return {}
    marcadores = ", ".join(f":f{i}" for i in range(len(fechas)))
    params = {f"f{i}": f for i, f in enumerate(fechas)}
    sql = text(f"""
        SELECT fecha, sucursal, SUM(importe) AS importe
        FROM sales_lines WHERE fecha IN ({marcadores})
        GROUP BY fecha, sucursal
    """)
    with engine.connect() as conn:
        return {(r["fecha"], r["sucursal"]): r["importe"] or 0.0
                for r in conn.execute(sql, params).mappings()}


def informe(engine, borrar: list[dict], total_actual: float) -> None:
    if not borrar:
        print("\nЗадвоенных чеков не найдено -- база чистая, делать нечего.\n")
        return

    por_dia: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"tickets": 0, "lineas": 0, "importe": 0.0}
    )
    for g in borrar:
        clave = (g["fecha"], g["sucursal"])
        por_dia[clave]["tickets"] += 1
        por_dia[clave]["lineas"] += g["lineas"]
        por_dia[clave]["importe"] += g["importe"] or 0.0

    total_lineas = sum(d["lineas"] for d in por_dia.values())
    total_importe = sum(d["importe"] for d in por_dia.values())
    ahora = _totales_por_dia(engine, sorted({f for f, _ in por_dia}))

    print(f"\nНайдено {len(borrar)} задвоенных чеков "
          f"({total_lineas} лишних строк). Затронуты дни:\n")
    print(f"  {'Дата':<12} {'Точка':<18} {'Чеков':>7} {'Строк':>7} "
          f"{'Сейчас':>14} {'Станет':>14}")
    print("  " + "-" * 77)
    for (fecha, sucursal), d in sorted(por_dia.items()):
        actual = ahora.get((fecha, sucursal), 0.0)
        print(f"  {fecha:<12} {sucursal:<18} {d['tickets']:>7} {d['lineas']:>7} "
              f"{actual:>14,.2f} {actual - d['importe']:>14,.2f}")
    print("  " + "-" * 77)
    print(f"\n  Лишняя выручка, которую сейчас показывает дашборд: "
          f"{total_importe:,.2f}")
    print(f"  Всего в базе сейчас: {total_actual:,.2f}  ->  станет: "
          f"{total_actual - total_importe:,.2f}\n")


def aplicar(engine, borrar: list[dict]) -> int:
    """Удаляет лишние копии -- одной транзакцией. Удаление идёт по паре
    (файл, чек), а не по id строк: так это один короткий запрос на файл,
    а не тысячи."""
    por_archivo: dict[str, list[int]] = defaultdict(list)
    for g in borrar:
        por_archivo[g["archivo_origen"]].append(g["movimiento_pdv"])

    borradas = 0
    with engine.begin() as conn:
        for archivo, tickets in por_archivo.items():
            for i in range(0, len(tickets), TAMANO_LOTE):
                lote = tickets[i:i + TAMANO_LOTE]
                res = conn.execute(
                    delete(sales_lines).where(
                        sales_lines.c.archivo_origen == archivo,
                        sales_lines.c.movimiento_pdv.in_(lote),
                    )
                )
                borradas += res.rowcount or 0
    return borradas


def _total_ventas(engine) -> float:
    with engine.connect() as conn:
        return conn.execute(select(func.sum(sales_lines.c.importe))).scalar() or 0.0


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true",
                    help="удалить лишнее (без этого флага -- только показать)")
    args = ap.parse_args()

    engine = get_engine(str(DB_PATH))
    print("=" * 60)
    print("  El Molino -- уборка задвоенных чеков")
    print(f"  База данных: {_etiqueta_base(engine)}")
    print("=" * 60)

    total_antes = _total_ventas(engine)
    grupos = buscar_duplicados(engine)
    _, borrar = decidir_que_borrar(grupos)
    informe(engine, borrar, total_antes)

    if not borrar:
        return

    if not args.aplicar:
        print("Ничего не изменено -- это был только показ.")
        print("Чтобы удалить лишнее, запусти:  py limpiar_duplicados.py --aplicar\n")
        return

    print("Удалить лишние копии? Продажи не потеряются -- у каждого чека")
    print("останется ровно одна полная копия.")
    respuesta = input("Нажми Y и Enter (любой другой ответ -- отмена): ").strip().lower()
    if respuesta not in {"y", "yes", "да", "д"}:
        print("Отменено, база не тронута.\n")
        return

    borradas = aplicar(engine, borrar)
    total_despues = _total_ventas(engine)
    print(f"\nУдалено строк: {borradas}")
    print(f"Выручка в базе: было {total_antes:,.2f}  ->  стало {total_despues:,.2f}")

    sobrantes = decidir_que_borrar(buscar_duplicados(engine))[1]
    if sobrantes:
        print(f"ВНИМАНИЕ: осталось {len(sobrantes)} задвоенных чеков -- "
              f"запусти скрипт ещё раз.")
    else:
        print("Проверка после уборки: задвоенных чеков не осталось.")
    print("\nНе забудь нажать «🔄 Обновить данные» в дашборде -- он держит "
          "цифры в памяти 5 минут.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(0)
