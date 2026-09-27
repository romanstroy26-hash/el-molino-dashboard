"""Read a Wansoft receipt from imported sales lines for cashier loyalty credit."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.engine import Engine

from db import sales_lines


class WansoftTicketError(ValueError):
    pass


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
