"""Tokens firmados (HMAC) para enlaces de email: sin estado en la base de datos."""
from __future__ import annotations

import hashlib
import hmac
import time

from app.core.config import settings


class SigningNotConfigured(RuntimeError):
    pass


def _signature(purpose: str, subject: str, expires_at: int) -> str:
    secret = settings.signing_secret
    if not secret:
        raise SigningNotConfigured("Define APP_SECRET_KEY (o ADMIN_API_KEY) para firmar enlaces.")
    message = f"{purpose}:{subject}:{expires_at}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def make_token(purpose: str, subject: str | int, ttl_seconds: int | None = None) -> str:
    """Token '<expira>.<firma>'; expira=0 significa sin vencimiento."""
    expires_at = int(time.time()) + ttl_seconds if ttl_seconds else 0
    return f"{expires_at}.{_signature(purpose, str(subject), expires_at)}"


def verify_token(purpose: str, subject: str | int, token: str) -> bool:
    try:
        raw_expiry, signature = (token or "").split(".", 1)
        expires_at = int(raw_expiry)
    except ValueError:
        return False
    if expires_at and expires_at < time.time():
        return False
    try:
        expected = _signature(purpose, str(subject), expires_at)
    except SigningNotConfigured:
        return False
    return hmac.compare_digest(expected, signature)
