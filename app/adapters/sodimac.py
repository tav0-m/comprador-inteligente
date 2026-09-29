"""
Adaptador Sodimac Chile v3 — ATG platform.
Estrategia: API → Playwright (headless) → BeautifulSoup HTML.
"""
from __future__ import annotations
import json, logging, re, time, random
import requests
from bs4 import BeautifulSoup
from app.adapters.base import SearchAdapter
from app.adapters._price_utils import clp_to_float, to_int
from app.adapters.playwright_scraper import (
    playwright_available, scrape_with_playwright, parse_sodimac_pw
)
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-CL,es;q=0.9",
    "Referer": "https://www.sodimac.cl/",
}

_ENDPOINTS = [
    "https://www.sodimac.cl/s/search/product-search/search",
    "https://www.sodimac.cl/s/search/v1/product-search",
]

class SodimacAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl": return []
        try:
            return (self._try_api(query, max_results)
                    or self._try_playwright(query, max_results)
                    or self._try_html(query, max_results))
        except Exception as exc:
            logger.warning(f"[Sodimac] Error: {exc}")
            return []

    def _try_api(self, query: str, max_results: int) -> list[ProductOffer]:
        """Pagina la API ATG de Sodimac con el parámetro No (offset)."""
        from app.adapters._pagination import atg_paginate, MAX_PAGES
        page_size = 24
        target    = max(max_results, page_size * MAX_PAGES)

        for url in _ENDPOINTS:
            for param_key in ["Ntt", "q", "query"]:
                def build_params(offset, _pk=param_key, _ps=page_size):
                    return {_pk: query, "No": offset, "Nrpp": _ps,
                            "zone": "RM", "country": "CL"}
                try:
                    raw = atg_paginate(
                        url=url,
                        query_params_builder=build_params,
                        max_results=target,
                        headers=_HEADERS,
                        page_size=page_size,
                    )
                    if raw:
                        offers = [o for o in (_parse_atg_item(p) for p in raw) if o]
                        if offers:
                            logger.info(f"[Sodimac] ATG paginado ({url}): {len(offers)} resultados")
                            return offers
                except Exception:
                    continue
        return []

    def _try_playwright(self, query: str, max_results: int) -> list[ProductOffer]:
        if not playwright_available(): return []
        url = f"https://www.sodimac.cl/sodimac-cl/search?Ntt={requests.utils.quote(query)}"
        offers = scrape_with_playwright(
            url=url, store="Sodimac", source="sodimac",
            parser=parse_sodimac_pw,
            wait_selector="[class*='product-card'], [class*='pod-'], article",
            timeout_ms=25_000,
        )
        return offers[:max_results]

    def _try_html(self, query: str, max_results: int) -> list[ProductOffer]:
        time.sleep(random.uniform(0.5, 1.0))
        try:
            url  = f"https://www.sodimac.cl/sodimac-cl/search?Ntt={requests.utils.quote(query)}"
            resp = requests.get(url, headers={**_HEADERS, "Accept": "text/html"}, timeout=20)
            if resp.status_code != 200: return []
            soup = BeautifulSoup(resp.text, "html.parser")
            for fn in [_parse_jsonld, _parse_script_state, _parse_cards]:
                offers = fn(soup, "Sodimac", "sodimac")
                if offers:
                    logger.info(f"[Sodimac] HTML {fn.__name__}: {len(offers)} resultados")
                    return offers[:max_results]
        except Exception as exc:
            logger.debug(f"[Sodimac] HTML fallback fallo: {exc}")
        return []


def _parse_atg_item(item: dict) -> ProductOffer | None:
    try:
        title = (item.get("displayName") or item.get("name") or item.get("title") or "").strip()
        if not title: return None
        price = clp_to_float(item.get("price") or item.get("offerPrice") or item.get("normalPrice") or
                              item.get("prices", {}).get("offerPrice") or item.get("prices", {}).get("normalPrice"))
        if not price: return None
        pid   = item.get("productId") or item.get("id") or ""
        link  = item.get("url") or f"https://www.sodimac.cl/sodimac-cl/product/{pid}"
        thumb = item.get("image") or item.get("thumbnailUrl")
        if isinstance(thumb, list): thumb = thumb[0] if thumb else None
        return ProductOffer(title=title, store="Sodimac", source="sodimac",
                            price_text=f"CLP {price:,.0f}", extracted_price=price, currency="CLP",
                            delivery="Despacho disponible",
                            availability=str(item.get("stockType") or ""),
                            rating=clp_to_float(item.get("rating")),
                            reviews=to_int(item.get("ratingsCount")),
                            link=link, thumbnail=thumb)
    except Exception:
        return None

def _parse_jsonld(soup, store, source) -> list[ProductOffer]:
    offers = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data  = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    od    = item.get("offers", {})
                    if isinstance(od, list): od = od[0] if od else {}
                    price = clp_to_float(od.get("price"))
                    title = item.get("name", "")
                    if title and price:
                        offers.append(ProductOffer(title=title, store=store, source=source,
                                                   extracted_price=price, price_text=f"CLP {price:,.0f}",
                                                   currency="CLP", link=item.get("url"),
                                                   thumbnail=None, delivery="Despacho disponible"))
        except Exception: continue
    return offers

def _parse_script_state(soup, store, source) -> list[ProductOffer]:
    offers = []
    for script in soup.find_all("script"):
        text = script.string or ""
        if "products" not in text.lower(): continue
        for match in re.findall(r'"products"\s*:\s*(\[.*?\])', text, re.DOTALL)[:1]:
            try:
                for p in json.loads(match)[:20]:
                    if isinstance(p, dict):
                        o = _parse_atg_item(p)
                        if o: offers.append(o)
            except Exception: continue
        if offers: break
    return offers

def _parse_cards(soup, store, source) -> list[ProductOffer]:
    offers = []
    for tag, attrs in [("div", {"class": re.compile(r"product-card|ProductCard|pod-")}),
                       ("article", {"class": re.compile(r"product|item")}),
                       ("li", {"class": re.compile(r"product|item")})]:
        for card in soup.find_all(tag, attrs, limit=20):
            title_el = card.find(["h2","h3","h4","span"], class_=re.compile(r"title|name|product-name"))
            price_el = card.find(["span","div"], class_=re.compile(r"price|precio"))
            link_el  = card.find("a", href=True)
            img_el   = card.find("img")
            if not title_el: continue
            title = title_el.get_text(strip=True)
            price = clp_to_float(price_el.get_text(strip=True) if price_el else "")
            if not price: continue
            link = link_el["href"] if link_el else None
            if link and not link.startswith("http"): link = "https://www.sodimac.cl" + link
            offers.append(ProductOffer(title=title, store=store, source=source,
                                       extracted_price=price, price_text=f"CLP {price:,.0f}",
                                       currency="CLP", link=link, delivery="Despacho disponible",
                                       thumbnail=(img_el.get("src") or img_el.get("data-src")) if img_el else None))
        if offers: break
    return offers
