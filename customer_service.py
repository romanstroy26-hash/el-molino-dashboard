"""Servicios de clientes y fidelidad.

Este módulo no depende de Wansoft. La app futura podrá llamar a estos
servicios desde una API sin tener acceso directo a la base de datos.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from phone_numbers import normalize_customer_phone

from customer_schema import (
    customer_events,
    customer_devices,
    campaign_recipients,
    campaign_events,
    campaigns,
    customer_profiles,
    customer_visits,
    customers,
    loyalty_accounts,
    login_challenges,
    loyalty_transactions,
    purchase_items,
    purchases,
    reward_redemptions,
    rewards,
)


class CustomerError(Exception):
    """Error de negocio esperado del módulo de clientes."""


class CustomerNotFound(CustomerError):
    pass


class InsufficientPoints(CustomerError):
    pass


class InvalidLoginCode(CustomerError):
    pass


class TooManyCodes(CustomerError):
    pass


class RedemptionNotFound(CustomerError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _id() -> str:
    return str(uuid4())


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def create_customer(
    engine: Engine,
    full_name: str,
    phone: str | None = None,
    email: str | None = None,
    marketing_consent: bool = False,
) -> dict:
    """Crea cliente + perfil + cuenta de puntos en una sola transacción."""
    full_name = full_name.strip()
    if not full_name:
        raise CustomerError("El nombre del cliente es obligatorio")

    phone = normalize_customer_phone(phone)
    email = _normalize_optional(email)
    now = _now()
    customer_id = _id()

    with engine.begin() as conn:
        _insert_customer(conn, customer_id, full_name, phone, email, marketing_consent, now)

    return get_customer(engine, customer_id)


def _insert_customer(conn, customer_id: str, full_name: str, phone: str | None,
                     email: str | None, marketing_consent: bool, now: datetime) -> None:
    if phone and conn.execute(select(customers.c.id).where(customers.c.phone == phone)).first():
        raise CustomerError("Ya existe un cliente con ese teléfono")
    if email and conn.execute(select(customers.c.id).where(customers.c.email == email)).first():
        raise CustomerError("Ya existe un cliente con ese email")
    conn.execute(customers.insert().values(
        id=customer_id, full_name=full_name, phone=phone, email=email,
        status="active", marketing_consent=marketing_consent,
        created_at=now, updated_at=now,
    ))
    conn.execute(customer_profiles.insert().values(customer_id=customer_id, created_at=now, updated_at=now))
    conn.execute(loyalty_accounts.insert().values(customer_id=customer_id, balance=0, created_at=now, updated_at=now))


def get_customer(engine: Engine, customer_id: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(select(customers).where(customers.c.id == customer_id)).mappings().first()
    if not row:
        raise CustomerNotFound(customer_id)
    return dict(row)


def update_customer(engine: Engine, customer_id: str, updates: dict) -> dict:
    """Update customer-owned identity fields while preserving unique contacts."""
    allowed = {"full_name", "email", "marketing_consent"}
    values = {key: value for key, value in updates.items() if key in allowed}
    if not values:
        return get_customer(engine, customer_id)
    if "full_name" in values:
        values["full_name"] = values["full_name"].strip()
        if not values["full_name"]:
            raise CustomerError("El nombre del cliente es obligatorio")
    if "email" in values:
        values["email"] = _normalize_optional(values["email"])
    now = _now()
    with engine.begin() as conn:
        existing = conn.execute(select(customers.c.id).where(customers.c.id == customer_id)).first()
        if not existing:
            raise CustomerNotFound(customer_id)
        if values.get("email"):
            duplicate = conn.execute(select(customers.c.id).where(customers.c.email == values["email"], customers.c.id != customer_id)).first()
            if duplicate:
                raise CustomerError("Ya existe un cliente con ese email")
        conn.execute(update(customers).where(customers.c.id == customer_id).values(**values, updated_at=now))
    return get_customer(engine, customer_id)


def get_customer_profile(engine: Engine, customer_id: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(select(customer_profiles).where(customer_profiles.c.customer_id == customer_id)).mappings().first()
    if not row:
        raise CustomerNotFound(customer_id)
    return dict(row)


def update_customer_profile(engine: Engine, customer_id: str, updates: dict) -> dict:
    """Store optional preferences separately from a customer's identity and purchase ledger."""
    allowed = {"birth_date", "preferred_store_id", "preferred_channel"}
    values = {key: _normalize_optional(value) for key, value in updates.items() if key in allowed}
    if not values:
        return get_customer_profile(engine, customer_id)
    with engine.begin() as conn:
        result = conn.execute(update(customer_profiles).where(customer_profiles.c.customer_id == customer_id).values(**values, updated_at=_now()))
        if result.rowcount == 0:
            raise CustomerNotFound(customer_id)
    return get_customer_profile(engine, customer_id)


