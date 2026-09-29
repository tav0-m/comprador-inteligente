"""
Adaptador Sodimac Chile v4.

Sodimac migro a la misma plataforma Next.js de Falabella: la busqueda publica
los productos en __NEXT_DATA__ (pageProps.searchProps.searchData.results).
Las APIs ATG anteriores (/s/search/...) ya no responden y el adaptador
tardaba ~30 s probando 18 combinaciones antes de devolver 0 resultados.
"""
from __future__ import annotations

import logging
import random
import time

from app.adapters._html_data import dig, fetch_html, next_data_page_props
from app.adapters.base import SearchAdapter
from app.adapters.falabella import parse_jsonld_products, parse_platform_item
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.sodimac.cl/sodimac-cl/search"
PAGE_SIZE = 28
MAX_PAGES = 3

# En Sodimac "NORMAL" es el precio vigente; el tachado llega con label "Normal"
# (p. ej. en combos). Los precios con tarjeta CMR se informan aparte.
SODIMAC_PRICE_TYPES = {
    "current": {"NORMAL", "INTERNET", "EVENT"},
    "reference": {"COMBO"},
    "card": {"CMR", "cmrPrice"},
}


def _product_link(item: dict) -> str | None:
    product_id = item.get("productId")
    # /product/{id} redirige al articulo canonico con slug y SKU.
    return f"https://www.sodimac.cl/sodimac-cl/product/{product_id}" if product_id else None


class SodimacAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl":
            return []
        offers: list[ProductOffer] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(random.uniform(0.2, 0.5))
            params = {"Ntt": query, **({"currentpage": str(page)} if page > 1 else {})}
            html = fetch_html(SEARCH_URL, params, store="Sodimac")
            if not html:
                break
            search_data = dig(next_data_page_props(html), "searchProps", "searchData")
            results = dig(search_data, "results")
            if not isinstance(results, list):
                if page == 1:
                    offers = parse_jsonld_products(html, store="Sodimac", source="sodimac")
                break
            for item in results:
                offer = parse_platform_item(item, store="Sodimac", source="sodimac",
                                            price_types=SODIMAC_PRICE_TYPES, link_builder=_product_link)
                if offer and offer.link not in seen:
                    seen.add(offer.link)
                    offers.append(offer)
            total = dig(search_data, "pagination", "count", default=len(results))
            if len(offers) >= max_results or len(results) < PAGE_SIZE or page * PAGE_SIZE >= total:
                break
        logger.info("[Sodimac] %d resultados para '%s'", len(offers), query)
        return offers[:max_results]
