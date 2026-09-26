from datetime import datetime
import re
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from api import create_app
from customer_schema import customer_events, customer_metadata, purchase_items, rewards
from sqlalchemy import func, select


def test_production_requires_persistent_config(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_TOKEN_SECRET"):
        create_app()


def make_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    customer_metadata.create_all(engine)
    return TestClient(create_app(engine, expose_debug_code=True, token_secret="test-secret", admin_api_key="admin-test-key", cashier_api_key="cashier-test-key"))


def create_customer(client: TestClient, marketing_consent: bool = False) -> dict:
    response = client.post("/customers", json={"full_name": "Ana", "phone": "555-123", "marketing_consent": marketing_consent}, headers=cashier_headers())
    assert response.status_code == 201
    return response.json()


def auth_headers(client: TestClient, phone: str) -> dict:
    requested = client.post("/auth/request-code", json={"phone": phone})
    assert requested.status_code == 202
    verified = client.post("/auth/verify-code", json={"phone": phone, "code": requested.json()["debug_code"]})
    assert verified.status_code == 200
    return {"Authorization": f"Bearer {verified.json()['access_token']}"}


def cashier_headers() -> dict:
    return {"X-Cashier-Key": "cashier-test-key"}


def test_customer_registration_retrieval_and_points():
    client = make_client()
    customer = create_customer(client)
    headers = auth_headers(client, "555-123")
    assert client.get(f"/customers/{customer['id']}", headers=headers).json()["full_name"] == "Ana"
    assert client.get(f"/customers/{customer['id']}/points", headers=headers).json() == {"customer_id": customer["id"], "balance": 0}
    assert client.get("/customers/missing", headers=headers).status_code == 403


def test_customer_purchase_history_is_private_and_shows_items_and_points():
    client = make_client()
    customer = create_customer(client)
    owner_headers = auth_headers(client, "555-123")
    url = f"/customers/{customer['id']}/purchases"
    assert client.get(url, headers=owner_headers).json() == []

    for reference, day, amount, items in [
        ("history-older", "2026-09-20T15:00:00", "42.50", [{"product_name": "Café", "quantity": 1, "unit_price": "42.50"}]),
        ("history-newer", "2026-09-21T15:00:00", "70.00", [{"product_name": "Latte", "quantity": 1, "unit_price": "42.50"}, {"product_name": "Galleta", "quantity": 2, "unit_price": "13.75"}]),
    ]:
        response = client.post(url, json={"total_amount": amount, "external_reference": reference, "purchased_at": day, "items": items}, headers=cashier_headers())
        assert response.status_code == 201

    history = client.get(url, headers=owner_headers)
    assert history.status_code == 200
    assert [entry["total_amount"] for entry in history.json()] == ["70.00", "42.50"]
    assert history.json()[0]["points_earned"] == 70
    assert sorted((item["product_name"], item["quantity"]) for item in history.json()[0]["items"]) == [("Galleta", "2.000"), ("Latte", "1.000")]
    assert len(client.get(f"{url}?limit=1", headers=owner_headers).json()) == 1
    assert client.get(f"{url}?limit=0", headers=owner_headers).status_code == 422
    cashier_url = f"/cashier/customers/{customer['id']}/purchases"
    assert client.get(cashier_url).status_code == 401
    assert client.get(cashier_url, headers=owner_headers).status_code == 401
    cashier_history = client.get(f"{cashier_url}?limit=1", headers=cashier_headers())
    assert cashier_history.status_code == 200
    assert len(cashier_history.json()) == 1
    assert cashier_history.json()[0]["external_reference"] == "history-newer"
    assert client.get(f"{cashier_url}?limit=21", headers=cashier_headers()).status_code == 422
    assert client.get("/cashier/customers/missing/purchases", headers=cashier_headers()).status_code == 404

    other = client.post("/customers", json={"full_name": "Luis", "phone": "555-456"}, headers=cashier_headers()).json()
    other_headers = auth_headers(client, "555-456")
    assert client.get(url, headers=other_headers).status_code == 403
    assert client.get(f"/customers/{other['id']}/purchases", headers=other_headers).json() == []
    assert client.get(f"/cashier/customers/{other['id']}/purchases", headers=cashier_headers()).json() == []
    assert client.get(url).status_code == 401


def test_new_customer_registers_only_after_phone_code():
    client = make_client()
    assert client.post("/customers", json={"full_name": "Ana", "phone": "555-789"}).status_code == 401
    requested = client.post("/auth/register/request-code", json={"phone": "555-789"})
    assert requested.status_code == 202
    code = requested.json()["debug_code"]
    repeated = client.post("/auth/register/request-code", json={"phone": "555-789"})
    assert repeated.status_code == 202
    assert "debug_code" not in repeated.json()
    invalid = client.post("/auth/register/verify-code", json={"phone": "555-789", "code": "999999" if code != "999999" else "888888", "full_name": "Ana"})
    assert invalid.status_code == 401
    registered = client.post("/auth/register/verify-code", json={"phone": "555-789", "code": code, "full_name": "Ana", "marketing_consent": True})
    assert registered.status_code == 201
    customer = registered.json()["customer"]
    assert customer["phone"] == "555-789" and customer["marketing_consent"] is True
    existing = client.post("/auth/register/request-code", json={"phone": "555-789"})
    assert existing.status_code == 202
    assert existing.json() == repeated.json()
    headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    assert client.get(f"/customers/{customer['id']}", headers=headers).status_code == 200
    assert client.post("/auth/register/verify-code", json={"phone": "555-789", "code": code, "full_name": "Ana"}).status_code == 401


def test_login_code_locks_after_five_wrong_attempts():
    client = make_client()
    create_customer(client)
    requested = client.post("/auth/request-code", json={"phone": "555-123"})
    repeated = client.post("/auth/request-code", json={"phone": "555-123"})
    unknown = client.post("/auth/request-code", json={"phone": "555-000"})
    assert repeated.status_code == unknown.status_code == 202
    assert repeated.json() == unknown.json()
    code = requested.json()["debug_code"]
    wrong = "999999" if code != "999999" else "888888"
    for _ in range(5):
        assert client.post("/auth/verify-code", json={"phone": "555-123", "code": wrong}).status_code == 401
    assert client.post("/auth/verify-code", json={"phone": "555-123", "code": code}).status_code == 401


def test_labsmobile_registration_uses_sms_and_canonical_phone(monkeypatch):
    sent = []

    class Accepted:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "0"}

    def fake_post(url, *, auth, json, timeout):
        sent.append((url, auth, json, timeout))
        return Accepted()

    monkeypatch.setenv("LABSMOBILE_USERNAME", "test-user")
    monkeypatch.setenv("LABSMOBILE_API_TOKEN", "test-token")
    monkeypatch.setenv("LABSMOBILE_TEST_MODE", "1")
    monkeypatch.setattr("sms_provider.httpx.post", fake_post)
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    customer_metadata.create_all(engine)
    client = TestClient(create_app(engine, token_secret="test-secret"))

    requested = client.post("/auth/register/request-code", json={"phone": "444 123 4567"})
    assert requested.status_code == 202
    assert "debug_code" not in requested.json()
    assert sent[0][2]["recipient"] == [{"msisdn": "524441234567"}]
    assert sent[0][2]["test"] == 1
    code = re.search(r"\b\d{6}\b", sent[0][2]["message"]).group()
    verified = client.post("/auth/register/verify-code", json={"phone": "+52 444 123 4567", "code": code, "full_name": "Ana"})
    assert verified.status_code == 201
    assert verified.json()["customer"]["phone"] == "+524441234567"


