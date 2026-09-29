"""IP real del cliente detras de proxies de confianza."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
from functools import lru_cache

from starlette.requests import Request

from app.core.config import settings


@lru_cache
def _trusted_networks() -> tuple:
    networks = []
    for cidr in settings.trusted_proxy_cidrs:
        try:
            networks.append(ipaddress.ip_network(cidr.strip(), strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in _trusted_networks())


def get_client_ip(request: Request) -> str:
    """Recorre X-Forwarded-For de derecha a izquierda saltando proxies confiables.

    Solo se lee el encabezado si la conexion viene de un proxy confiable; de lo
    contrario cualquiera podria falsificar su IP. Detras del frontend Next.js,
    sin esto todos los usuarios compartian la IP del contenedor.
    """
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted(peer):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    for address in reversed(chain):
        if not _is_trusted(address):
            return address
    return chain[0] if chain else peer


def client_fingerprint(request: Request) -> str:
    """Seudonimo estable de la IP (HMAC): permite deduplicar sin guardar la IP."""
    secret = settings.signing_secret or "sin-secreto"
    return hmac.new(secret.encode(), get_client_ip(request).encode(), hashlib.sha256).hexdigest()