def register_customer_device(engine: Engine, customer_id: str, platform: str, push_token: str) -> dict:
    """Register or refresh a push-capable client device for one customer."""
    platform, push_token = platform.strip().lower(), push_token.strip()
    if platform not in {"web", "ios", "android"} or not push_token:
        raise CustomerError("La plataforma y el token del dispositivo son obligatorios")
    now = _now()
    with engine.begin() as conn:
        if not conn.execute(select(customers.c.id).where(customers.c.id == customer_id)).first():
            raise CustomerNotFound(customer_id)
        existing = conn.execute(select(customer_devices).where(customer_devices.c.push_token == push_token)).mappings().first()
        if existing and existing["customer_id"] != customer_id:
            raise CustomerError("El dispositivo ya está asociado a otro cliente")
        if existing:
            conn.execute(update(customer_devices).where(customer_devices.c.id == existing["id"]).values(platform=platform, last_seen_at=now))
            device_id = existing["id"]
        else:
            device_id = _id()
            conn.execute(customer_devices.insert().values(
                id=device_id, customer_id=customer_id, platform=platform,
                push_token=push_token, created_at=now, last_seen_at=now,
            ))
    return {"id": device_id, "customer_id": customer_id, "platform": platform, "last_seen_at": now}


def find_customer_by_phone(engine: Engine, phone: str) -> dict | None:
    phone = normalize_customer_phone(phone)
    if not phone:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(customers).where(customers.c.phone == phone)).mappings().first()
    return dict(row) if row else None


def create_login_challenge(engine: Engine, phone: str, code: str, valid_for_minutes: int = 10) -> None:
    """Store a short-lived, single-use verification code without its plaintext."""
    phone = normalize_customer_phone(phone)
    if not phone or not find_customer_by_phone(engine, phone):
        raise CustomerNotFound(phone or "")
    _create_phone_challenge(engine, phone, code, valid_for_minutes)


def create_registration_challenge(engine: Engine, phone: str, code: str, valid_for_minutes: int = 10) -> None:
    """Issue a code only for a phone that is not registered yet."""
    phone = normalize_customer_phone(phone)
    if not phone:
        raise CustomerError("El teléfono es obligatorio")
    if find_customer_by_phone(engine, phone):
        raise CustomerError("Este teléfono ya está registrado")
    _create_phone_challenge(engine, phone, code, valid_for_minutes)


