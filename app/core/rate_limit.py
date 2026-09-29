from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limite simple por IP para proteger endpoints costosos.

    Redis debe reemplazar este contador cuando haya mas de una replica de API.
    """

    PROTECTED_PATHS = {"/search", "/search/stream", "/search/async", "/basket/optimize"}

    def __init__(self, app, requests_per_minute: int = 30):
        super().__init__(app)
        self.limit = requests_per_minute
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):
        if request.url.path not in self.PROTECTED_PATHS:
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        key = f"{client}:{request.url.path}"
        now = time.monotonic()

        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= self.limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Demasiadas solicitudes. Intenta nuevamente en un minuto."},
                    headers={"Retry-After": "60"},
                )
            events.append(now)

        return await call_next(request)
