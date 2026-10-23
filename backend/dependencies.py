"""Ortak bağımlılıklar: kullanıcı çekme, audit log, uuid/now helpers."""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException, Request, Depends
from auth_utils import decode_token
from database import db

logger = logging.getLogger(__name__)


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_current_user(request: Request) -> dict:
    """JWT'den kullanıcıyı çek (cookie veya Authorization header)."""
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Oturum açmanız gerekli")
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Geçersiz token tipi")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user or user.get("active") is False:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı veya pasif")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Yetkiniz yok (admin gerekli)")
    return user


async def write_audit(user: dict, action: str, resource: str, resource_id: Optional[str] = None, meta: Optional[dict] = None):
    try:
        await db.audit_logs.insert_one({
            "id": _uid(),
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "action": action,
            "resource": resource,
            "resource_id": resource_id,
            "meta": meta or {},
            "ts": _now(),
        })
    except Exception as e:
        logger.warning("audit yazılamadı: %s", e)


async def require_writer(user: dict = Depends(get_current_user)) -> dict:
    if user.get('role') not in {'admin', 'manager', 'accountant', 'finance', 'operations'}:
        raise HTTPException(403, 'Bu işlem için kayıt düzenleme yetkisi gerekiyor.')
    return user


async def require_finance(user: dict = Depends(get_current_user)) -> dict:
    if user.get('role') not in {'admin', 'manager', 'accountant', 'finance'}:
        raise HTTPException(403, 'Bu işlem için finans yetkisi gerekiyor.')
    return user


async def require_approver(user: dict = Depends(get_current_user)) -> dict:
    if user.get('role') not in {'admin', 'manager', 'accountant'}:
        raise HTTPException(403, 'Belge onaylamak için yönetici veya muhasebe yetkisi gerekiyor.')
    return user