def _create_phone_challenge(engine: Engine, phone: str, code: str, valid_for_minutes: int) -> None:
    if len(code) != 6 or not code.isdigit():
        raise CustomerError("El código de acceso debe tener seis dígitos")
    now = _now()
    challenge_id = _id()
    with engine.begin() as conn:
        latest = conn.execute(
            select(login_challenges.c.created_at)
            .where(login_challenges.c.phone == phone)
            .order_by(login_challenges.c.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest and now - latest < timedelta(seconds=60):
            raise TooManyCodes("Espera un minuto antes de pedir otro código")
        conn.execute(
            update(login_challenges)
            .where(login_challenges.c.phone == phone, login_challenges.c.used_at.is_(None))
            .values(used_at=now)
        )
        conn.execute(login_challenges.insert().values(
            id=challenge_id, phone=phone,
            code_hash=sha256(f"{challenge_id}:{code}".encode()).hexdigest(),
            expires_at=now + timedelta(minutes=valid_for_minutes), attempts=0, created_at=now,
        ))


def verify_login_code(engine: Engine, phone: str, code: str) -> dict:
    """Verify the latest active code; it expires after 10 minutes or 5 failed attempts."""
    phone = normalize_customer_phone(phone)
    now = _now()
    if not phone or len(code) != 6 or not code.isdigit():
        raise InvalidLoginCode("Código inválido")
    with engine.begin() as conn:
        valid = _consume_phone_code(conn, phone, code, now)
    if not valid:
        raise InvalidLoginCode("Código inválido o vencido")
    customer = find_customer_by_phone(engine, phone)
    if not customer:
        raise CustomerNotFound(phone)
    return customer


def register_customer_with_code(engine: Engine, phone: str, code: str, full_name: str,
                                marketing_consent: bool = False) -> dict:
    """Consume the SMS code and create a new customer in one transaction."""
    phone = normalize_customer_phone(phone)
    full_name = full_name.strip()
    if not phone or not full_name:
        raise CustomerError("El nombre y el teléfono son obligatorios")
    if len(code) != 6 or not code.isdigit():
        raise InvalidLoginCode("Código inválido")
    now, customer_id = _now(), _id()
    with engine.begin() as conn:
        valid = _consume_phone_code(conn, phone, code, now)
        if valid:
            _insert_customer(conn, customer_id, full_name, phone, None, marketing_consent, now)
    if not valid:
        raise InvalidLoginCode("Código inválido o vencido")
    return get_customer(engine, customer_id)


def _consume_phone_code(conn, phone: str, code: str, now: datetime) -> bool:
    challenge = conn.execute(
        select(login_challenges)
        .where(login_challenges.c.phone == phone, login_challenges.c.used_at.is_(None))
        .order_by(login_challenges.c.created_at.desc())
        .with_for_update()
    ).mappings().first()
    if not challenge or challenge["expires_at"] < now or int(challenge["attempts"]) >= 5:
        return False
    expected = sha256(f"{challenge['id']}:{code}".encode()).hexdigest()
    if expected != challenge["code_hash"]:
        conn.execute(update(login_challenges).where(login_challenges.c.id == challenge["id"]).values(attempts=int(challenge["attempts"]) + 1))
        return False
    conn.execute(update(login_challenges).where(login_challenges.c.id == challenge["id"]).values(used_at=now))
    return True


def get_points_balance(engine: Engine, customer_id: str) -> int:
    with engine.connect() as conn:
        row = conn.execute(
            select(loyalty_accounts.c.balance).where(loyalty_accounts.c.customer_id == customer_id)
        ).first()
    if not row:
        raise CustomerNotFound(customer_id)
    return int(row.balance)


def list_active_rewards(engine: Engine) -> list[dict]:
    """Return the rewards currently available to a customer application."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(rewards)
            .where(rewards.c.active.is_(True))
            .order_by(rewards.c.points_cost, rewards.c.name)
        ).mappings()
        return [dict(row) for row in rows]


def create_reward(
    engine: Engine, name: str, points_cost: int, description: str | None = None,
) -> dict:
    """Create a reward that becomes available in the customer app immediately."""
    name = name.strip()
    if not name or points_cost <= 0:
        raise CustomerError("El nombre y el costo del premio son obligatorios")
    now = _now()
    reward = {"id": _id(), "name": name, "description": _normalize_optional(description), "points_cost": points_cost,
              "active": True, "created_at": now, "updated_at": now}
    with engine.begin() as conn:
        conn.execute(rewards.insert().values(**reward))
    return reward


def create_campaign(
    engine: Engine, name: str, channel: str, message: str | None, customer_ids: list[str],
    starts_at: datetime | None = None, ends_at: datetime | None = None,
) -> dict:
    """Create a campaign and its recipient list without delivering any messages."""
    name, channel = name.strip(), channel.strip().lower()
    customer_ids = list(dict.fromkeys(customer_ids))
    if not name or not channel or not customer_ids:
        raise CustomerError("La campaña necesita nombre, canal y al menos un cliente")
    if starts_at and ends_at and ends_at < starts_at:
        raise CustomerError("La fecha final no puede ser anterior a la fecha inicial")
    now, campaign_id = _now(), _id()
    with engine.begin() as conn:
        found = {row.id for row in conn.execute(select(customers.c.id).where(customers.c.id.in_(customer_ids)))}
        missing = set(customer_ids) - found
        if missing:
            raise CustomerNotFound(next(iter(missing)))
        eligible = [row.id for row in conn.execute(
            select(customers.c.id).where(
                customers.c.id.in_(customer_ids),
                customers.c.status == "active",
                customers.c.marketing_consent.is_(True),
            )
        )]
        if not eligible:
            raise CustomerError("No hay clientes con consentimiento de marketing")
        conn.execute(campaigns.insert().values(
            id=campaign_id, name=name, channel=channel, status="draft",
            starts_at=starts_at, ends_at=ends_at, message=_normalize_optional(message),
            created_at=now, updated_at=now,
        ))
        conn.execute(campaign_recipients.insert(), [
            {"id": _id(), "campaign_id": campaign_id, "customer_id": customer_id,
             "status": "pending", "scheduled_at": starts_at}
            for customer_id in eligible
        ])
    return {"id": campaign_id, "name": name, "channel": channel, "recipient_count": len(eligible), "status": "draft"}


def list_campaigns(engine: Engine) -> list[dict]:
    """List manager-visible campaigns with current recipient counts."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(campaigns.c.id, campaigns.c.name, campaigns.c.channel,
                   campaigns.c.status, campaigns.c.created_at)
            .order_by(campaigns.c.created_at.desc())
        ).mappings().all()
        return [{**dict(row), "recipient_count": int(conn.execute(
            select(func.count()).select_from(campaign_recipients)
            .where(campaign_recipients.c.campaign_id == row["id"])
        ).scalar_one())} for row in rows]


