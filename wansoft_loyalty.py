"""Read a Wansoft receipt from imported sales lines for cashier loyalty credit."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.engine import Engine

from customer_schema import customers, purchase_items, purchases
from db import sales_lines


class WansoftTicketError(ValueError):
    pass


def _ticket_number(reference: str) -> int | None:
    if not reference.isascii() or not reference.isdigit() or len(reference) > 10:
        return None
    number = int(reference)
    return number if 0 < number <= 2_147_483_647 else None


def read_wansoft_ticket(engine: Engine, ticket_id: int) -> dict | None:
    with engine.connect() as connection:
        rows = connection.execute(
            select(sales_lines.c.sucursal, sales_lines.c.fecha, sales_lines.c.hora_cierre,
                   sales_lines.c.platillo, sales_lines.c.cantidad,
                   sales_lines.c.precio_unit_con_mod, sales_lines.c.importe)
            .where(sales_lines.c.movimiento_pdv == ticket_id)
            .order_by(sales_lines.c.id)
        ).mappings().all()
    if not rows:
        return None

    items = []
    total = Decimal("0.00")
    for row in rows:
        try:
            quantity = Decimal(str(row["cantidad"]))
            price = Decimal(str(row["precio_unit_con_mod"]))
            reported_amount = Decimal(str(row["importe"]))
            if not all(value.is_finite() for value in (quantity, price, reported_amount)) or quantity <= 0 or price < 0:
                raise WansoftTicketError("El ticket Wansoft contiene importes inválidos")
            quantity = quantity.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
            price = price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if quantity <= 0:
                raise WansoftTicketError("El ticket Wansoft contiene importes inválidos")
            if not row["platillo"] or not row["platillo"].strip():
                raise WansoftTicketError("El ticket Wansoft contiene un producto sin nombre")
        except WansoftTicketError:
            raise
        except (InvalidOperation, TypeError, ValueError) as error:
            raise WansoftTicketError("El ticket Wansoft contiene importes inválidos") from error
        subtotal = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if subtotal != reported_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
            raise WansoftTicketError("El total del ticket Wansoft no coincide con sus productos")
        items.append({"product_name": row["platillo"].strip(), "quantity": quantity,
                      "unit_price": price, "line_total": subtotal})
        total += subtotal

    first = rows[0]
    try:
        purchased_at = datetime.fromisoformat(first["hora_cierre"] or first["fecha"])
    except (TypeError, ValueError) as error:
        raise WansoftTicketError("El ticket Wansoft no tiene una fecha válida") from error
    return {"external_reference": str(ticket_id), "sucursal": first["sucursal"],
            "purchased_at": purchased_at, "total_amount": total, "items": items}


def list_wansoft_reconciliation(engine: Engine, limit: int = 50) -> list[dict]:
    """Compare recent cashier credits with imported POS totals and items."""
    with engine.connect() as connection:
        credited = connection.execute(
            select(purchases.c.id, purchases.c.external_reference, purchases.c.total_amount,
                   purchases.c.purchased_at, customers.c.full_name)
            .join(customers, customers.c.id == purchases.c.customer_id)
            .where(purchases.c.source == "cashier", purchases.c.external_reference.is_not(None))
            .order_by(purchases.c.created_at.desc(), purchases.c.id.desc())
            .limit(limit)
        ).mappings().all()
        ticket_ids = {number for row in credited
                      if (number := _ticket_number(row["external_reference"])) is not None}
        imported = connection.execute(
            select(sales_lines.c.movimiento_pdv, sales_lines.c.platillo,
                   sales_lines.c.cantidad, sales_lines.c.precio_unit_con_mod,
                   sales_lines.c.importe)
            .where(sales_lines.c.movimiento_pdv.in_(ticket_ids))
        ).mappings().all() if ticket_ids else []
        purchase_ids = [row["id"] for row in credited]
        credited_items = connection.execute(
            select(purchase_items.c.purchase_id, purchase_items.c.product_name,
                   purchase_items.c.quantity, purchase_items.c.unit_price,
                   purchase_items.c.line_total)
            .where(purchase_items.c.purchase_id.in_(purchase_ids))
        ).mappings().all() if purchase_ids else []

    imported_totals: dict[int, Decimal] = {}
    imported_by_ticket = defaultdict(list)
    for item in imported:
        ticket_id = item["movimiento_pdv"]
        imported_totals[ticket_id] = imported_totals.get(ticket_id, Decimal("0")) + Decimal(str(item["importe"]))
        imported_by_ticket[ticket_id].append(item)
    credited_by_purchase = defaultdict(list)
    for item in credited_items:
        credited_by_purchase[item["purchase_id"]].append(item)

    results = []
    for row in credited:
        reference = row["external_reference"]
        ticket_id = _ticket_number(reference)
        wansoft_amount = imported_totals.get(ticket_id) if ticket_id is not None else None
        if ticket_id is None:
            state = "unverifiable"
        elif wansoft_amount is None:
            state = "pending_import"
        else:
            wansoft_amount = wansoft_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            state = "matched" if wansoft_amount == row["total_amount"] else "amount_mismatch"
        item_differences = []
        if wansoft_amount is not None:
            item_differences = _item_differences(credited_by_purchase[row["id"]], imported_by_ticket[ticket_id])
            if state == "matched" and item_differences:
                state = "items_mismatch"
        results.append({"external_reference": reference, "customer_name": row["full_name"],
                        "purchased_at": row["purchased_at"], "credited_amount": row["total_amount"],
                        "wansoft_amount": wansoft_amount, "status": state,
                        "item_differences": item_differences})
    return results


def _item_differences(credited_items: list[dict], imported_items: list[dict]) -> list[str]:
    """Describe quantity and subtotal differences, grouping repeated product lines."""
    def summarize(items: list[dict], name_field: str, price_field: str, total_field: str):
        summary = defaultdict(lambda: [Decimal("0"), Decimal("0")])
        for item in items:
            name = " ".join(str(item[name_field] or "").split()).casefold()
            price = Decimal(str(item[price_field])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            key = (name, price)
            summary[key][0] += Decimal(str(item["quantity" if name_field == "product_name" else "cantidad"]))
            summary[key][1] += Decimal(str(item[total_field]))
        return summary

    credited = summarize(credited_items, "product_name", "unit_price", "line_total")
    wansoft = summarize(imported_items, "platillo", "precio_unit_con_mod", "importe")
    differences = []
    for name, price in sorted(credited.keys() | wansoft.keys()):
        credited_quantity, credited_total = credited.get((name, price), (Decimal("0"), Decimal("0")))
        wansoft_quantity, wansoft_total = wansoft.get((name, price), (Decimal("0"), Decimal("0")))
        if credited_quantity == wansoft_quantity and credited_total == wansoft_total:
            continue
        differences.append(
            f"{name or 'Producto sin nombre'} · ${price:.2f}: "
            f"acreditado {credited_quantity:g} / Wansoft {wansoft_quantity:g}; "
            f"importe ${credited_total:.2f} / ${wansoft_total:.2f}"
        )
    return differences
