from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select

from customer_schema import customer_events, customer_metadata, rewards
from datetime import datetime

from customer_service import (
    CustomerError,
    InsufficientPoints,
    create_customer,
    earn_points,
    get_points_balance,
    record_event,
    record_purchase,
    redeem_reward,
)


def make_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    customer_metadata.create_all(engine)
    return engine


def test_create_customer_initializes_loyalty_account():
    engine = make_engine()
    customer = create_customer(engine, "Ana", phone="555-123")
    assert customer["full_name"] == "Ana"
    assert get_points_balance(engine, customer["id"]) == 0


def test_duplicate_phone_is_rejected():
    engine = make_engine()
    create_customer(engine, "Ana", phone="555-123")
    with pytest.raises(CustomerError):
        create_customer(engine, "Luis", phone="555-123")


def test_purchase_earns_points_and_is_idempotent():
    engine = make_engine()
    customer = create_customer(engine, "Ana")
    first = record_purchase(
        engine, customer["id"], Decimal("185.50"),
        [{"product_name": "Latte", "quantity": 1, "unit_price": Decimal("185.50")}],
        external_reference="ticket-1",
    )
    second = record_purchase(
        engine, customer["id"], Decimal("185.50"),
        [{"product_name": "Latte", "quantity": 1, "unit_price": Decimal("185.50")}],
        external_reference="ticket-1",
    )
    assert first["id"] == second["id"]
    assert get_points_balance(engine, customer["id"]) == 185


def test_redeem_reward_decreases_balance():
    engine = make_engine()
    customer = create_customer(engine, "Ana")
    earn_points(engine, customer["id"], 100)
    with engine.begin() as conn:
        conn.execute(rewards.insert().values(
            id="reward-1", name="Cafe gratis", description="", points_cost=60,
            active=True, created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))
    result = redeem_reward(engine, customer["id"], "reward-1")
    assert result["balance"] == 40
    assert get_points_balance(engine, customer["id"]) == 40


def test_redeem_without_points_fails():
    engine = make_engine()
    customer = create_customer(engine, "Ana")
    with engine.begin() as conn:
        now = datetime.utcnow()
        conn.execute(rewards.insert().values(
            id="reward-1", name="Cafe gratis", description="", points_cost=60,
            active=True, created_at=now, updated_at=now,
        ))
    with pytest.raises(InsufficientPoints):
        redeem_reward(engine, customer["id"], "reward-1")


def test_event_is_recorded():
    engine = make_engine()
    customer = create_customer(engine, "Ana")
    event_id = record_event(engine, customer["id"], "app_open")
    with engine.connect() as conn:
        row = conn.execute(
            select(customer_events).where(customer_events.c.id == event_id)
        ).first()
    assert row is not None
