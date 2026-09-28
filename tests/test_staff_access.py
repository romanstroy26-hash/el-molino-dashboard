"""Personal staff codes must identify, limit, and revoke individual workers."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from api import create_app
from customer_schema import customer_metadata
from staff_auth import staff_users


def client() -> TestClient:
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    customer_metadata.create_all(engine)
    return TestClient(create_app(engine, expose_debug_code=True, token_secret="test-secret",
                                 admin_api_key="admin-test-key", cashier_api_key="cashier-test-key"))


def test_personal_codes_permissions_and_audit():
    app = client()
    assert app.post("/staff/bootstrap", json={"full_name": "Owner", "permissions": []},
                    headers={"X-Admin-Key": "wrong"}).status_code == 401
    response = app.post("/staff/bootstrap", json={"full_name": "Owner", "permissions": []},
                        headers={"X-Admin-Key": "admin-test-key"})
    assert response.status_code == 201
    owner_code = response.json()["code"]
    assert len(owner_code.replace("-", "")) == 16
    assert app.post("/staff/bootstrap", json={"full_name": "Other", "permissions": []},
                    headers={"X-Admin-Key": "admin-test-key"}).status_code == 409
    assert app.get("/admin/audiences", headers={"X-Admin-Key": "admin-test-key"}).status_code == 401
    owner_token = app.post("/staff/login", json={"code": owner_code}).json()["session"]
    owner_headers = {"X-Staff-Session": owner_token}
    created = app.post("/staff/team", json={"full_name": "Ana", "permissions": ["cashier"]}, headers=owner_headers)
    assert created.status_code == 201
    employee = created.json()
    employee_id, employee_code = employee["user"]["id"], employee["code"]
    with app.app.state.engine.connect() as connection:
        row = connection.execute(select(staff_users).where(staff_users.c.id == employee_id)).first()
        assert employee_code not in str(row)
    employee_token = app.post("/staff/login", json={"code": employee_code}).json()["session"]
    employee_headers = {"X-Staff-Session": employee_token}
    assert app.get("/cashier/customers", params={"phone": "555123"}, headers=employee_headers).status_code == 404
    assert app.get("/admin/audiences", headers=employee_headers).status_code == 403
    assert app.get("/staff/team", headers=employee_headers).status_code == 403
    assert app.patch(f"/staff/team/{employee_id}", json={"permissions": ["cashier", "analytics"]},
                     headers=owner_headers).status_code == 200
    assert app.get("/admin/audiences", headers=employee_headers).status_code == 200
    assert app.get("/admin/campaigns", headers=employee_headers).status_code == 403
    assert app.post("/admin/rewards", json={"name": "Café", "points_cost": 10}, headers=employee_headers).status_code == 403
    actions = app.get("/staff/actions", headers=owner_headers).json()
    assert any(row["full_name"] == "Ana" and row["action"].startswith("GET /admin/audiences") for row in actions)
    assert app.patch(f"/staff/team/{employee_id}", json={"active": False}, headers=owner_headers).status_code == 200
    assert app.get("/staff/me", headers=employee_headers).status_code == 401
    assert app.post("/staff/login", json={"code": employee_code}).status_code == 401
    assert app.patch(f"/staff/team/{employee_id}", json={"active": True}, headers=owner_headers).status_code == 200
    new_code = app.post(f"/staff/team/{employee_id}/reset-code", headers=owner_headers).json()["code"]
    assert app.post("/staff/login", json={"code": employee_code}).status_code == 401
    assert app.post("/staff/login", json={"code": new_code}).status_code == 200


def test_owner_recovery_revokes_previous_session():
    app = client()
    code = app.post("/staff/bootstrap", json={"full_name": "Owner"}, headers={"X-Admin-Key": "admin-test-key"}).json()["code"]
    token = app.post("/staff/login", json={"code": code}).json()["session"]
    assert app.post("/staff/recover-owner", headers={"X-Admin-Key": "wrong"}).status_code == 401
    new_code = app.post("/staff/recover-owner", headers={"X-Admin-Key": "admin-test-key"}).json()["code"]
    assert app.get("/staff/me", headers={"X-Staff-Session": token}).status_code == 401
    assert app.post("/staff/login", json={"code": code}).status_code == 401
    assert app.post("/staff/login", json={"code": new_code}).status_code == 200
