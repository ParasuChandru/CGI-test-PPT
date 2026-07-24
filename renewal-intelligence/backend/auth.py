"""
RBAC (NFR-101, NFR-102): role checks enforced server-side, not left to the
UI. Auth itself is a demo shim — an `X-Role` / `X-User-Id` header pair —
standing in for the enterprise SSO integration required by NFR-403, which
needs a real identity provider this POC does not have. Every request that
touches score/attribution/recommendation data is logged (NFR-106).
"""
from __future__ import annotations

from fastapi import Header, HTTPException

from . import db
from .config import ROLES


def get_actor(x_role: str = Header(...), x_user_id: str = Header(default="demo-user")):
    if x_role not in ROLES:
        raise HTTPException(status_code=401, detail=f"Unknown role '{x_role}'. Valid: {ROLES}")
    return {"role": x_role, "user_id": x_user_id}


def require_role(*allowed_roles: str):
    def checker(x_role: str = Header(...), x_user_id: str = Header(default="demo-user")):
        if x_role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{x_role}' is not permitted here. Allowed: {sorted(allowed_roles)}",
            )
        return {"role": x_role, "user_id": x_user_id}

    return checker


def audited(actor: dict, action: str, resource: str) -> None:
    db.log_audit(actor["role"], actor["user_id"], action, resource)