def test_labsmobile_rejection_does_not_expose_provider_details(monkeypatch):
    class Rejected:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "35", "message": "Account has no credit"}

    monkeypatch.setenv("LABSMOBILE_USERNAME", "test-user")
    monkeypatch.setenv("LABSMOBILE_API_TOKEN", "test-token")
    monkeypatch.setattr("sms_provider.httpx.post", lambda *args, **kwargs: Rejected())
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    customer_metadata.create_all(engine)
    client = TestClient(create_app(engine, token_secret="test-secret"))

    response = client.post("/auth/register/request-code", json={"phone": "4441234567"})
    assert response.status_code == 202
    assert "credit" not in response.text.lower()
    assert "test-token" not in response.text


def test_customer_app_is_served():
    client = make_client()
    assert "EL MOLINO" in client.get("/").text
    assert "Tu perfil" in client.get("/").text
    assert "Tus compras" in client.get("/").text
    assert client.get("/manifest.webmanifest").status_code == 200
    staff = client.get("/staff.html")
    assert "Panel del equipo" in staff.text
    assert 'href="./styles.css"' in staff.text
    assert 'href="./staff.css"' in staff.text
    assert 'src="./staff.js"' in staff.text
    assert client.get("/styles.css").headers["content-type"].startswith("text/css")
    assert client.get("/staff.css").headers["content-type"].startswith("text/css")
    assert client.get("/staff.js").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


