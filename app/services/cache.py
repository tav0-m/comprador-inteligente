from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)
_redis_client = None
_redis_ok = False


def _get_client():
    global _redis_client, _redis_ok
    if _redis_client is not None:
        return _redis_client if _redis_ok else None
    try:
        import redis

        _redis_client = redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        _redis_client.ping()
        _redis_ok = True
    except Exception as exc:
        logger.info("[Cache] Redis no disponible (%s); se continua sin cache.", exc)
        _redis_ok = False
    return _redis_client if _redis_ok else None


def cache_key(query: str, country: str = "cl", city: str | None = None, max_results: int = 20) -> str:
    raw = f"v5|{country}|{(city or '').strip().lower()}|{max_results}|{query.strip().lower()}"
    return "ci:search:" + hashlib.sha256(raw.encode()).hexdigest()


def cache_get(key: str) -> Any | None:
    client = _get_client()
    if not client:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("[Cache] Lectura fallida: %s", exc)
        return None


def cache_set(key: str, value: Any, ttl: int | None = None) -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        client.setex(
            key,
            ttl or settings.cache_ttl_seconds,
            json.dumps(value, ensure_ascii=False, default=str),
        )
        return True
    except Exception as exc:
        logger.debug("[Cache] Escritura fallida: %s", exc)
        return False


def cache_delete(key: str) -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        client.delete(key)
        return True
    except Exception:
        return False


def cache_stats() -> dict:
    client = _get_client()
    if not client:
        return {"available": False, "keys": 0, "memory_mb": 0}
    try:
        info = client.info("memory")
        return {
            "available": True,
            "keys": client.dbsize(),
            "memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
        }
    except Exception:
        return {"available": False, "keys": 0, "memory_mb": 0}
