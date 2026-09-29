"""
Adaptador MercadoLibre Chile v2 — API oficial (sin key), con filtros de categoría
y manejo de precio en CLP.
"""
from __future__ import annotations
import logging, time, random
import requests
from app.adapters.base import SearchAdapter
from app.adapters._price_utils import clp_to_float, to_int
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
        try:
            offers = self._search_api(query, site, max_results)
            logger.info(f"[MercadoLibre] {len(offers)} resultados para '{query}'")
            return offers
        except Exception as exc:
            logger.warning(f"[MercadoLibre] Error: {exc}")
            return []

    def _search_api(self, query: str, site: str, max_results: int) -> list[ProductOffer]:
        """
        Pagina la API de ML en bloques de 50. Máximo 3 páginas = 150 productos.
        ML permite hasta 1000 resultados totales con offset.
        """
        from app.adapters._pagination import offset_paginate, MAX_PAGES

        url = f"https://api.mercadolibre.com/sites/{site}/search"
        base_params = {
            "q":         query,
            "sort":      "price_asc",
            "condition": "new",
        }

        # Verificar conectividad en primera llamada antes de paginar
        try:
            check = requests.get(url, params={**base_params, "limit": "1", "offset": "0"},
                                 headers=_HEADERS, timeout=10)
            if check.status_code in (401, 403, 429):
                logger.warning(f"[MercadoLibre] HTTP {check.status_code} — omitiendo")
                return []
        except Exception as exc:
            logger.warning(f"[MercadoLibre] Sin conexión: {exc}")
            return []

        # Cuántos resultados hay disponibles según la API
        try:
            total_available = check.json().get("paging", {}).get("total", 0)
        except Exception:
            total_available = max_results

        target = min(max_results, total_available, 50 * MAX_PAGES)

        raw_items = offset_paginate(
            url=url,
            base_params=base_params,
            offset_key="offset",
            limit_key="limit",
            max_results=target,
            headers=_HEADERS,
            results_key="results",
            page_size=50,
            timeout=20,
        )

        offers = [o for o in (_parse_item(item) for item in raw_items) if o]
        logger.info(f"[MercadoLibre] {len(offers)} resultados (de {total_available} disponibles)")
        return offers


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
        reviews = to_int(item.get("reviews", {}).get("rating_total") if isinstance(item.get("reviews"), dict)
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
            if r: return clp_to_float(r)
    return None
