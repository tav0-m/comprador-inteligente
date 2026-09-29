from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.client_ip import get_client_ip

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateRule:
    name: str
    limit: int
    window_seconds: int


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limite por IP real del cliente y por regla (ruta + metodo).

    Usa Redis (ventana fija compartida entre replicas y workers) y cae a un
    contador en memoria si Redis no esta disponible.
    """

    def __init__(self, app, rules: dict[tuple[str, str], RateRule]):
        super().__init__(app)
        self.rules = rules
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):
        rule = self.rules.get((request.method, request.url.path))
        if rule is None:
            return await call_next(request)

        client = get_client_ip(request)
        if not self._allow(rule, client):
            return JSONResponse(
                status_code=429,
                content={"detail": "Demasiadas solicitudes. Intenta nuevamente mas tarde."},
                headers={"Retry-After": str(rule.window_seconds)},
            )
        return await call_next(request)

    def _allow(self, rule: RateRule, client: str) -> bool:
        allowed = self._allow_redis(rule, client)
        return self._allow_memory(rule, client) if allowed is None else allowed

    @staticmethod
    def _allow_redis(rule: RateRule, client: str) -> bool | None:
        from app.services.cache import _get_client

        redis = _get_client()
        if redis is None:
            return None
        window = int(time.time() // rule.window_seconds)
        key = f"ci:rl:{rule.name}:{client}:{window}"
        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, rule.window_seconds + 5)
            count, _ = pipe.execute()
            return int(count) <= rule.limit
        except Exception as exc:
            logger.debug("[RateLimit] Redis fallo (%s); usando memoria.", exc)
            return None

    def _allow_memory(self, rule: RateRule, client: str) -> bool:
        key = f"{rule.name}:{client}"
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - rule.window_seconds:
                events.popleft()
            if len(events) >= rule.limit:
                return False
            events.append(now)
            return True


def default_rules(settings) -> dict[tuple[str, str], RateRule]:
    search = RateRule("search", settings.rate_limit_per_minute, 60)
    return {
        ("GET", "/search"): search,
        ("GET", "/search/stream"): RateRule("search_stream", settings.rate_limit_per_minute, 60),
        ("POST", "/search/async"): RateRule("search_async", settings.rate_limit_per_minute, 60),
        ("POST", "/basket/optimize"): RateRule("basket", max(1, settings.rate_limit_per_minute // 3), 60),
        ("POST", "/feedback"): RateRule("feedback", settings.feedback_limit_per_minute, 60),
        ("POST", "/alerts"): RateRule("alert_create", settings.alert_create_limit_per_hour, 3600),
        ("GET", "/alerts/confirm"): RateRule("alert_token", 30, 3600),
        ("GET", "/alerts/unsubscribe"): RateRule("alert_token", 30, 3600),
    }