def test_admin_can_create_reward_and_targeted_campaign():
    client = make_client()
    customer = create_customer(client, marketing_consent=True)
    customer_headers = auth_headers(client, "555-123")
    admin_headers = {"X-Admin-Key": "admin-test-key"}
    reward = client.post("/admin/rewards", json={"name": "Galleta gratis", "points_cost": 30}, headers=admin_headers)
    assert reward.status_code == 201
    campaign = client.post(
        "/admin/campaigns",
        json={"name": "Bienvenida", "channel": "push", "message": "Tenemos algo para ti", "customer_ids": [customer["id"]]},
        headers=admin_headers,
    )
    assert campaign.status_code == 201
    assert campaign.json()["status"] == "draft"
    assert client.get(f"/customers/{customer['id']}/campaigns", headers=customer_headers).json() == []
    assert client.post(f"/admin/campaigns/{campaign.json()['id']}/activate", headers=admin_headers).status_code == 200
    campaigns = client.get(f"/customers/{customer['id']}/campaigns", headers=customer_headers)
    assert campaigns.status_code == 200
    assert campaigns.json()[0]["name"] == "Bienvenida"
    assert client.post("/admin/rewards", json={"name": "x", "points_cost": 1}).status_code == 401


def test_admin_customer_insights_uses_purchase_history():
    client = make_client()
    customer = create_customer(client)
    customer_headers = auth_headers(client, "555-123")
    client.post(
        f"/customers/{customer['id']}/purchases",
        json={"total_amount": "150", "external_reference": "ticket-insight", "items": [{"product_name": "Cappuccino", "quantity": 2, "unit_price": "75"}]},
        headers=cashier_headers(),
    )
    response = client.get(f"/admin/customers/{customer['id']}/insights", headers={"X-Admin-Key": "admin-test-key"})
    assert response.status_code == 200
    assert response.json() == {
        "customer_id": customer["id"], "full_name": "Ana", "purchase_count": 1,
        "total_spend": 150.0, "average_ticket": 150.0, "last_purchase_at": response.json()["last_purchase_at"],
        "days_since_last_purchase": 0, "favorite_product": "Cappuccino", "favorite_product_quantity": 2.0,
        "points_balance": 150, "segment": "active",
    }


def test_admin_can_build_audience_and_campaign_from_segment():
    client = make_client()
    customer = create_customer(client, marketing_consent=True)
    headers = {"X-Admin-Key": "admin-test-key"}
    audience = client.get("/admin/audiences?segment=new", headers=headers)
    assert audience.status_code == 200
    assert audience.json()[0]["customer_id"] == customer["id"]
    campaign = client.post(
        "/admin/campaigns/by-segment",
        json={"name": "Bienvenida", "channel": "push", "segment": "new", "message": "Tu primer reward te espera"},
        headers=headers,
    )
    assert campaign.status_code == 201
    assert campaign.json()["recipient_count"] == 1


def test_campaign_interactions_are_visible_in_analytics():
    client = make_client()
    customer = create_customer(client, marketing_consent=True)
    customer_headers = auth_headers(client, "555-123")
    admin_headers = {"X-Admin-Key": "admin-test-key"}
    campaign = client.post(
        "/admin/campaigns",
        json={"name": "Café", "channel": "push", "customer_ids": [customer["id"]]}, headers=admin_headers,
    ).json()
    assert client.post(f"/admin/campaigns/{campaign['id']}/activate", headers=admin_headers).json()["status"] == "active"
    assert client.post(f"/customers/{customer['id']}/campaigns/{campaign['id']}/events", json={"event_type": "opened"}, headers=customer_headers).status_code == 201
    assert client.post(f"/customers/{customer['id']}/campaigns/{campaign['id']}/events", json={"event_type": "clicked"}, headers=customer_headers).status_code == 201
    analytics = client.get(f"/admin/campaigns/{campaign['id']}/analytics", headers=admin_headers).json()
    assert analytics["recipient_count"] == analytics["opened_count"] == analytics["clicked_count"] == 1


