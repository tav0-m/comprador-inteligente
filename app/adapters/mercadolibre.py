"""
Adaptador MercadoLibre Chile v2 — API oficial (sin key), con filtros de categoría
y manejo de precio en CLP.
"""
from __future__ import annotations
import logging, threading, time
import requests
from app.adapters.base import SearchAdapter
from app.adapters._price_utils import clp_to_float, to_count, to_rating
from app.core.config import settings
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

SITE_BY_COUNTRY = {
    "cl": "MLC",
    "ar": "MLA",
    "mx": "MLM",
    "co": "MCO",
    "pe": "MPE",
}

# Categorías relevantes para constructora en ML Chile
_CONSTRUCTION_CATEGORIES = {
    "MLC1574",  # Herramientas y Hogar
    "MLC1500",  # Construcción
    "MLC436355", # Materiales de Construcción
    "MLC3937",  # Pinturas y Accesorios
}

_HEADERS = {
    "User-Agent": "CompradorInteligente/2.0 (+constructora-cl)",
    "Accept": "application/json",
    "Accept-Language": "es-CL,es;q=0.9",
}

class MercadoLibreAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        site = SITE_BY_COUNTRY.get(country.lower(), "MLC")
        token = get_access_token()
        if not token:
            return []
        try:
            offers = self._search_api(query, site, max_results, token)
            logger.info(f"[MercadoLibre] {len(offers)} resultados para '{query}'")
            return offers
        except Exception as exc:
            logger.warning(f"[MercadoLibre] Error: {exc}")
            return []

    def _search_api(self, query: str, site: str, max_results: int, token: str) -> list[ProductOffer]:
        """
        Pagina la API de ML en bloques de 50. Maximo 3 paginas = 150 productos.
        Desde 2025 /sites/{site}/search exige un token OAuth (sin token responde 403).
        """
        from app.adapters._pagination import offset_paginate, MAX_PAGES

        url = f"https://api.mercadolibre.com/sites/{site}/search"
        headers = {**_HEADERS, "Authorization": f"Bearer {token}"}
        base_params = {
            "q":         query,
            "sort":      "price_asc",
            "condition": "new",
        }

        check = requests.get(url, params={**base_params, "limit": "1", "offset": "0"},
                             headers=headers, timeout=10)
        if check.status_code in (401, 403):
            _invalidate_token()
            logger.warning(f"[MercadoLibre] HTTP {check.status_code} con token de aplicacion; "
                           "revisa permisos de la app en developers.mercadolibre.cl")
            return []
        if check.status_code != 200:
            logger.warning(f"[MercadoLibre] HTTP {check.status_code} — omitiendo")
            return []

        total_available = check.json().get("paging", {}).get("total", 0)
        target = min(max_results, total_available, 50 * MAX_PAGES)
        if target <= 0:
            return []

        raw_items = offset_paginate(
            url=url,
            base_params=base_params,
            offset_key="offset",
            limit_key="limit",
            max_results=target,
            headers=headers,
            results_key="results",
            page_size=50,
            timeout=20,
        )

        offers = [o for o in (_parse_item(item) for item in raw_items) if o]
        logger.info(f"[MercadoLibre] {len(offers)} resultados (de {total_available} disponibles)")
        return offers


# ── OAuth (client_credentials) ────────────────────────────────────────────────
_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
_token_lock = threading.Lock()
_token_cache: dict = {"value": None, "expires_at": 0.0}
_missing_credentials_logged = False


def get_access_token() -> str | None:
    """Token de aplicacion cacheado en memoria hasta 5 min antes de expirar."""
    global _missing_credentials_logged
    if not settings.mercadolibre_client_id or not settings.mercadolibre_client_secret:
        if not _missing_credentials_logged:
            logger.info("[MercadoLibre] Sin MERCADOLIBRE_CLIENT_ID/SECRET; fuente omitida.")
            _missing_credentials_logged = True
        return None
    with _token_lock:
        if _token_cache["value"] and time.time() < _token_cache["expires_at"]:
            return _token_cache["value"]
        try:
            response = requests.post(
                _TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.mercadolibre_client_id,
                    "client_secret": settings.mercadolibre_client_secret,
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.warning(f"[MercadoLibre] No se pudo obtener token: {exc}")
            return None
        if response.status_code != 200:
            logger.warning(f"[MercadoLibre] OAuth HTTP {response.status_code}; revisa las credenciales.")
            return None
        payload = response.json()
        _token_cache["value"] = payload.get("access_token")
        _token_cache["expires_at"] = time.time() + max(60, int(payload.get("expires_in", 21600)) - 300)
        return _token_cache["value"]


def _invalidate_token() -> None:
    with _token_lock:
        _token_cache["value"] = None
        _token_cache["expires_at"] = 0.0


def _parse_item(item: dict) -> ProductOffer | None:
    try:
        title = (item.get("title") or "").strip()
        if not title: return None
        currency = item.get("currency_id") or "CLP"
        raw_price = item.get("price")
        # Precio original_price = precio sin descuento
        original_price = item.get("original_price")

        price = clp_to_float(raw_price)
        if not price: return None

        shipping = item.get("shipping") or {}
        free_ship = bool(shipping.get("free_shipping"))
        logistic  = shipping.get("logistic_type", "")
        if free_ship:
            delivery = "Envío gratis"
        elif logistic in ("fulfillment", "self_service"):
            delivery = "Despacho disponible"
        else:
            delivery = "Retiro o despacho"

        # Disponibilidad
        qty   = item.get("available_quantity") or 0
        avail = "En stock" if qty > 0 else "Agotado"

        # Rating y reseñas
        reviews = to_count(item.get("reviews", {}).get("rating_total") if isinstance(item.get("reviews"), dict)
                          else item.get("reviews_total"))

        # Ahorro si hay precio original
        price_text = f"CLP {price:,.0f}"
        if original_price:
            orig = clp_to_float(original_price)
            if orig and orig > price:
                savings_pct = int((orig - price) / orig * 100)
                price_text += f" (-{savings_pct}%)"

        return ProductOffer(
            title=title,
            store="Mercado Libre",
            source="mercadolibre",
            price_text=price_text,
            extracted_price=price,
            currency=currency,
            delivery=delivery,
            availability=avail,
            rating=_to_rating(item),
            reviews=reviews,
            link=item.get("permalink"),
            thumbnail=item.get("thumbnail"),
        )
    except Exception:
        return None

def _to_rating(item: dict) -> float | None:
    """Extrae rating de múltiples lugares posibles en la respuesta ML."""
    for key in ("seller_reputation", "reviews"):
        val = item.get(key)
        if isinstance(val, dict):
            r = val.get("rating") or val.get("rating_average")
            if r: return to_rating(r)
    return None
