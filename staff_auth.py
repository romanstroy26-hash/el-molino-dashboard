"""Personal staff access, revocable sessions, and a server-side activity log."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, MetaData, String, Table, Text, select, update
from sqlalchemy.engine import Engine


PERMISSIONS = ("cashier", "analytics", "rewards", "campaigns")
staff_metadata = MetaData()
staff_users = Table(
    "staff_users", staff_metadata,
    Column("id", String(36), primary_key=True),
    Column("full_name", String(160), nullable=False),
    Column("code_hash", String(64), nullable=False, unique=True),
    Column("permissions", Text, nullable=False),
    Column("is_owner", Boolean, nullable=False, default=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)
staff_sessions = Table(
    "staff_sessions", staff_metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", String(36), ForeignKey("staff_users.id"), nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Column("revoked_at", DateTime),
    Column("created_at", DateTime, nullable=False),
)
staff_actions = Table(
    "staff_actions", staff_metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("staff_users.id"), nullable=False),
    Column("action", String(120), nullable=False),
    Column("target", String(255)),
    Column("created_at", DateTime, nullable=False),
)
Index("ix_staff_sessions_user", staff_sessions.c.user_id)
Index("ix_staff_actions_date", staff_actions.c.created_at)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _normalize_code(code: str) -> str:
    return "".join(char for char in code.upper() if char.isalnum())


def _new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    characters = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join(characters[index:index + 4] for index in range(0, 16, 4))


def public_user(row) -> dict:
    data = row._mapping if hasattr(row, "_mapping") else row
    return {
        "id": data["id"], "full_name": data["full_name"],
        "permissions": list(PERMISSIONS) if data["is_owner"] else json.loads(data["permissions"]),
        "is_owner": bool(data["is_owner"]), "active": bool(data["active"]),
    }


def owner_exists(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(staff_users.c.id).where(staff_users.c.is_owner.is_(True)).limit(1)).first() is not None


def create_user(engine: Engine, full_name: str, permissions: list[str], is_owner: bool = False) -> tuple[dict, str]:
    if set(permissions) - set(PERMISSIONS):
        raise ValueError("Permiso desconocido")
    code = _new_code()
    now = _now()
    row = {"id": str(uuid4()), "full_name": full_name.strip(), "code_hash": _digest(_normalize_code(code)),
           "permissions": json.dumps(sorted(set(permissions))), "is_owner": is_owner,
           "active": True, "created_at": now, "updated_at": now}
    if not row["full_name"]:
        raise ValueError("Nombre requerido")
    with engine.begin() as conn:
        if is_owner and conn.execute(select(staff_users.c.id).where(staff_users.c.is_owner.is_(True)).limit(1)).first():
            raise ValueError("La cuenta principal ya existe")
        conn.execute(staff_users.insert().values(**row))
    return public_user(row), code


def login(engine: Engine, code: str) -> tuple[dict, str] | None:
    normalized = _normalize_code(code)
    if len(normalized) != 16:
        return None
    with engine.begin() as conn:
        row = conn.execute(select(staff_users).where(staff_users.c.code_hash == _digest(normalized))).first()
        if not row or not row.active or not hmac.compare_digest(row.code_hash, _digest(normalized)):
            return None
        token = secrets.token_urlsafe(32)
        conn.execute(staff_sessions.insert().values(token_hash=_digest(token), user_id=row.id,
                                                  expires_at=_now() + timedelta(hours=12), created_at=_now()))
        conn.execute(staff_actions.insert().values(id=str(uuid4()), user_id=row.id, action="login", created_at=_now()))
        return public_user(row), token


def session_user(engine: Engine, token: str | None) -> dict | None:
    if not token:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(staff_users).join(staff_sessions, staff_users.c.id == staff_sessions.c.user_id)
                           .where(staff_sessions.c.token_hash == _digest(token), staff_sessions.c.revoked_at.is_(None),
                                  staff_sessions.c.expires_at > _now(), staff_users.c.active.is_(True))).first()
        return public_user(row) if row else None


def revoke_session(engine: Engine, token: str, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(update(staff_sessions).where(staff_sessions.c.token_hash == _digest(token),
                                                  staff_sessions.c.user_id == user_id).values(revoked_at=_now()))
        conn.execute(staff_actions.insert().values(id=str(uuid4()), user_id=user_id, action="logout", created_at=_now()))


def list_users(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        return [public_user(row) for row in conn.execute(select(staff_users).order_by(staff_users.c.created_at))]


def update_user(engine: Engine, user_id: str, *, full_name: str | None = None,
                permissions: list[str] | None = None, active: bool | None = None) -> dict | None:
    if permissions is not None and set(permissions) - set(PERMISSIONS):
        raise ValueError("Permiso desconocido")
    with engine.begin() as conn:
        row = conn.execute(select(staff_users).where(staff_users.c.id == user_id)).first()
        if not row:
            return None
        if row.is_owner:
            raise ValueError("La cuenta principal no se puede cambiar aquí")
        values = {"updated_at": _now()}
        if full_name is not None:
            if not full_name.strip():
                raise ValueError("Nombre requerido")
            values["full_name"] = full_name.strip()
        if permissions is not None:
            values["permissions"] = json.dumps(sorted(set(permissions)))
        if active is not None:
            values["active"] = active
        conn.execute(update(staff_users).where(staff_users.c.id == user_id).values(**values))
        # Permissions and status changes take effect immediately, including open sessions.
        return public_user({**row._mapping, **values})


def rotate_code(engine: Engine, user_id: str, *, allow_owner: bool = False) -> str | None:
    with engine.begin() as conn:
        row = conn.execute(select(staff_users).where(staff_users.c.id == user_id)).first()
        if not row:
            return None
        if row.is_owner and not allow_owner:
            raise ValueError("El código principal no se cambia aquí")
        code = _new_code()
        conn.execute(update(staff_users).where(staff_users.c.id == user_id).values(
            code_hash=_digest(_normalize_code(code)), updated_at=_now()))
        conn.execute(update(staff_sessions).where(staff_sessions.c.user_id == user_id,
                                                 staff_sessions.c.revoked_at.is_(None)).values(revoked_at=_now()))
        return code


def recover_owner_code(engine: Engine) -> str | None:
    with engine.connect() as conn:
        owner = conn.execute(select(staff_users.c.id).where(staff_users.c.is_owner.is_(True)).limit(1)).first()
    return rotate_code(engine, owner.id, allow_owner=True) if owner else None


def log_action(engine: Engine, user_id: str, action: str, target: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(staff_actions.insert().values(id=str(uuid4()), user_id=user_id, action=action,
                                                  target=target, created_at=_now()))


def list_actions(engine: Engine, limit: int = 100) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(staff_actions.c.action, staff_actions.c.target, staff_actions.c.created_at,
                                   staff_users.c.full_name).join(staff_users, staff_users.c.id == staff_actions.c.user_id)
                            .order_by(staff_actions.c.created_at.desc()).limit(limit)).all()
        return [dict(row._mapping) for row in rows]