def list_customer_campaigns(engine: Engine, customer_id: str) -> list[dict]:
    """Return campaigns assigned to a customer and currently visible in their app."""
    now = _now()
    with engine.connect() as conn:
        consent = conn.execute(select(customers.c.marketing_consent).where(customers.c.id == customer_id)).scalar_one_or_none()
        if not consent:
            return []
        rows = conn.execute(
            select(campaigns, campaign_recipients.c.status.label("recipient_status"))
            .join(campaign_recipients, campaign_recipients.c.campaign_id == campaigns.c.id)
            .where(campaign_recipients.c.customer_id == customer_id,
                   campaigns.c.status == "active",
                   (campaigns.c.starts_at.is_(None)) | (campaigns.c.starts_at <= now),
                   (campaigns.c.ends_at.is_(None)) | (campaigns.c.ends_at >= now))
            .order_by(campaigns.c.starts_at.desc())
        ).mappings()
        return [dict(row) for row in rows]


def get_customer_insights(engine: Engine, customer_id: str) -> dict:
    """Build a portable Customer 360 summary from recorded purchases and loyalty data."""
    customer = get_customer(engine, customer_id)
    with engine.connect() as conn:
        purchase_rows = conn.execute(
            select(purchases.c.total_amount, purchases.c.purchased_at)
            .where(purchases.c.customer_id == customer_id)
            .order_by(purchases.c.purchased_at)
        ).all()
        favorite = conn.execute(
            select(purchase_items.c.product_name, func.sum(purchase_items.c.quantity).label("quantity"))
            .join(purchases, purchases.c.id == purchase_items.c.purchase_id)
            .where(purchases.c.customer_id == customer_id)
            .group_by(purchase_items.c.product_name)
            .order_by(func.sum(purchase_items.c.quantity).desc(), purchase_items.c.product_name)
            .limit(1)
        ).first()
    count = len(purchase_rows)
    total = sum((Decimal(str(row.total_amount)) for row in purchase_rows), Decimal("0"))
    last_purchase = purchase_rows[-1].purchased_at if purchase_rows else None
    if count == 0:
        segment, days_since = "new", None
    else:
        days_since = max((_now() - last_purchase).days, 0)
        segment = "at_risk" if days_since > 45 else "loyal" if count >= 10 else "active"
    return {
        "customer_id": customer["id"], "full_name": customer["full_name"],
        "purchase_count": count, "total_spend": float(total),
        "average_ticket": float(total / count) if count else 0.0,
        "last_purchase_at": last_purchase, "days_since_last_purchase": days_since,
        "favorite_product": favorite.product_name if favorite else None,
        "favorite_product_quantity": float(favorite.quantity) if favorite else 0.0,
        "points_balance": get_points_balance(engine, customer_id), "segment": segment,
    }


def list_customer_insights(engine: Engine, segment: str | None = None) -> list[dict]:
    """List customer summaries, optionally keeping only one marketing segment."""
    with engine.connect() as conn:
        customer_ids = [row.id for row in conn.execute(select(customers.c.id).where(customers.c.status == "active"))]
    summaries = [get_customer_insights(engine, customer_id) for customer_id in customer_ids]
    if segment:
        segment = segment.strip().lower()
        allowed = {"new", "active", "loyal", "at_risk"}
        if segment not in allowed:
            raise CustomerError("Segmento inválido")
        summaries = [summary for summary in summaries if summary["segment"] == segment]
    return summaries


def create_campaign_for_segment(
    engine: Engine, name: str, channel: str, message: str | None, segment: str,
    starts_at: datetime | None = None, ends_at: datetime | None = None,
) -> dict:
    """Freeze the current members of a segment as campaign recipients."""
    recipients = list_customer_insights(engine, segment)
    if not recipients:
        raise CustomerError("No hay clientes en este segmento")
    return create_campaign(
        engine, name=name, channel=channel, message=message,
        customer_ids=[recipient["customer_id"] for recipient in recipients],
        starts_at=starts_at, ends_at=ends_at,
    )