def test_campaign_draft_and_marketing_consent_are_enforced():
    client = make_client()
    customer = create_customer(client, marketing_consent=True)
    customer_headers = auth_headers(client, "555-123")
    admin_headers = {"X-Admin-Key": "admin-test-key"}
    campaign = client.post(
        "/admin/campaigns",
        json={"name": "Oferta", "channel": "push", "customer_ids": [customer["id"]]},
        headers=admin_headers,
    ).json()
    assert campaign["status"] == "draft"
    assert client.get("/admin/campaigns", headers=admin_headers).json()[0]["recipient_count"] == 1
    assert client.post(f"/customers/{customer['id']}/campaigns/{campaign['id']}/events", json={"event_type": "opened"}, headers=customer_headers).status_code == 400
    client.patch(f"/customers/{customer['id']}", json={"marketing_consent": False}, headers=customer_headers)
    assert client.post(f"/admin/campaigns/{campaign['id']}/activate", headers=admin_headers).status_code == 400
    assert client.get(f"/customers/{customer['id']}/campaigns", headers=customer_headers).json() == []
    assert client.post(
        "/admin/campaigns", json={"name": "Otra", "channel": "sms", "customer_ids": [customer["id"]]}, headers=admin_headers,
    ).status_code == 400
    client.patch(f"/customers/{customer['id']}", json={"marketing_consent": True}, headers=customer_headers)
    assert client.post(f"/admin/campaigns/{campaign['id']}/activate", headers=admin_headers).status_code == 200
    assert len(client.get(f"/customers/{customer['id']}/campaigns", headers=customer_headers).json()) == 1
    client.patch(f"/customers/{customer['id']}", json={"marketing_consent": False}, headers=customer_headers)
    assert client.get(f"/customers/{customer['id']}/campaigns", headers=customer_headers).json() == []
    assert client.post(f"/customers/{customer['id']}/campaigns/{campaign['id']}/events", json={"event_type": "clicked"}, headers=customer_headers).status_code == 400


def test_admin_receives_explainable_next_best_actions():
    client = make_client()
    customer = create_customer(client)
    response = client.get("/admin/next-best-actions", headers={"X-Admin-Key": "admin-test-key"})
    assert response.status_code == 200
    assert response.json() == [{
        "customer_id": customer["id"], "full_name": "Ana", "segment": "new",
        "action_type": "welcome", "priority": "medium", "reason": "Aún no tiene compras registradas.",
        "suggested_message": "Bienvenido a El Molino Club. Tu primera visita suma puntos.",
    }]


