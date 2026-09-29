"""
Adaptador Falabella Chile v3.

Falabella renderiza la busqueda con Next.js: el HTML trae los productos en
__NEXT_DATA__ (props.pageProps.results), sin navegador headless. Las antiguas
APIs /s/browse/v1/listing y /search/api/listing ya no responden JSON, y el
scraping de tarjetas con Playwright tomaba filtros ("Tipo de Entrega") como
titulos.

Falabella es marketplace: ~30% de los resultados los vende Sodimac; el
vendedor real queda en `seller`.
"""
from __future__ import annotations

import logging
import random
import time

from app.adapters._html_data import dig, fetch_html, format_clp, jsonld_blocks, next_data_page_props, strip_tags
from app.adapters._price_utils import clp_to_float, to_count, to_rating
from app.adapters.base import SearchAdapter
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.falabella.com/falabella-cl/search"
PAGE_SIZE = 48
MAX_PAGES = 3

# Tipos de precio de la plataforma Falabella/Sodimac.
# cmrPrice exige tarjeta CMR y normalPrice viene tachado: se informan, no se comparan.
FALABELLA_PRICE_TYPES = {
    "current": {"eventPrice", "internetPrice"},
    "reference": {"normalPrice"},
    "card": {"cmrPrice"},
}


class FalabellaAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl":
            return []
        offers: list[ProductOffer] = []
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(random.uniform(0.2, 0.5))
            params = {"Ntt": query, **({"page": str(page)} if page > 1 else {})}
            html = fetch_html(SEARCH_URL, params, store="Falabella")
            if not html:
                break
            props = next_data_page_props(html)
            results = dig(props, "results")
            if not isinstance(results, list):
                if page == 1:  # cambio de plataforma: ultimo recurso JSON-LD
                    offers = parse_jsonld_products(html, store="Falabella", source="falabella")
                break
            for item in results:
                offer = parse_platform_item(item, store="Falabella", source="falabella",
                                            price_types=FALABELLA_PRICE_TYPES)
                if offer and offer.link not in seen:
                    seen.add(offer.link)
                    offers.append(offer)
            total = dig(props, "pagination", "count", default=len(results))
            if len(offers) >= max_results or len(results) < PAGE_SIZE or page * PAGE_SIZE >= total:
                break
        logger.info("[Falabella] %d resultados para '%s'", len(offers), query)
        return offers[:max_results]


def _price_of(entry: dict) -> float | None:
    if entry.get("priceWithoutFormatting"):
        return clp_to_float(entry["priceWithoutFormatting"])
    values = entry.get("price") or []
    if isinstance(values, (str, int, float)):
        values = [values]
    # Rangos ("desde-hasta") traen dos valores: se usa el menor publicado.
    parsed = [value for value in (clp_to_float(v) for v in values) if value]
    return min(parsed) if parsed else None


def select_prices(prices: list[dict], price_types: dict) -> tuple[float | None, float | None, float | None]:
    """Retorna (precio_vigente, precio_referencia, precio_tarjeta)."""
    current, reference, card = [], [], []
    for entry in prices or []:
        price = _price_of(entry)
        if not price:
            continue
        kind = entry.get("type")
        if kind in price_types["card"]:
            card.append(price)
        elif (kind in price_types["reference"] or entry.get("crossed")
              or (entry.get("label") or "").strip().casefold() == "normal"):
            reference.append(price)
        else:
            current.append(price)
    current_price = min(current) if current else (min(reference) if reference else None)
    reference_price = max(reference) if reference else None
    card_price = min(card) if card else None
    return current_price, reference_price, card_price


def parse_platform_item(item: dict, store: str, source: str, price_types: dict,
                        link_builder=None) -> ProductOffer | None:
    """Parser comun para la plataforma Next.js de Falabella y Sodimac."""
    title = (item.get("displayName") or "").strip()
    if not title:
        return None
    price, reference, card = select_prices(item.get("prices") or [], price_types)
    if not price:
        return None

    brand = (item.get("brand") or "").strip()
    if brand and brand.casefold() not in title.casefold():
        title = f"{brand} {title}"

    price_text = f"CLP {format_clp(price)}"
    if reference and reference > price:
        price_text += f" (normal {format_clp(reference)})"
    if card and card < price:
        price_text += f" (tarjeta {format_clp(card)})"

    labels = [strip_tags(sticker.get("label")) for sticker in item.get("meatStickers") or []]
    labels += [strip_tags(event.get("description")) for event in item.get("events") or []]
    delivery = ", ".join(label for label in labels if label) or "Despacho disponible"

    media = item.get("mediaUrls") or []
    link = item.get("url") or (link_builder(item) if link_builder else None)
    return ProductOffer(
        title=title[:500],
        store=store,
        seller=item.get("sellerName") or None,
        source=source,
        price_text=price_text[:100],
        extracted_price=price,
        currency="CLP",
        delivery=delivery[:500],
        availability="Disponible",  # el listado solo muestra productos vendibles
        rating=to_rating(item.get("rating")),
        reviews=to_count(item.get("totalReviews")),
        link=link,
        thumbnail=media[0] if media and isinstance(media[0], str) else None,
    )


def parse_jsonld_products(html: str, store: str, source: str) -> list[ProductOffer]:
    """Productos desde JSON-LD: bloques Product sueltos o ItemList de Product."""
    products = []
    for block in jsonld_blocks(html):
        if not isinstance(block, dict):
            continue
        if block.get("@type") == "Product":
            products.append(block)
        entity = block.get("mainEntity") if block.get("@type") != "ItemList" else block
        for element in dig(entity, "itemListElement", default=[]) or []:
            item = element.get("item") if isinstance(element, dict) else None
            if isinstance(item, dict) and item.get("@type", "Product") == "Product":
                products.append(item)

    offers = []
    for item in products:
        offer_data = item.get("offers") or {}
        if isinstance(offer_data, list):
            offer_data = offer_data[0] if offer_data else {}
        price = clp_to_float(offer_data.get("price") or offer_data.get("lowPrice"))
        title = (item.get("name") or "").strip()
        if not title or not price:
            continue
        brand = dig(item, "brand", "name") or (item.get("brand") if isinstance(item.get("brand"), str) else "")
        if brand and brand.casefold() not in title.casefold():
            title = f"{brand} {title}"
        image = item.get("image")
        availability = str(offer_data.get("availability") or "")
        offers.append(ProductOffer(
            title=title[:500], store=store, source=source,
            extracted_price=price, price_text=f"CLP {format_clp(price)}",
            currency=offer_data.get("priceCurrency") or "CLP",
            link=item.get("url") or offer_data.get("url"),
            thumbnail=image[0] if isinstance(image, list) and image else image if isinstance(image, str) else None,
            availability="Sin stock" if "OutOfStock" in availability else "Disponible" if availability else None,
            delivery="Despacho disponible",
        ))
    return offers
