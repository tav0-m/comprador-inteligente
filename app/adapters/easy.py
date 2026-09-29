"""
Adaptador Easy Chile v4.

Easy dejo de exponer la API VTEX catalog_system (responde 404). La busqueda
vive en /search/{termino} (Next.js) y publica los productos en __NEXT_DATA__
(pageProps.serverProductsResponse.productList), incluido el precio por unidad
de medida (ppumPrices: CLP/kg, CLP/m2...), util para comparar formatos.
"""
from __future__ import annotations

import logging
import random
import time
from urllib.parse import quote

from app.adapters._html_data import dig, fetch_html, format_clp, next_data_page_props
from app.adapters._price_utils import clp_to_float
from app.adapters.base import SearchAdapter
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

BASE_URL = "https://www.easy.cl"
PAGE_SIZE = 40
MAX_PAGES = 3


class EasyAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl":
            return []
        url = f"{BASE_URL}/search/{quote(query, safe='')}"
        offers: list[ProductOffer] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(random.uniform(0.2, 0.5))
            html = fetch_html(url, {"page": str(page)} if page > 1 else None, store="Easy")
            if not html:
                break
            response = dig(next_data_page_props(html), "serverProductsResponse")
            products = dig(response, "productList")
            if not isinstance(products, list):
                break
            for item in products:
                offer = parse_easy_product(item)
                if offer and offer.link not in seen:
                    seen.add(offer.link)
                    offers.append(offer)
            total = dig(response, "recordsFiltered", default=len(products))
            if len(offers) >= max_results or len(products) < PAGE_SIZE or page * PAGE_SIZE >= total:
                break
        logger.info("[Easy] %d resultados para '%s'", len(offers), query)
        return offers[:max_results]


def _current_and_normal(prices: dict | None) -> tuple[float | None, float | None]:
    prices = prices or {}
    normal = clp_to_float(prices.get("normalPrice"))
    candidates = [clp_to_float(prices.get(key)) for key in ("offerPrice", "normalPrice")]
    candidates = [value for value in candidates if value]
    return (min(candidates) if candidates else None), normal


def parse_easy_product(item: dict) -> ProductOffer | None:
    title = (item.get("productName") or "").strip()
    if not title:
        return None
    prices = item.get("prices") or dig(item, "commercialOffer", "defaultOffer", "prices")
    price, normal = _current_and_normal(prices)
    if not price:
        return None

    brand = (item.get("brand") or "").strip()
    if brand and brand.casefold() not in title.casefold():
        title = f"{brand} {title}"

    price_text = f"CLP {format_clp(price)}"
    if normal and normal > price:
        price_text += f" (normal {format_clp(normal)})"
    unit_prices = item.get("ppumPrices") or dig(item, "commercialOffer", "defaultOffer", "pricesPerUnit")
    unit_price, _ = _current_and_normal(unit_prices) if unit_prices else (None, None)
    if unit_price and unit_prices.get("contentUnit"):
        price_text += f" [{format_clp(unit_price)}/{unit_prices['contentUnit']}]"

    link_text = (item.get("linkText") or "").strip("/")
    quantity = item.get("availableQuantity")
    return ProductOffer(
        title=title[:500],
        store="Easy",
        seller=(item.get("sellerName") or None) if item.get("isMarketplace") else None,
        source="easy",
        price_text=price_text[:100],
        extracted_price=price,
        currency=(prices or {}).get("currency") or "CLP",
        delivery="Despacho disponible",
        availability="Sin stock" if quantity == 0 else "Disponible",
        link=f"{BASE_URL}/{link_text}" if link_text else None,
        thumbnail=item.get("imageUrl"),
    )