def test_customer_can_manage_own_profile_and_marketing_consent():
    client = make_client()
    customer = create_customer(client)
    headers = auth_headers(client, "555-123")
    updated = client.patch(
        f"/customers/{customer['id']}", json={"full_name": "Ana López", "marketing_consent": True}, headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["marketing_consent"] is True
    profile = client.patch(
        f"/customers/{customer['id']}/profile",
        json={"birth_date": "1990-05-20", "preferred_channel": "whatsapp"}, headers=headers,
    )
    assert profile.status_code == 200
    assert profile.json()["preferred_channel"] == "whatsapp"


def test_customer_can_register_and_refresh_own_device():
    client = make_client()
    customer = create_customer(client)
    headers = auth_headers(client, "555-123")
    first = client.post(
        f"/customers/{customer['id']}/devices", json={"platform": "web", "push_token": "device-token"}, headers=headers,
    )
    second = client.post(
        f"/customers/{customer['id']}/devices", json={"platform": "web", "push_token": "device-token"}, headers=headers,
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_purchase_is_idempotent_and_records_event():
    client = make_client()
    customer = create_customer(client)
    headers = auth_headers(client, "555-123")
    body = {
        "total_amount": "185.50",
        "external_reference": "ticket-1",
        "items": [{"product_name": "Latte", "quantity": "1", "unit_price": "185.50"}],
    }
    first = client.post(f"/customers/{customer['id']}/purchases", json=body, headers=cashier_headers())
    second = client.post(f"/customers/{customer['id']}/purchases", json=body, headers=cashier_headers())
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert client.get(f"/customers/{customer['id']}/points", headers=headers).json()["balance"] == 185
    event = client.post(f"/customers/{customer['id']}/events", json={"event_type": "app_open"}, headers=headers)
    assert event.status_code == 201 and event.json()["id"]


def test_purchase_rejects_inconsistent_totals_without_earning_points():
    client = make_client()
    customer = create_customer(client)
    owner_headers = auth_headers(client, "555-123")
    path = f"/customers/{customer['id']}/purchases"
    body = {"total_amount": "70.00", "external_reference": "ticket-validated", "items": [
        {"product_name": "Café", "quantity": 1, "unit_price": "42.50", "line_total": "42.50"},
        {"product_name": "Pan dulce", "quantity": 2, "unit_price": "13.75", "line_total": "27.50"},
    ]}
    inflated = {**body, "total_amount": "170.00"}
    wrong_line = {**body, "items": [body["items"][0], {**body["items"][1], "line_total": "127.50"}]}
    assert client.post(path, json=inflated, headers=cashier_headers()).status_code == 400
    assert client.post(path, json=wrong_line, headers=cashier_headers()).status_code == 400
    assert client.get(f"/customers/{customer['id']}/points", headers=owner_headers).json()["balance"] == 0
    assert client.get(path, headers=owner_headers).json() == []
    valid = client.post(path, json=body, headers=cashier_headers())
    assert valid.status_code == 201
    assert valid.json()["points_earned"] == 70
    changed = {**body, "items": [{"product_name": "Otro producto", "quantity": 1, "unit_price": "70.00"}]}
    assert client.post(path, json=changed, headers=cashier_headers()).status_code == 400
    repeated = client.post(path, json=body, headers=cashier_headers())
    assert repeated.status_code == 201 and repeated.json()["id"] == valid.json()["id"]
    fractional = client.post(path, json={"total_amount": "0.01", "external_reference": "ticket-fractional", "items": [
        {"product_name": "Ingrediente", "quantity": "0.001", "unit_price": "5.00", "line_total": "0.01"},
    ]}, headers=cashier_headers())
    assert fractional.status_code == 201
    assert client.get(f"/customers/{customer['id']}/points", headers=owner_headers).json()["balance"] == 70


def test_rewards_and_redemption():
    client = make_client()
    customer = create_customer(client)
    headers = auth_headers(client, "555-123")
    engine = client.app.state.engine
    with engine.begin() as conn:
        now = datetime.utcnow()
        conn.execute(rewards.insert().values(id="reward-1", name="Café gratis", description="", points_cost=60, active=True, created_at=now, updated_at=now))
    assert client.get(f"/customers/{customer['id']}/rewards", headers=headers).json()[0]["id"] == "reward-1"
    client.post(f"/customers/{customer['id']}/purchases", json={"total_amount": "100", "external_reference": "ticket-reward", "items": [{"product_name": "Latte", "quantity": 1, "unit_price": "100"}]}, headers=cashier_headers())
    redeemed = client.post(f"/customers/{customer['id']}/rewards/reward-1/redeem", headers=headers)
    assert redeemed.status_code == 201
    assert redeemed.json()["balance"] == 40


def test_purchase_requires_cashier_key_and_rejects_client_controlled_points():
    client = make_client()
    customer = create_customer(client)
    customer_headers = auth_headers(client, "555-123")
    path = f"/customers/{customer['id']}/purchases"
    body = {"total_amount": "10", "external_reference": "ticket-secure", "items": [{"product_name": "Café", "quantity": 1, "unit_price": "10"}]}

    assert client.post(path, json=body, headers=customer_headers).status_code == 401
    assert client.post(path, json=body, headers={"X-Admin-Key": "admin-test-key"}).status_code == 401
    assert client.post(path, json={**body, "points_per_mxn": 100}, headers=cashier_headers()).status_code == 422
    assert client.post(path, json={**body, "source": "app"}, headers=cashier_headers()).status_code == 422
    assert client.get(f"/customers/{customer['id']}/points", headers=customer_headers).json()["balance"] == 0
    assert client.post(path, json=body, headers=cashier_headers()).status_code == 201
    assert client.get(f"/customers/{customer['id']}/points", headers=customer_headers).json()["balance"] == 10


def test_cashier_ticket_cannot_be_reassigned_to_another_customer():
    client = make_client()
    first = create_customer(client)
    second = client.post("/customers", json={"full_name": "Bea", "phone": "555-456"}, headers=cashier_headers()).json()
    body = {"total_amount": "10", "external_reference": "ticket-shared", "items": [{"product_name": "Café", "quantity": 1, "unit_price": "10"}]}
    assert client.post(f"/customers/{first['id']}/purchases", json=body, headers=cashier_headers()).status_code == 201
    assert client.post(f"/customers/{second['id']}/purchases", json=body, headers=cashier_headers()).status_code == 400


def test_cashier_can_find_customer_without_exposing_full_profile():
    client = make_client()
    customer = create_customer(client)
    path = "/cashier/customers?phone=555-123"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Admin-Key": "admin-test-key"}).status_code == 401
    response = client.get(path, headers=cashier_headers())
    assert response.status_code == 200
    assert response.json() == {"id": customer["id"], "full_name": "Ana", "points_balance": 0}
    assert client.get("/cashier/customers?phone=unknown", headers=cashier_headers()).status_code == 404


def test_cashier_can_register_walk_in_and_credit_first_purchase():
    client = make_client()
    phone = "555 123 4567"
    assert client.get(f"/cashier/customers?phone={phone}", headers=cashier_headers()).status_code == 404
    created = client.post("/customers", json={"full_name": "Nuevo Cliente", "phone": phone, "marketing_consent": False}, headers=cashier_headers())
    assert created.status_code == 201
    customer = created.json()
    assert customer["phone"] == "+525551234567"
    assert customer["marketing_consent"] is False
    found = client.get("/cashier/customers?phone=%2B525551234567", headers=cashier_headers())
    assert found.status_code == 200
    assert found.json()["points_balance"] == 0
    ticket = client.post(
        f"/customers/{customer['id']}/purchases",
        json={"total_amount": "70.00", "external_reference": "first-ticket", "items": [
            {"product_name": "Café", "quantity": 1, "unit_price": "42.50", "line_total": "42.50"},
            {"product_name": "Pan dulce", "quantity": 2, "unit_price": "13.75", "line_total": "27.50"},
        ]},
        headers=cashier_headers(),
    )
    assert ticket.status_code == 201
    assert ticket.json()["points_earned"] == 70
    with client.app.state.engine.connect() as conn:
        lines = conn.execute(select(purchase_items.c.product_name).where(purchase_items.c.purchase_id == ticket.json()["id"])).scalars().all()
    assert set(lines) == {"Café", "Pan dulce"}
    assert client.get("/cashier/customers?phone=5551234567", headers=cashier_headers()).json()["points_balance"] == 70


def test_reward_handover_is_visible_to_customer_and_happens_once():
    client = make_client()
    customer = create_customer(client)
    owner_headers = auth_headers(client, "555-123")
    other = client.post("/customers", json={"full_name": "Bea", "phone": "555-456"}, headers=cashier_headers()).json()
    other_headers = auth_headers(client, "555-456")
    reward = client.post(
        "/admin/rewards", json={"name": "Café gratis", "points_cost": 60},
        headers={"X-Admin-Key": "admin-test-key"},
    ).json()
    client.post(
        f"/customers/{customer['id']}/purchases",
        json={"total_amount": "100", "external_reference": "ticket-handover", "items": [{"product_name": "Latte", "quantity": 1, "unit_price": "100"}]},
        headers=cashier_headers(),
    )
    redeemed = client.post(f"/customers/{customer['id']}/rewards/{reward['id']}/redeem", headers=owner_headers)
    assert redeemed.status_code == 201
    code = redeemed.json()["redemption_id"]
    customer_list = client.get(f"/customers/{customer['id']}/redemptions", headers=owner_headers)
    assert customer_list.json()[0]["id"] == code
    assert customer_list.json()[0]["status"] == "redeemed"
    assert client.get(f"/customers/{customer['id']}/redemptions", headers=other_headers).status_code == 403
    assert client.get(f"/customers/{other['id']}/redemptions", headers=other_headers).json() == []
    assert client.get(f"/cashier/redemptions/{code}").status_code == 401
    assert client.get(f"/cashier/redemptions/{code}", headers=cashier_headers()).json()["reward_name"] == "Café gratis"
    delivered = client.post(f"/cashier/redemptions/{code}/fulfill", headers=cashier_headers())
    assert delivered.status_code == 200
    assert delivered.json()["status"] == "fulfilled"
    assert client.post(f"/cashier/redemptions/{code}/fulfill", headers=cashier_headers()).status_code == 400
    with client.app.state.engine.connect() as conn:
        event_count = conn.execute(
            select(func.count()).select_from(customer_events).where(
                customer_events.c.event_type == "reward_fulfilled",
                customer_events.c.reference_id == code,
            )
        ).scalar_one()
    assert event_count == 1
    assert client.get(f"/customers/{customer['id']}/points", headers=owner_headers).json()["balance"] == 40
    assert client.get(f"/customers/{customer['id']}/redemptions", headers=owner_headers).json()[0]["status"] == "fulfilled"
    assert client.get("/cashier/redemptions/missing", headers=cashier_headers()).status_code == 404
