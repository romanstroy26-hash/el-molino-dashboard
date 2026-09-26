"""Esquema de clientes, fidelidad y marketing para El Molino.

El esquema es independiente de Wansoft y usa solo tipos portables entre
SQLite y PostgreSQL. Los IDs se guardan como TEXT para mantener la misma
estructura en desarrollo local y en la base cloud.
"""

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, MetaData, Numeric,
    String, Table, Text, UniqueConstraint, Index,
)

customer_metadata = MetaData()

customers = Table(
    "customers", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("full_name", String(160), nullable=False),
    Column("phone", String(40)),
    Column("email", String(254)),
    Column("status", String(20), nullable=False, default="active"),
    Column("marketing_consent", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    UniqueConstraint("phone", name="uq_customers_phone"),
    UniqueConstraint("email", name="uq_customers_email"),
)

customer_profiles = Table(
    "customer_profiles", customer_metadata,
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True),
    Column("birth_date", String(10)),
    Column("preferred_store_id", String(36)),
    Column("preferred_channel", String(30)),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

customer_devices = Table(
    "customer_devices", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
    Column("platform", String(20)),
    Column("push_token", Text),
    Column("created_at", DateTime, nullable=False),
    Column("last_seen_at", DateTime),
    UniqueConstraint("push_token", name="uq_customer_devices_push_token"),
)

stores = Table(
    "stores", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("external_code", String(80)),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("external_code", name="uq_stores_external_code"),
)

customer_visits = Table(
    "customer_visits", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
    Column("store_id", String(36), ForeignKey("stores.id")),
    Column("visited_at", DateTime, nullable=False),
    Column("source", String(30), nullable=False, default="app"),
    Column("external_reference", String(120)),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("source", "external_reference", name="uq_customer_visits_external_ref"),
)

purchases = Table(
    "purchases", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
    Column("visit_id", String(36), ForeignKey("customer_visits.id")),
    Column("store_id", String(36), ForeignKey("stores.id")),
    Column("purchased_at", DateTime, nullable=False),
    Column("total_amount", Numeric(12, 2), nullable=False),
    Column("currency", String(3), nullable=False, default="MXN"),
    Column("source", String(30), nullable=False, default="app"),
    Column("external_reference", String(120)),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("source", "external_reference", name="uq_purchases_external_ref"),
)

purchase_items = Table(
    "purchase_items", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("purchase_id", String(36), ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False),
    Column("product_name", String(180), nullable=False),
    Column("product_code", String(80)),
    Column("quantity", Numeric(12, 3), nullable=False),
    Column("unit_price", Numeric(12, 2), nullable=False),
    Column("line_total", Numeric(12, 2), nullable=False),
)

customer_events = Table(
    "customer_events", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
    Column("event_type", String(60), nullable=False),
    Column("occurred_at", DateTime, nullable=False),
    Column("source", String(30), nullable=False, default="app"),
    Column("reference_id", String(120)),
    Column("value", Numeric(12, 2)),
    Column("text_value", Text),
    Column("created_at", DateTime, nullable=False),
)

login_challenges = Table(
    "login_challenges", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("phone", String(40), nullable=False),
    Column("code_hash", String(64), nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Column("used_at", DateTime),
    Column("attempts", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False),
)

loyalty_accounts = Table(
    "loyalty_accounts", customer_metadata,
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True),
    Column("balance", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

loyalty_transactions = Table(
    "loyalty_transactions", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
    Column("points", Integer, nullable=False),
    Column("transaction_type", String(30), nullable=False),
    Column("reference_type", String(40)),
    Column("reference_id", String(120)),
    Column("description", String(255)),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("transaction_type", "reference_type", "reference_id", name="uq_loyalty_reference"),
)

rewards = Table(
    "rewards", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("description", Text),
    Column("points_cost", Integer, nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

reward_redemptions = Table(
    "reward_redemptions", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
    Column("reward_id", String(36), ForeignKey("rewards.id"), nullable=False),
    Column("points_spent", Integer, nullable=False),
    Column("status", String(20), nullable=False, default="redeemed"),
    Column("redeemed_at", DateTime, nullable=False),
)

campaigns = Table(
    "campaigns", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("channel", String(30), nullable=False),
    Column("status", String(20), nullable=False, default="draft"),
    Column("starts_at", DateTime),
    Column("ends_at", DateTime),
    Column("message", Text),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

campaign_recipients = Table(
    "campaign_recipients", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("campaign_id", String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(20), nullable=False, default="pending"),
    Column("scheduled_at", DateTime),
    Column("sent_at", DateTime),
    UniqueConstraint("campaign_id", "customer_id", name="uq_campaign_recipient"),
)

campaign_events = Table(
    "campaign_events", customer_metadata,
    Column("id", String(36), primary_key=True),
    Column("campaign_id", String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("customer_id", String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
    Column("event_type", String(30), nullable=False),
    Column("occurred_at", DateTime, nullable=False),
)

Index("ix_customers_status", customers.c.status)
Index("ix_customer_visits_customer_date", customer_visits.c.customer_id, customer_visits.c.visited_at)
Index("ix_purchases_customer_date", purchases.c.customer_id, purchases.c.purchased_at)
Index("ix_purchase_items_purchase", purchase_items.c.purchase_id)
Index("ix_customer_events_customer_date", customer_events.c.customer_id, customer_events.c.occurred_at)
Index("ix_login_challenges_phone_created", login_challenges.c.phone, login_challenges.c.created_at)
Index("ix_loyalty_transactions_customer_date", loyalty_transactions.c.customer_id, loyalty_transactions.c.created_at)
Index("ix_campaign_recipients_customer", campaign_recipients.c.customer_id)
Index("ix_campaign_events_customer_date", campaign_events.c.customer_id, campaign_events.c.occurred_at)
