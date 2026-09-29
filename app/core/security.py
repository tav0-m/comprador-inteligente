from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Protege operaciones administrativas con una clave solo del servidor."""
    configured = settings.admin_api_key.strip()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_API_KEY no esta configurada.",
        )
    if not x_admin_key or not secrets.compare_digest(x_admin_key, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial administrativa invalida.",
        )
