"""
Adaptador Paris Chile (Cencosud) — plataforma VTEX.
Tienda con materiales, herramientas, hogar.
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
    "Referer": "https://www.paris.cl/",
}

class ParisAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl": return []
        try:
            return self._try_vtex(query, max_results) or self._try_html(query, max_results)
        except Exception as exc:
            logger.warning(f"[Paris] Error: {exc}")
            return []

    def _try_vtex(self, query: str, max_results: int) -> list[ProductOffer]:
        """Pagina la API VTEX de Paris en bloques de 24."""
        from app.adapters._pagination import vtex_paginate
        url = "https://www.paris.cl/api/catalog_system/pub/products/search"
        raw = vtex_paginate(
            url=url, query=query,
            max_results=max(max_results, 48),
            headers=_HEADERS, page_size=24,
        )
        if not raw:
            return []
        offers = [o for o in (_parse_paris_item(p) for p in raw) if o]
        logger.info(f"[Paris] VTEX paginado: {len(offers)} resultados")
        return offers

    def _try_html(self, query: str, max_results: int) -> list[ProductOffer]:
        time.sleep(random.uniform(0.5, 1.0))
        try:
            url  = f"https://www.paris.cl/search?q={requests.utils.quote(query)}&map=ft"
            resp = requests.get(url, headers={**_HEADERS, "Accept": "text/html"}, timeout=20)
            if resp.status_code != 200: return []
            soup = BeautifulSoup(resp.text, "html.parser")

            offers = _parse_jsonld(soup)
            if offers:
                logger.info(f"[Paris] JSON-LD: {len(offers)} resultados")
                return offers[:max_results]

            offers = _parse_vtex_state(soup)
            if offers:
                logger.info(f"[Paris] script state: {len(offers)} resultados")
                return offers[:max_results]

        except Exception as exc:
            logger.debug(f"[Paris] HTML fallo: {exc}")
        return []


def _parse_paris_item(item: dict) -> ProductOffer | None:
    try:
        title   = (item.get("productName") or item.get("name") or "").strip()
        if not title: return None
        skus    = item.get("items", [])
        sku     = skus[0] if skus else {}
        sellers = sku.get("sellers", [])
        seller  = sellers[0] if sellers else {}
        comm    = seller.get("commertialOffer", {})
        price   = clp_to_float(comm.get("Price") or comm.get("ListPrice"))
        if not price: return None
        avail   = "En stock" if (comm.get("AvailableQuantity") or 0) > 0 else "Sin stock"
        link    = item.get("link") or item.get("linkText")
        if link and not link.startswith("http"): link = f"https://www.paris.cl/{link}/p"
        images  = item.get("images") or sku.get("images", [])
        thumb   = images[0].get("imageUrl") if images else None
        free_ship = bool(comm.get("DeliverySlaSamplesPerRegion"))
        return ProductOffer(title=title, store="Paris", source="paris",
                            price_text=f"CLP {price:,.0f}",
                            extracted_price=price, currency="CLP",
                            delivery="Envío gratis" if free_ship else "Despacho disponible",
                            availability=avail,
                            rating=clp_to_float(item.get("rating")),
                            reviews=to_int(item.get("totalReviews")),
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
                        offers.append(ProductOffer(title=title, store="Paris", source="paris",
                                                   extracted_price=price,
                                                   price_text=f"CLP {price:,.0f}",
                                                   currency="CLP",
                                                   link=item.get("url") or od.get("url"),
                                                   thumbnail=None,
                                                   delivery="Despacho disponible"))
        except Exception:
            continue
    return offers

def _parse_vtex_state(soup: BeautifulSoup) -> list[ProductOffer]:
    offers = []
    for script in soup.find_all("script"):
        text = script.string or ""
        if "productName" not in text: continue
        for match in re.findall(r'"products"\s*:\s*(\[.{20,}\])', text, re.DOTALL)[:1]:
            try:
                for p in json.loads(match)[:20]:
                    if isinstance(p, dict):
                        o = _parse_paris_item(p)
                        if o: offers.append(o)
            except Exception:
                continue
        if offers: break
    return offers
