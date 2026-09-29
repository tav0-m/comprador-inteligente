"""
Adaptador Easy Chile v2 — plataforma VTEX, precio CLP corregido.
"""
from __future__ import annotations
import json, logging, re, time, random
import requests
from bs4 import BeautifulSoup
from app.adapters.base import SearchAdapter
from app.adapters.playwright_scraper import (playwright_available, scrape_with_playwright, parse_easy_pw)
from app.adapters._price_utils import clp_to_float, to_int
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-CL,es;q=0.9",
    "Referer": "https://www.easy.cl/",
}

_VTEX_ENDPOINTS = [
    ("https://www.easy.cl/api/catalog_system/pub/products/search",
     {"ft": "{q}", "_from": "0", "_to": "{n}", "O": "OrderByScoreDESC"}),
    ("https://www.easy.cl/api/catalog_system/pub/products/search",
     {"fq": "specificationFilter_40:{q}", "_from": "0", "_to": "{n}"}),
]

class EasyAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl": return []
        try:
            return (self._try_vtex(query, max_results)
                    or self._try_playwright(query, max_results)
                    or self._try_html(query, max_results))
        except Exception as exc:
            logger.warning(f"[Easy] Error: {exc}")
            return []

    def _try_vtex(self, query: str, max_results: int) -> list[ProductOffer]:
        """Pagina la API VTEX de Easy en bloques de 24."""
        from app.adapters._pagination import vtex_paginate
        url = "https://www.easy.cl/api/catalog_system/pub/products/search"
        raw = vtex_paginate(
            url=url, query=query,
            max_results=max(max_results, 48),  # mínimo 2 páginas
            headers=_HEADERS, page_size=24,
        )
        if not raw:
            # Intentar con filtro de especificación como fallback
            url2 = "https://www.easy.cl/api/catalog_system/pub/products/search"
            raw = vtex_paginate(
                url=url2,
                query=query,
                max_results=max(max_results, 48),
                headers=_HEADERS,
                extra_params={"fq": f"specificationFilter_40:{query}"},
                page_size=24,
            )
        if not raw:
            return []
        offers = [o for o in (_parse_vtex_item(p) for p in raw) if o]
        logger.info(f"[Easy] VTEX paginado: {len(offers)} resultados")
        return offers


    def _try_playwright(self, query: str, max_results: int) -> list[ProductOffer]:
        if not playwright_available(): return []
        url = "https://www.easy.cl/buscador?q={}".format(requests.utils.quote(query))
        offers = scrape_with_playwright(
            url=url, store="Easy", source="easy",
            parser=parse_easy_pw,
            wait_selector="[class*='vtex-product'], [class*='product'], article",
            timeout_ms=25_000,
        )
        return offers[:max_results]

    def _try_html(self, query: str, max_results: int) -> list[ProductOffer]:
        time.sleep(random.uniform(0.5, 1.0))
        try:
            url = f"https://www.easy.cl/buscador?q={requests.utils.quote(query)}"
            resp = requests.get(url, headers={**_HEADERS, "Accept": "text/html"}, timeout=20)
            if resp.status_code != 200:
                url = f"https://www.easy.cl/{requests.utils.quote(query.replace(' ','-'))}"
                resp = requests.get(url, headers={**_HEADERS, "Accept": "text/html"}, timeout=20)
            if resp.status_code != 200: return []
            soup = BeautifulSoup(resp.text, "html.parser")

            offers = _parse_jsonld_easy(soup)
            if offers:
                logger.info(f"[Easy] HTML JSON-LD: {len(offers)} resultados")
                return offers[:max_results]

            offers = _parse_vtex_script_state(soup)
            if offers:
                logger.info(f"[Easy] HTML script state: {len(offers)} resultados")
                return offers[:max_results]

            offers = _parse_easy_cards(soup)
            if offers:
                logger.info(f"[Easy] HTML cards: {len(offers)} resultados")
                return offers[:max_results]

        except Exception as exc:
            logger.debug(f"[Easy] HTML fallback fallo: {exc}")
        return []


def _parse_vtex_item(item: dict) -> ProductOffer | None:
    try:
        title = (item.get("productName") or item.get("name") or "").strip()
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
        if link and not link.startswith("http"): link = f"https://www.easy.cl/{link}/p"
        images  = item.get("images") or sku.get("images", [])
        thumb   = images[0].get("imageUrl") if images else None
        free_ship = bool(comm.get("DeliverySlaSamplesPerRegion"))
        delivery  = "Envío gratis" if free_ship else "Despacho disponible"
        return ProductOffer(title=title, store="Easy", source="easy",
                            price_text=f"CLP {price:,.0f}",
                            extracted_price=price, currency="CLP",
                            delivery=delivery, availability=avail,
                            rating=clp_to_float(item.get("rating")),
                            reviews=to_int(item.get("totalReviews")),
                            link=link, thumbnail=thumb)
    except Exception:
        return None

def _parse_jsonld_easy(soup: BeautifulSoup) -> list[ProductOffer]:
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
                    link  = item.get("url") or od.get("url")
                    img   = item.get("image")
                    thumb = img[0] if isinstance(img, list) else img
                    if title and price:
                        offers.append(ProductOffer(title=title, store="Easy", source="easy",
                                                   extracted_price=price,
                                                   price_text=f"CLP {price:,.0f}",
                                                   currency="CLP", link=link, thumbnail=thumb,
                                                   delivery="Despacho disponible"))
        except Exception:
            continue
    return offers

def _parse_vtex_script_state(soup: BeautifulSoup) -> list[ProductOffer]:
    offers = []
    for script in soup.find_all("script"):
        text = script.string or ""
        if "productName" not in text and "productTitle" not in text: continue
        matches = re.findall(r'"products"\s*:\s*(\[.{20,}\])', text, re.DOTALL)
        for match in matches[:1]:
            try:
                for p in json.loads(match)[:20]:
                    if isinstance(p, dict):
                        o = _parse_vtex_item(p)
                        if o: offers.append(o)
            except Exception:
                continue
        if offers: break
    return offers

def _parse_easy_cards(soup: BeautifulSoup) -> list[ProductOffer]:
    offers = []
    for card in soup.find_all(["article","div","li"], class_=re.compile(r"product|item|vtex-product"), limit=20):
        title_el = card.find(["h2","h3","span","div"], class_=re.compile(r"name|title|product-name"))
        price_el = card.find(["span","div"], class_=re.compile(r"price|precio"))
        link_el  = card.find("a", href=True)
        img_el   = card.find("img")
        if not title_el: continue
        title    = title_el.get_text(strip=True)
        price_raw = price_el.get_text(strip=True) if price_el else ""
        price    = clp_to_float(price_raw)
        if not price: continue
        link = link_el["href"] if link_el else None
        if link and not link.startswith("http"): link = "https://www.easy.cl" + link
        thumb = img_el.get("src") or img_el.get("data-src") if img_el else None
        if title:
            offers.append(ProductOffer(title=title, store="Easy", source="easy",
                                       extracted_price=price,
                                       price_text=f"CLP {price:,.0f}",
                                       currency="CLP", link=link, thumbnail=thumb,
                                       delivery="Despacho disponible"))
    return offers