def list_next_best_actions(engine: Engine) -> list[dict]:
    """Produce explainable marketing suggestions from Customer 360 data."""
    actions: list[dict] = []
    for insight in list_customer_insights(engine):
        if insight["segment"] == "at_risk":
            action = {
                "action_type": "reactivate", "priority": "high",
                "reason": f"No compra desde hace {insight['days_since_last_purchase']} días.",
                "suggested_message": "Te extrañamos: vuelve por tu café favorito y descubre un reward especial.",
            }
        elif insight["segment"] == "new":
            action = {
                "action_type": "welcome", "priority": "medium",
                "reason": "Aún no tiene compras registradas.",
                "suggested_message": "Bienvenido a El Molino Club. Tu primera visita suma puntos.",
            }
        elif insight["segment"] == "loyal":
            action = {
                "action_type": "recognize", "priority": "medium",
                "reason": f"Tiene {insight['purchase_count']} compras y es un cliente frecuente.",
                "suggested_message": "Gracias por ser parte de El Molino Club: tenemos un beneficio especial para ti.",
            }
        else:
            product = insight["favorite_product"] or "tu café favorito"
            action = {
                "action_type": "cross_sell", "priority": "low",
                "reason": f"Su producto más comprado es {product}.",
                "suggested_message": f"Acompaña tu {product} con algo nuevo en tu próxima visita.",
            }
        actions.append({
            "customer_id": insight["customer_id"], "full_name": insight["full_name"],
            "segment": insight["segment"], **action,
        })
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(actions, key=lambda action: (priority_order[action["priority"]], action["full_name"]))


def activate_campaign(engine: Engine, campaign_id: str) -> dict:
    """Make a prepared campaign visible to its recipients."""
    now = _now()
    with engine.begin() as conn:
        campaign = conn.execute(select(campaigns).where(campaigns.c.id == campaign_id)).mappings().first()
        if not campaign:
            raise CustomerError("La campaña no existe")
        if campaign["status"] not in {"draft", "scheduled", "active"}:
            raise CustomerError("La campaña no se puede activar")
        conn.execute(
            delete(campaign_recipients).where(
                campaign_recipients.c.campaign_id == campaign_id,
                campaign_recipients.c.customer_id.not_in(
                    select(customers.c.id).where(
                        customers.c.status == "active",
                        customers.c.marketing_consent.is_(True),
                    )
                ),
            )
        )
        count = conn.execute(select(func.count()).select_from(campaign_recipients).where(
            campaign_recipients.c.campaign_id == campaign_id,
        )).scalar_one()
        if not count:
            raise CustomerError("La campaña no tiene destinatarios con consentimiento vigente")
        conn.execute(update(campaigns).where(campaigns.c.id == campaign_id).values(status="active", updated_at=now))
    return {"id": campaign_id, "status": "active"}


def record_campaign_event(engine: Engine, customer_id: str, campaign_id: str, event_type: str) -> str:
    """Record an in-app campaign interaction only for an assigned recipient."""
    event_type = event_type.strip().lower()
    if event_type not in {"opened", "clicked"}:
        raise CustomerError("Evento de campaña inválido")
    now, event_id = _now(), _id()
    with engine.begin() as conn:
        campaign_status = conn.execute(select(campaigns.c.status).where(campaigns.c.id == campaign_id)).scalar_one_or_none()
        consent = conn.execute(select(customers.c.marketing_consent).where(customers.c.id == customer_id)).scalar_one_or_none()
        if campaign_status != "active" or not consent:
            raise CustomerError("La campaña no está activa para este cliente")
        recipient = conn.execute(
            select(campaign_recipients).where(
                campaign_recipients.c.campaign_id == campaign_id,
                campaign_recipients.c.customer_id == customer_id,
            )
        ).mappings().first()
        if not recipient:
            raise CustomerError("La campaña no está asignada al cliente")
        conn.execute(campaign_events.insert().values(
            id=event_id, campaign_id=campaign_id, customer_id=customer_id,
            event_type=event_type, occurred_at=now,
        ))
        conn.execute(update(campaign_recipients).where(campaign_recipients.c.id == recipient["id"]).values(status=event_type))
    return event_id


def get_campaign_analytics(engine: Engine, campaign_id: str) -> dict:
    """Return delivery-list size and unique engagement counts for one campaign."""
    with engine.connect() as conn:
        campaign = conn.execute(select(campaigns.c.id, campaigns.c.name, campaigns.c.status).where(campaigns.c.id == campaign_id)).mappings().first()
        if not campaign:
            raise CustomerError("La campaña no existe")
        recipient_count = conn.execute(select(func.count()).select_from(campaign_recipients).where(campaign_recipients.c.campaign_id == campaign_id)).scalar_one()
        opened_count = conn.execute(select(func.count(func.distinct(campaign_events.c.customer_id))).where(campaign_events.c.campaign_id == campaign_id, campaign_events.c.event_type == "opened")).scalar_one()
        clicked_count = conn.execute(select(func.count(func.distinct(campaign_events.c.customer_id))).where(campaign_events.c.campaign_id == campaign_id, campaign_events.c.event_type == "clicked")).scalar_one()
    return {"id": campaign["id"], "name": campaign["name"], "status": campaign["status"],
            "recipient_count": int(recipient_count), "opened_count": int(opened_count), "clicked_count": int(clicked_count)}


