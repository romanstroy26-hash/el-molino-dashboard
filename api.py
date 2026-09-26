"""FastAPI application for the El Molino customer app.

The API delegates all loyalty and customer mutations to ``customer_service``;
it does not connect to Wansoft or implement a second data-access layer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sql_text
from sqlalchemy.engine import Engine

from customer_service import (
    CustomerError,
    CustomerNotFound,
    InvalidLoginCode,
    TooManyCodes,
    InsufficientPoints,
    RedemptionNotFound,
    create_customer,
    create_campaign,
    create_campaign_for_segment,
    list_campaigns,
    activate_campaign,
    create_reward,
    create_login_challenge,
    create_registration_challenge,
    get_customer,
    find_customer_by_phone,
    get_points_balance,
    list_active_rewards,
    list_customer_campaigns,
    get_customer_insights,
    list_customer_insights,
    list_next_best_actions,
    get_campaign_analytics,
    record_campaign_event,
    record_event,
    record_purchase,
    list_customer_purchases,
    redeem_reward,
    list_customer_redemptions,
    get_redemption_for_cashier,
    fulfill_redemption,
    verify_login_code,
    register_customer_with_code,
    get_customer_profile,
    update_customer,
    update_customer_profile,
    register_customer_device,
)
from db import get_engine
from phone_numbers import mexican_sms_number
from sms_provider import SmsDeliveryError, sender_from_env


logger = logging.getLogger(__name__)


class APIModel(BaseModel):
    """Base for response payloads; database-only fields are not exposed."""


class RequestModel(APIModel):
    model_config = ConfigDict(extra="forbid")


class CustomerCreate(RequestModel):
    full_name: str = Field(min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    marketing_consent: bool = False


class CustomerOut(APIModel):
    id: str
    full_name: str
    phone: str | None = None
    email: str | None = None
    status: str
    marketing_consent: bool
    created_at: datetime
    updated_at: datetime


class CustomerUpdate(RequestModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    marketing_consent: bool | None = None


class CustomerProfileOut(APIModel):
    customer_id: str
    birth_date: str | None = None
    preferred_store_id: str | None = None
    preferred_channel: str | None = None
    created_at: datetime
    updated_at: datetime


class CustomerProfileUpdate(RequestModel):
    birth_date: str | None = Field(default=None, max_length=10)
    preferred_store_id: str | None = Field(default=None, max_length=36)
    preferred_channel: str | None = Field(default=None, max_length=30)


class DeviceRegister(RequestModel):
    platform: str = Field(pattern="^(web|ios|android)$")
    push_token: str = Field(min_length=1)


class DeviceOut(APIModel):
    id: str
    customer_id: str
    platform: str
    last_seen_at: datetime


class LoginRequest(RequestModel):
    phone: str = Field(min_length=1, max_length=40)


class LoginVerify(RequestModel):
    phone: str = Field(min_length=1, max_length=40)
    code: str = Field(pattern=r"^\d{6}$")


class RegistrationVerify(LoginVerify):
    full_name: str = Field(min_length=1, max_length=160)
    marketing_consent: bool = False


class LoginRequested(APIModel):
    detail: str
    debug_code: str | None = None


class SessionOut(APIModel):
    access_token: str
    token_type: str = "bearer"
    customer: CustomerOut


class PointsOut(APIModel):
    customer_id: str
    balance: int


class CashierCustomerOut(APIModel):
    id: str
    full_name: str
    points_balance: int


class RewardOut(APIModel):
    id: str
    name: str
    description: str | None = None
    points_cost: int
    active: bool


class RewardCreate(RequestModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    points_cost: int = Field(gt=0)


class CampaignCreate(RequestModel):
    name: str = Field(min_length=1, max_length=160)
    channel: str = Field(min_length=1, max_length=30)
    message: str | None = None
    customer_ids: list[str] = Field(min_length=1)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class SegmentCampaignCreate(RequestModel):
    name: str = Field(min_length=1, max_length=160)
    channel: str = Field(min_length=1, max_length=30)
    message: str | None = None
    segment: str = Field(pattern="^(new|active|loyal|at_risk)$")
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class CampaignOut(APIModel):
    id: str
    name: str
    channel: str
    message: str | None = None
    status: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    recipient_status: str | None = None


class CampaignCreated(APIModel):
    id: str
    name: str
    channel: str
    recipient_count: int
    status: str


class CampaignSummaryOut(APIModel):
    id: str
    name: str
    channel: str
    status: str
    recipient_count: int
    created_at: datetime


class CampaignInteraction(RequestModel):
    event_type: str = Field(pattern="^(opened|clicked)$")


class CampaignInteractionOut(APIModel):
    id: str


class CampaignAnalyticsOut(APIModel):
    id: str
    name: str
    status: str
    recipient_count: int
    opened_count: int
    clicked_count: int


class CustomerInsightsOut(APIModel):
    customer_id: str
    full_name: str
    purchase_count: int
    total_spend: float
    average_ticket: float
    last_purchase_at: datetime | None = None
    days_since_last_purchase: int | None = None
    favorite_product: str | None = None
    favorite_product_quantity: float
    points_balance: int
    segment: str


class NextBestActionOut(APIModel):
    customer_id: str
    full_name: str
    segment: str
    action_type: str
    priority: str
    reason: str
    suggested_message: str


class PurchaseItemIn(RequestModel):
    product_name: str = Field(min_length=1, max_length=180)
    product_code: str | None = Field(default=None, max_length=80)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    line_total: Decimal | None = Field(default=None, ge=0)


class PurchaseCreate(RequestModel):
    total_amount: Decimal = Field(ge=0)
    items: list[PurchaseItemIn] = Field(min_length=1)
    store_id: str | None = None
    purchased_at: datetime | None = None
    external_reference: str = Field(min_length=1, max_length=120)


class PurchaseOut(APIModel):
    id: str
    customer_id: str
    total_amount: Decimal
    points_earned: int


class PurchaseHistoryItemOut(APIModel):
    product_name: str
    quantity: Decimal
    line_total: Decimal


class PurchaseHistoryOut(PurchaseOut):
    purchased_at: datetime
    currency: str
    external_reference: str | None = None
    items: list[PurchaseHistoryItemOut]


class RedemptionOut(APIModel):
    redemption_id: str
    customer_id: str
    reward_id: str
    points_spent: int
    balance: int


class CustomerRedemptionOut(APIModel):
    id: str
    customer_id: str
    reward_id: str
    reward_name: str
    points_spent: int
    status: str
    redeemed_at: datetime


class CashierRedemptionOut(APIModel):
    id: str
    customer_id: str
    customer_name: str
    reward_name: str
    points_spent: int
    status: str
    redeemed_at: datetime


class EventCreate(RequestModel):
    event_type: str = Field(min_length=1, max_length=60)
    source: str = Field(default="app", min_length=1, max_length=30)
    reference_id: str | None = Field(default=None, max_length=120)
    value: Decimal | None = None
    text_value: str | None = None
    occurred_at: datetime | None = None


class EventOut(APIModel):
    id: str


def _error_to_http(error: CustomerError) -> HTTPException:
    if isinstance(error, TooManyCodes):
        return HTTPException(status_code=429, detail=str(error))
    if isinstance(error, RedemptionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, CustomerNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    if isinstance(error, InsufficientPoints):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _make_token(customer_id: str, secret: bytes) -> str:
    payload = json.dumps({"sub": customer_id, "exp": int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())}, separators=(",", ":")).encode()
    body = _b64(payload)
    return f"{body}.{_b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())}"


def _read_token(token: str, secret: bytes) -> str | None:
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(secret, body.encode(), hashlib.sha256).digest())
        payload = json.loads(_unb64(body))
        if not hmac.compare_digest(signature, expected) or int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return str(payload["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _validate_production_config() -> None:
    if os.getenv("APP_ENV") != "production":
        return
    required = (
        "DATABASE_URL",
        "AUTH_TOKEN_SECRET",
        "ADMIN_API_KEY",
        "CASHIER_API_KEY",
        "LABSMOBILE_USERNAME",
        "LABSMOBILE_API_TOKEN",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing production settings: " + ", ".join(missing))


def create_app(engine: Engine | None = None, otp_sender: Callable[[str, str], None] | None = None, expose_debug_code: bool = False, token_secret: str | None = None, admin_api_key: str | None = None, cashier_api_key: str | None = None) -> FastAPI:
    """Build an app.  Passing an engine keeps API tests isolated from config."""
    _validate_production_config()
    app = FastAPI(title="El Molino Customer API", version="1.0.0")
    app.state.engine = engine or get_engine()
    app.state.token_secret = (token_secret or os.getenv("AUTH_TOKEN_SECRET") or secrets.token_urlsafe(48)).encode()
    app.state.admin_api_key = admin_api_key or os.getenv("ADMIN_API_KEY")
    app.state.cashier_api_key = cashier_api_key or os.getenv("CASHIER_API_KEY")
    labsmobile_enabled = otp_sender is None and not expose_debug_code
    if labsmobile_enabled:
        otp_sender = sender_from_env()

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        try:
            with app.state.engine.connect() as connection:
                connection.execute(sql_text("SELECT 1"))
        except Exception as error:
            raise HTTPException(status_code=503, detail="Database unavailable") from error
        return {"status": "ok"}

    def require_customer(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Se requiere una sesión válida")
        customer_id = _read_token(authorization.removeprefix("Bearer "), app.state.token_secret)
        if not customer_id:
            raise HTTPException(status_code=401, detail="Sesión inválida o vencida")
        return customer_id

    def require_owner(customer_id: str, session_customer_id: str) -> None:
        if customer_id != session_customer_id:
            raise HTTPException(status_code=403, detail="No autorizado para este cliente")

    def require_admin(x_admin_key: Annotated[str | None, Header()] = None) -> None:
        if not app.state.admin_api_key:
            raise HTTPException(status_code=503, detail="El acceso de administración no está configurado")
        if not x_admin_key or not hmac.compare_digest(x_admin_key, app.state.admin_api_key):
            raise HTTPException(status_code=401, detail="Acceso de administración no autorizado")

    def require_cashier(x_cashier_key: Annotated[str | None, Header()] = None) -> None:
        if not app.state.cashier_api_key:
            raise HTTPException(status_code=503, detail="El acceso de caja no está configurado")
        if not x_cashier_key or not hmac.compare_digest(x_cashier_key, app.state.cashier_api_key):
            raise HTTPException(status_code=401, detail="Acceso de caja no autorizado")

    @app.get("/cashier/customers", response_model=CashierCustomerOut)
    def find_cashier_customer(phone: str, _: None = Depends(require_cashier)) -> dict:
        customer = find_customer_by_phone(app.state.engine, phone)
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        return {
            "id": customer["id"],
            "full_name": customer["full_name"],
            "points_balance": get_points_balance(app.state.engine, customer["id"]),
        }

    @app.get("/cashier/customers/{customer_id}/purchases", response_model=list[PurchaseHistoryOut])
    def read_cashier_purchases(customer_id: str, limit: int = Query(5, ge=1, le=20), _: None = Depends(require_cashier)) -> list[dict]:
        try:
            return list_customer_purchases(app.state.engine, customer_id, limit)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
    def register_customer(payload: CustomerCreate, _: None = Depends(require_cashier)) -> dict:
        if labsmobile_enabled:
            try:
                mexican_sms_number(payload.phone or "")
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            return create_customer(app.state.engine, **payload.model_dump())
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/auth/register/request-code", response_model=LoginRequested, response_model_exclude_none=True, status_code=status.HTTP_202_ACCEPTED)
    def request_registration_code(payload: LoginRequest) -> dict:
        if not otp_sender and not expose_debug_code:
            raise HTTPException(status_code=503, detail="El envío de SMS no está configurado")
        if labsmobile_enabled:
            try:
                mexican_sms_number(payload.phone)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            create_registration_challenge(app.state.engine, payload.phone, code)
        except TooManyCodes:
            return {"detail": "Si el número está disponible, enviamos un código."}
        except CustomerError:
            return {"detail": "Si el número está disponible, enviamos un código."}
        if otp_sender:
            try:
                otp_sender(payload.phone, code)
            except SmsDeliveryError:
                logger.warning("Registration SMS was not accepted by the provider")
                return {"detail": "Si el número está disponible, enviamos un código."}
        response = {"detail": "Si el número está disponible, enviamos un código."}
        if expose_debug_code:
            response["debug_code"] = code
        return response

    @app.post("/auth/register/verify-code", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
    def verify_registration(payload: RegistrationVerify) -> dict:
        try:
            customer = register_customer_with_code(app.state.engine, **payload.model_dump())
        except InvalidLoginCode:
            raise HTTPException(status_code=401, detail="Código inválido o vencido") from None
        except CustomerError as error:
            raise _error_to_http(error) from error
        return {"access_token": _make_token(customer["id"], app.state.token_secret), "customer": customer}

    @app.post("/auth/request-code", response_model=LoginRequested, response_model_exclude_none=True, status_code=status.HTTP_202_ACCEPTED)
    def request_login_code(payload: LoginRequest) -> dict:
        if not otp_sender and not expose_debug_code:
            raise HTTPException(status_code=503, detail="El envío de SMS no está configurado")
        if labsmobile_enabled:
            try:
                mexican_sms_number(payload.phone)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            create_login_challenge(app.state.engine, payload.phone, code)
        except CustomerNotFound:
            return {"detail": "Si el número está registrado, enviamos un código."}
        except TooManyCodes:
            return {"detail": "Si el número está registrado, enviamos un código."}
        except CustomerError as error:
            raise _error_to_http(error) from error
        if otp_sender:
            try:
                otp_sender(payload.phone, code)
            except SmsDeliveryError:
                logger.warning("Login SMS was not accepted by the provider")
                return {"detail": "Si el número está registrado, enviamos un código."}
        response = {"detail": "Si el número está registrado, enviamos un código."}
        if expose_debug_code:
            response["debug_code"] = code
        return response

    @app.post("/auth/verify-code", response_model=SessionOut)
    def verify_code(payload: LoginVerify) -> dict:
        try:
            customer = verify_login_code(app.state.engine, payload.phone, payload.code)
        except (CustomerNotFound, InvalidLoginCode):
            raise HTTPException(status_code=401, detail="Código inválido o vencido") from None
        return {"access_token": _make_token(customer["id"], app.state.token_secret), "customer": customer}

    @app.get("/customers/{customer_id}", response_model=CustomerOut)
    def read_customer(customer_id: str, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return get_customer(app.state.engine, customer_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.patch("/customers/{customer_id}", response_model=CustomerOut)
    def edit_customer(customer_id: str, payload: CustomerUpdate, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return update_customer(app.state.engine, customer_id, payload.model_dump(exclude_unset=True))
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/customers/{customer_id}/profile", response_model=CustomerProfileOut)
    def read_customer_profile(customer_id: str, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return get_customer_profile(app.state.engine, customer_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.patch("/customers/{customer_id}/profile", response_model=CustomerProfileOut)
    def edit_customer_profile(customer_id: str, payload: CustomerProfileUpdate, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return update_customer_profile(app.state.engine, customer_id, payload.model_dump(exclude_unset=True))
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/customers/{customer_id}/devices", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
    def add_customer_device(customer_id: str, payload: DeviceRegister, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return register_customer_device(app.state.engine, customer_id, **payload.model_dump())
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/customers/{customer_id}/points", response_model=PointsOut)
    def read_points(customer_id: str, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return {"customer_id": customer_id, "balance": get_points_balance(app.state.engine, customer_id)}
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/customers/{customer_id}/rewards", response_model=list[RewardOut])
    def read_rewards(customer_id: str, session_customer_id: str = Depends(require_customer)) -> list[dict]:
        require_owner(customer_id, session_customer_id)
        try:
            get_customer(app.state.engine, customer_id)
            return list_active_rewards(app.state.engine)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/customers/{customer_id}/campaigns", response_model=list[CampaignOut])
    def read_campaigns(customer_id: str, session_customer_id: str = Depends(require_customer)) -> list[dict]:
        require_owner(customer_id, session_customer_id)
        try:
            get_customer(app.state.engine, customer_id)
            return list_customer_campaigns(app.state.engine, customer_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/admin/rewards", response_model=RewardOut, status_code=status.HTTP_201_CREATED)
    def add_reward(payload: RewardCreate, _: None = Depends(require_admin)) -> dict:
        try:
            return create_reward(app.state.engine, **payload.model_dump())
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/admin/campaigns", response_model=CampaignCreated, status_code=status.HTTP_201_CREATED)
    def add_campaign(payload: CampaignCreate, _: None = Depends(require_admin)) -> dict:
        try:
            return create_campaign(app.state.engine, **payload.model_dump())
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/admin/campaigns", response_model=list[CampaignSummaryOut])
    def read_admin_campaigns(_: None = Depends(require_admin)) -> list[dict]:
        return list_campaigns(app.state.engine)

    @app.get("/admin/customers/{customer_id}/insights", response_model=CustomerInsightsOut)
    def read_customer_insights(customer_id: str, _: None = Depends(require_admin)) -> dict:
        try:
            return get_customer_insights(app.state.engine, customer_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/admin/audiences", response_model=list[CustomerInsightsOut])
    def read_audience(segment: str | None = None, _: None = Depends(require_admin)) -> list[dict]:
        try:
            return list_customer_insights(app.state.engine, segment)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/admin/next-best-actions", response_model=list[NextBestActionOut])
    def read_next_best_actions(_: None = Depends(require_admin)) -> list[dict]:
        return list_next_best_actions(app.state.engine)

    @app.post("/admin/campaigns/by-segment", response_model=CampaignCreated, status_code=status.HTTP_201_CREATED)
    def add_segment_campaign(payload: SegmentCampaignCreate, _: None = Depends(require_admin)) -> dict:
        try:
            return create_campaign_for_segment(app.state.engine, **payload.model_dump())
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/admin/campaigns/{campaign_id}/activate")
    def activate_existing_campaign(campaign_id: str, _: None = Depends(require_admin)) -> dict:
        try:
            return activate_campaign(app.state.engine, campaign_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/admin/campaigns/{campaign_id}/analytics", response_model=CampaignAnalyticsOut)
    def read_campaign_analytics(campaign_id: str, _: None = Depends(require_admin)) -> dict:
        try:
            return get_campaign_analytics(app.state.engine, campaign_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/customers/{customer_id}/campaigns/{campaign_id}/events", response_model=CampaignInteractionOut, status_code=status.HTTP_201_CREATED)
    def create_campaign_interaction(customer_id: str, campaign_id: str, payload: CampaignInteraction, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return {"id": record_campaign_event(app.state.engine, customer_id, campaign_id, payload.event_type)}
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/customers/{customer_id}/purchases", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
    def create_purchase(customer_id: str, payload: PurchaseCreate, _: None = Depends(require_cashier)) -> dict:
        try:
            values = payload.model_dump()
            values["items"] = [item.model_dump() for item in payload.items]
            return record_purchase(app.state.engine, customer_id, source="cashier", points_per_mxn=1, **values)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/customers/{customer_id}/purchases", response_model=list[PurchaseHistoryOut])
    def read_customer_purchases(customer_id: str, limit: int = Query(20, ge=1, le=50), session_customer_id: str = Depends(require_customer)) -> list[dict]:
        require_owner(customer_id, session_customer_id)
        try:
            return list_customer_purchases(app.state.engine, customer_id, limit)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/customers/{customer_id}/rewards/{reward_id}/redeem", response_model=RedemptionOut, status_code=status.HTTP_201_CREATED)
    def create_redemption(customer_id: str, reward_id: str, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return redeem_reward(app.state.engine, customer_id, reward_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.get("/customers/{customer_id}/redemptions", response_model=list[CustomerRedemptionOut])
    def read_customer_redemptions(customer_id: str, session_customer_id: str = Depends(require_customer)) -> list[dict]:
        require_owner(customer_id, session_customer_id)
        return list_customer_redemptions(app.state.engine, customer_id)

    @app.get("/cashier/redemptions/{redemption_id}", response_model=CashierRedemptionOut)
    def read_cashier_redemption(redemption_id: str, _: None = Depends(require_cashier)) -> dict:
        try:
            return get_redemption_for_cashier(app.state.engine, redemption_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/cashier/redemptions/{redemption_id}/fulfill", response_model=CashierRedemptionOut)
    def confirm_reward_handover(redemption_id: str, _: None = Depends(require_cashier)) -> dict:
        try:
            return fulfill_redemption(app.state.engine, redemption_id)
        except CustomerError as error:
            raise _error_to_http(error) from error

    @app.post("/customers/{customer_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
    def create_event(customer_id: str, payload: EventCreate, session_customer_id: str = Depends(require_customer)) -> dict:
        require_owner(customer_id, session_customer_id)
        try:
            return {"id": record_event(app.state.engine, customer_id, **payload.model_dump())}
        except CustomerError as error:
            raise _error_to_http(error) from error

    web_directory = Path(__file__).resolve().parent / "web"
    if web_directory.is_dir():
        app.mount("/", StaticFiles(directory=web_directory, html=True), name="customer-app")

    return app


app = create_app()
