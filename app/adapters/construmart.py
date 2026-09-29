"""
Adaptador Construmart Chile — ferretería nacional especializada en construcción.
Plataforma propia. Usa API interna + fallback HTML.
"""
from __future__ import annotations
import json, logging, re, time, random
import requests
from bs4 import BeautifulSoup
from app.adapters.base import SearchAdapter
from app.adapters._price_utils import clp_to_float, to_int
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-CL,es;q=0.9",
    "Referer": "https://www.construmart.cl/",
}

class ConstrumartAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl": return []
        try:
            return self._try_api(query, max_results) or self._try_html(query, max_results)
        except Exception as exc:
            logger.warning(f"[Construmart] Error: {exc}")
            return []

    def _try_api(self, query: str, max_results: int) -> list[ProductOffer]:
        """Pagina la API VTEX de Construmart en bloques de 24."""
        from app.adapters._pagination import vtex_paginate
        url = "https://www.construmart.cl/api/catalog_system/pub/products/search"
        raw = vtex_paginate(
            url=url, query=query,
            max_results=max(max_results, 48),
            headers=_HEADERS, page_size=24,
        )
        if raw:
            offers = [o for o in (_parse_item(p) for p in raw) if o]
            if offers:
                logger.info(f"[Construmart] VTEX paginado: {len(offers)} resultados")
                return offers
        # Fallback: API propia de Construmart
        try:
            import time, random
            time.sleep(random.uniform(0.2, 0.5))
            resp = requests.get("https://api.construmart.cl/v1/products/search",
                                params={"q": query, "limit": str(min(max_results, 20))},
                                headers=_HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else (data.get("products") or data.get("items") or [])
                if items:
                    offers = [o for o in (_parse_item(p) for p in items) if o]
                    if offers:
                        logger.info(f"[Construmart] API propia: {len(offers)} resultados")
                        return offers
        except Exception:
            pass
        return []

    def _try_html(self, query: str, max_results: int) -> list[ProductOffer]:
        time.sleep(random.uniform(0.5, 1.0))
        try:
            url  = f"https://www.construmart.cl/search?q={requests.utils.quote(query)}"
            resp = requests.get(url, headers={**_HEADERS, "Accept": "text/html"}, timeout=20)
            if resp.status_code != 200: return []
            soup = BeautifulSoup(resp.text, "html.parser")

            # JSON-LD
            offers = _parse_jsonld(soup)
            if offers:
                logger.info(f"[Construmart] JSON-LD: {len(offers)} resultados")
                return offers[:max_results]

            # Cards HTML
            offers = _parse_cards(soup)
            if offers:
                logger.info(f"[Construmart] HTML cards: {len(offers)} resultados")
                return offers[:max_results]

        except Exception as exc:
            logger.debug(f"[Construmart] HTML fallo: {exc}")
        return []


def _parse_item(item: dict) -> ProductOffer | None:
    try:
        title = (item.get("productName") or item.get("name") or item.get("title") or "").strip()
        if not title: return None
        # Soporte para estructura VTEX y propia
        skus    = item.get("items", [])
        sku     = skus[0] if skus else {}
        sellers = sku.get("sellers", [])
        seller  = sellers[0] if sellers else {}
        comm    = seller.get("commertialOffer", {})
        price   = clp_to_float(comm.get("Price") or comm.get("ListPrice") or
                                item.get("price") or item.get("offerPrice"))
        if not price: return None
        link  = item.get("link") or item.get("url") or item.get("linkText")
        if link and not link.startswith("http"): link = f"https://www.construmart.cl/{link}/p"
        images = item.get("images") or sku.get("images", [])
        thumb  = (images[0].get("imageUrl") if isinstance(images[0], dict) else images[0]) if images else None
        avail  = "En stock" if (comm.get("AvailableQuantity") or item.get("stock") or 0) > 0 else None
        return ProductOffer(title=title, store="Construmart", source="construmart",
                            price_text=f"CLP {price:,.0f}",
                            extracted_price=price, currency="CLP",
                            delivery="Despacho disponible",
                            availability=avail,
                            link=link, thumbnail=thumb)
    except Exception:
        return None

def _parse_jsonld(soup: BeautifulSoup) -> list[ProductOffer]:
    offers = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data  = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    title = item.get("name", "")
                    od    = item.get("offers", {})
                    if isinstance(od, list): od = od[0] if od else {}
                    price = clp_to_float(od.get("price"))
                    if title and price:
                        offers.append(ProductOffer(title=title, store="Construmart", source="construmart",
                                                   extracted_price=price,
                                                   price_text=f"CLP {price:,.0f}",
                                                   currency="CLP",
                                                   link=item.get("url"),
                                                   thumbnail=None,
                                                   delivery="Despacho disponible"))
        except Exception:
            continue
    return offers

def _parse_cards(soup: BeautifulSoup) -> list[ProductOffer]:
    offers = []
    for card in soup.find_all(["article","div","li"],
                               class_=re.compile(r"product|item|card"), limit=20):
        title_el = card.find(["h2","h3","h4","span","a"],
                              class_=re.compile(r"title|name|product-name|description"))
        price_el = card.find(["span","b","div","p"],
                              class_=re.compile(r"price|precio|valor"))
        link_el  = card.find("a", href=True)
        img_el   = card.find("img")
        if not title_el: continue
        title    = title_el.get_text(strip=True)
        price    = clp_to_float(price_el.get_text(strip=True) if price_el else "")
        if not price: continue
        link  = link_el["href"] if link_el else None
        if link and not link.startswith("http"): link = "https://www.construmart.cl" + link
        thumb = img_el.get("src") or img_el.get("data-src") if img_el else None
        if title:
            offers.append(ProductOffer(title=title, store="Construmart", source="construmart",
                                       extracted_price=price,
                                       price_text=f"CLP {price:,.0f}",
                                       currency="CLP", link=link, thumbnail=thumb,
                                       delivery="Despacho disponible"))
    return offers