def earn_points(
    engine: Engine,
    customer_id: str,
    points: int,
    reference_type: str | None = None,
    reference_id: str | None = None,
    description: str | None = None,
) -> int:
    """Acredita puntos. La transacción y el saldo se actualizan atómicamente."""
    if points <= 0:
        raise CustomerError("Los puntos a acreditar deben ser mayores que cero")

    now = _now()
    tx_id = _id()
    with engine.begin() as conn:
        account = conn.execute(
            select(loyalty_accounts.c.balance).where(loyalty_accounts.c.customer_id == customer_id)
        ).first()
        if not account:
            raise CustomerNotFound(customer_id)

        conn.execute(loyalty_transactions.insert().values(
            id=tx_id,
            customer_id=customer_id,
            points=points,
            transaction_type="earn",
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            created_at=now,
        ))
        new_balance = int(account.balance) + points
        conn.execute(
            update(loyalty_accounts)
            .where(loyalty_accounts.c.customer_id == customer_id)
            .values(balance=new_balance, updated_at=now)
        )
    return new_balance


def redeem_reward(engine: Engine, customer_id: str, reward_id: str) -> dict:
    """Canjea un premio y descuenta sus puntos en una sola transacción."""
    now = _now()
    redemption_id = _id()

    with engine.begin() as conn:
        reward = conn.execute(
            select(rewards).where(rewards.c.id == reward_id, rewards.c.active.is_(True))
        ).mappings().first()
        if not reward:
            raise CustomerError("El premio no existe o no está activo")

        account = conn.execute(
            select(loyalty_accounts.c.balance).where(loyalty_accounts.c.customer_id == customer_id)
        ).first()
        if not account:
            raise CustomerNotFound(customer_id)

        balance = int(account.balance)
        cost = int(reward.points_cost)
        if balance < cost:
            raise InsufficientPoints(f"Saldo insuficiente: {balance} de {cost} puntos")

        new_balance = conn.execute(
            update(loyalty_accounts)
            .where(
                loyalty_accounts.c.customer_id == customer_id,
                loyalty_accounts.c.balance >= cost,
            )
            .values(balance=loyalty_accounts.c.balance - cost, updated_at=now)
            .returning(loyalty_accounts.c.balance)
        ).scalar_one_or_none()
        if new_balance is None:
            raise InsufficientPoints("Saldo insuficiente para este canje")
        conn.execute(reward_redemptions.insert().values(
            id=redemption_id,
            customer_id=customer_id,
            reward_id=reward_id,
            points_spent=cost,
            status="redeemed",
            redeemed_at=now,
        ))
        conn.execute(loyalty_transactions.insert().values(
            id=_id(),
            customer_id=customer_id,
            points=-cost,
            transaction_type="redeem",
            reference_type="reward_redemption",
            reference_id=redemption_id,
            description=f"Canje: {reward['name']}",
            created_at=now,
        ))

    return {
        "redemption_id": redemption_id,
        "customer_id": customer_id,
        "reward_id": reward_id,
        "points_spent": cost,
        "balance": int(new_balance),
    }


