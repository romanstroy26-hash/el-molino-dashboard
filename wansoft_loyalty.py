"""Read a Wansoft receipt from imported sales lines for cashier loyalty credit."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.engine import Engine

from customer_schema import customers, purchases
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
    """Compare recent cashier credits with imported POS totals without changing points."""
    with engine.connect() as connection:
        credited = connection.execute(
            select(purchases.c.external_reference, purchases.c.total_amount,
                   purchases.c.purchased_at, customers.c.full_name)
            .join(customers, customers.c.id == purchases.c.customer_id)
            .where(purchases.c.source == "cashier", purchases.c.external_reference.is_not(None))
            .order_by(purchases.c.created_at.desc(), purchases.c.id.desc())
            .limit(limit)
        ).mappings().all()
        ticket_ids = {number for row in credited
                      if (number := _ticket_number(row["external_reference"])) is not None}
        imported = connection.execute(
            select(sales_lines.c.movimiento_pdv, sales_lines.c.importe)
            .where(sales_lines.c.movimiento_pdv.in_(ticket_ids))
        ).all() if ticket_ids else []

    imported_totals: dict[int, Decimal] = {}
    for ticket_id, amount in imported:
        imported_totals[ticket_id] = imported_totals.get(ticket_id, Decimal("0")) + Decimal(str(amount))

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
        results.append({"external_reference": reference, "customer_name": row["full_name"],
                        "purchased_at": row["purchased_at"], "credited_amount": row["total_amount"],
                        "wansoft_amount": wansoft_amount, "status": state})
    return results
