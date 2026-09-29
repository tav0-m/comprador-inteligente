"""
Adaptador Paris Chile v3.

Paris dejo la API VTEX; la pagina /search/?q= publica los resultados como un
ItemList de schema.org en JSON-LD (nombre, marca, precio, URL, imagen). El
catalogo incluye productos de Easy (ambos son Cencosud).
"""
from __future__ import annotations

import logging

from app.adapters._html_data import fetch_html
from app.adapters.base import SearchAdapter
from app.adapters.falabella import parse_jsonld_products
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.paris.cl/search/"


class ParisAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl":
            return []
        html = fetch_html(SEARCH_URL, {"q": query}, store="Paris")
        if not html:
            return []
        offers, seen = [], set()
        for offer in parse_jsonld_products(html, store="Paris", source="paris"):
            if offer.link not in seen:
                seen.add(offer.link)
                offers.append(offer)
        logger.info("[Paris] %d resultados para '%s'", len(offers), query)
        return offers[:max_results]