def list_customer_redemptions(engine: Engine, customer_id: str) -> list[dict]:
    """Show the customer their redemption codes and fulfillment status."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                reward_redemptions.c.id,
                reward_redemptions.c.customer_id,
                reward_redemptions.c.reward_id,
                rewards.c.name.label("reward_name"),
                reward_redemptions.c.points_spent,
                reward_redemptions.c.status,
                reward_redemptions.c.redeemed_at,
            )
            .join(rewards, rewards.c.id == reward_redemptions.c.reward_id)
            .where(reward_redemptions.c.customer_id == customer_id)
            .order_by(reward_redemptions.c.redeemed_at.desc())
        ).mappings().all()
    return [dict(row) for row in rows]


def get_redemption_for_cashier(engine: Engine, redemption_id: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            select(
                reward_redemptions.c.id,
                reward_redemptions.c.customer_id,
                customers.c.full_name.label("customer_name"),
                rewards.c.name.label("reward_name"),
                reward_redemptions.c.points_spent,
                reward_redemptions.c.status,
                reward_redemptions.c.redeemed_at,
            )
            .join(customers, customers.c.id == reward_redemptions.c.customer_id)
            .join(rewards, rewards.c.id == reward_redemptions.c.reward_id)
            .where(reward_redemptions.c.id == redemption_id)
        ).mappings().first()
    if not row:
        raise RedemptionNotFound("Canje no encontrado")
    return dict(row)


def fulfill_redemption(engine: Engine, redemption_id: str) -> dict:
    """Mark a redemption as handed over exactly once; points were spent earlier."""
    now = _now()
    with engine.begin() as conn:
        changed = conn.execute(
            update(reward_redemptions)
            .where(
                reward_redemptions.c.id == redemption_id,
                reward_redemptions.c.status == "redeemed",
            )
            .values(status="fulfilled")
        ).rowcount
        if not changed:
            exists = conn.execute(
                select(reward_redemptions.c.status).where(reward_redemptions.c.id == redemption_id)
            ).scalar_one_or_none()
            if exists is None:
                raise RedemptionNotFound("Canje no encontrado")
            raise CustomerError("Este canje ya fue entregado")
        customer_id = conn.execute(
            select(reward_redemptions.c.customer_id).where(reward_redemptions.c.id == redemption_id)
        ).scalar_one()
        conn.execute(customer_events.insert().values(
            id=_id(), customer_id=customer_id, event_type="reward_fulfilled",
            occurred_at=now, source="cashier", reference_id=redemption_id,
            created_at=now,
        ))
    return get_redemption_for_cashier(engine, redemption_id)


def list_customer_purchases(engine: Engine, customer_id: str, limit: int = 20) -> list[dict]:
    """Return recent purchases with their items and actual loyalty credits."""
    with engine.connect() as conn:
        if not conn.execute(select(customers.c.id).where(customers.c.id == customer_id)).first():
            raise CustomerNotFound(customer_id)
        rows = conn.execute(
            select(purchases.c.id, purchases.c.customer_id, purchases.c.purchased_at,
                   purchases.c.total_amount, purchases.c.currency, purchases.c.external_reference)
            .where(purchases.c.customer_id == customer_id)
            .order_by(purchases.c.purchased_at.desc(), purchases.c.created_at.desc(), purchases.c.id.desc())
            .limit(limit)
        ).mappings().all()
        if not rows:
            return []

        ids = [row["id"] for row in rows]
        items_by_purchase = {purchase_id: [] for purchase_id in ids}
        for item in conn.execute(
            select(purchase_items.c.purchase_id, purchase_items.c.product_name,
                   purchase_items.c.quantity, purchase_items.c.line_total)
            .where(purchase_items.c.purchase_id.in_(ids))
            .order_by(purchase_items.c.id)
        ).mappings():
            items_by_purchase[item["purchase_id"]].append({
                "product_name": item["product_name"],
                "quantity": item["quantity"],
                "line_total": item["line_total"],
            })

        points_by_purchase = dict(conn.execute(
            select(loyalty_transactions.c.reference_id, loyalty_transactions.c.points)
            .where(loyalty_transactions.c.customer_id == customer_id,
                   loyalty_transactions.c.transaction_type == "earn",
                   loyalty_transactions.c.reference_type == "purchase",
                   loyalty_transactions.c.reference_id.in_(ids))
        ).all())
        return [
            {**dict(row), "points_earned": points_by_purchase.get(row["id"], 0),
             "items": items_by_purchase[row["id"]]}
            for row in rows
        ]


def record_purchase(
    engine: Engine,
    customer_id: str,
    total_amount: Decimal | float | str,
    items: list[dict],
    store_id: str | None = None,
    purchased_at: datetime | None = None,
    source: str = "app",
    external_reference: str | None = None,
    points_per_mxn: int = 1,
) -> dict:
    """Registra una compra y sus productos, y opcionalmente acredita puntos.

    external_reference permite que una misma compra enviada dos veces por la
    caja no se registre dos veces. Si ya existe, se devuelve la compra existente.
    """
    if not items:
        raise CustomerError("La compra debe tener al menos un producto")
    raw_amount = Decimal(str(total_amount))
    amount = raw_amount.quantize(Decimal("0.01"))
    if raw_amount < 0 or raw_amount != amount:
        raise CustomerError("El importe debe ser válido y tener como máximo dos decimales")
    if points_per_mxn < 0:
        raise CustomerError("points_per_mxn no puede ser negativo")

    prepared_items = []
    items_total = Decimal("0.00")
    for item in items:
        name = item["product_name"].strip()
        quantity = Decimal(str(item["quantity"]))
        unit_price = Decimal(str(item["unit_price"]))
        if not name or quantity <= 0 or unit_price < 0 or unit_price != unit_price.quantize(Decimal("0.01")):
            raise CustomerError("Nombre, cantidad y precio de producto deben ser válidos")
        expected_total = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        supplied_total = item.get("line_total")
        if supplied_total is not None and Decimal(str(supplied_total)) != expected_total:
            raise CustomerError("El subtotal del producto no coincide con cantidad y precio")
        prepared_items.append({
            "product_name": name, "product_code": item.get("product_code"),
            "quantity": quantity, "unit_price": unit_price, "line_total": expected_total,
        })
        items_total += expected_total
    if amount != items_total:
        raise CustomerError("El total del ticket no coincide con la suma de productos")

    purchased_at = purchased_at or _now()
    now = _now()
    purchase_id = _id()

    with engine.begin() as conn:
        if not conn.execute(select(customers.c.id).where(customers.c.id == customer_id)).first():
            raise CustomerNotFound(customer_id)

        if external_reference:
            existing = conn.execute(
                select(purchases).where(
                    purchases.c.source == source,
                    purchases.c.external_reference == external_reference,
                )
            ).mappings().first()
            if existing:
                if existing["customer_id"] != customer_id:
                    raise CustomerError("La referencia de compra pertenece a otro cliente")
                existing_items = conn.execute(
                    select(purchase_items.c.product_name, purchase_items.c.product_code,
                           purchase_items.c.quantity, purchase_items.c.unit_price,
                           purchase_items.c.line_total)
                    .where(purchase_items.c.purchase_id == existing["id"])
                ).mappings().all()
                fields = ("product_name", "product_code", "quantity", "unit_price", "line_total")
                stored = Counter(tuple(item[field] for field in fields) for item in existing_items)
                incoming = Counter(tuple(item[field] for field in fields) for item in prepared_items)
                if existing["total_amount"] != amount or stored != incoming:
                    raise CustomerError("El número de ticket ya existe con otros datos")
                points_row = conn.execute(
                    select(loyalty_transactions.c.points).where(
                        loyalty_transactions.c.customer_id == customer_id,
                        loyalty_transactions.c.transaction_type == "earn",
                        loyalty_transactions.c.reference_type == "purchase",
                        loyalty_transactions.c.reference_id == existing["id"],
                    )
                ).first()
                return {
                    "id": existing["id"],
                    "customer_id": existing["customer_id"],
                    "total_amount": existing["total_amount"],
                    "points_earned": int(points_row.points) if points_row else 0,
                }

        conn.execute(purchases.insert().values(
            id=purchase_id,
            customer_id=customer_id,
            store_id=store_id,
            purchased_at=purchased_at,
            total_amount=amount,
            currency="MXN",
            source=source,
            external_reference=external_reference,
            created_at=now,
        ))

        for item in prepared_items:
            conn.execute(purchase_items.insert().values(
                id=_id(),
                purchase_id=purchase_id,
                product_name=item["product_name"],
                product_code=item["product_code"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                line_total=item["line_total"],
            ))

        points = int(amount) * points_per_mxn
        if points:
            conn.execute(loyalty_transactions.insert().values(
                id=_id(),
                customer_id=customer_id,
                points=points,
                transaction_type="earn",
                reference_type="purchase",
                reference_id=purchase_id,
                description="Puntos por compra",
                created_at=now,
            ))
            account = conn.execute(
                select(loyalty_accounts.c.balance).where(loyalty_accounts.c.customer_id == customer_id)
            ).first()
            if not account:
                raise CustomerError("El cliente no tiene cuenta de fidelidad")
            conn.execute(
                update(loyalty_accounts)
                .where(loyalty_accounts.c.customer_id == customer_id)
                .values(balance=int(account.balance) + points, updated_at=now)
            )

    return {
        "id": purchase_id,
        "customer_id": customer_id,
        "total_amount": amount,
        "points_earned": points,
    }


def record_event(
    engine: Engine,
    customer_id: str,
    event_type: str,
    source: str = "app",
    reference_id: str | None = None,
    value: Decimal | float | str | None = None,
    text_value: str | None = None,
    occurred_at: datetime | None = None,
) -> str:
    """Guarda un evento de comportamiento para marketing y analítica futura."""
    event_id = _id()
    now = _now()
    with engine.begin() as conn:
        if not conn.execute(select(customers.c.id).where(customers.c.id == customer_id)).first():
            raise CustomerNotFound(customer_id)
        conn.execute(customer_events.insert().values(
            id=event_id,
            customer_id=customer_id,
            event_type=event_type,
            occurred_at=occurred_at or now,
            source=source,
            reference_id=reference_id,
            value=Decimal(str(value)) if value is not None else None,
            text_value=text_value,
            created_at=now,
        ))
    return event_id
