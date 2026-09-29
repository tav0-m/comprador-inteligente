"""
Adaptador Falabella Chile v2 — precio CLP corregido + filtro de valores absurdos.
"""
from __future__ import annotations
import json, logging, re, time, random
import requests
from bs4 import BeautifulSoup
from app.adapters.base import SearchAdapter
from app.adapters.playwright_scraper import (playwright_available, scrape_with_playwright, parse_falabella_pw)
from app.adapters._price_utils import clp_to_float, to_int
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-CL,es;q=0.9",
    "Referer": "https://www.falabella.com/falabella-cl/",
}

_API_ENDPOINTS = [
    "https://www.falabella.com/s/browse/v1/listing/cl",
    "https://www.falabella.com/falabella-cl/search/api/listing",
]

class FalabellaAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if country.lower() != "cl": return []
        try:
            return (self._try_api(query, max_results)
                    or self._try_playwright(query, max_results)
                    or self._try_html(query, max_results))
        except Exception as exc:
            logger.warning(f"[Falabella] Error: {exc}")
            return []

    def _try_api(self, query: str, max_results: int) -> list[ProductOffer]:
        """Pagina la API de Falabella usando el parámetro page (1-based)."""
        from app.adapters._pagination import MAX_PAGES
        page_size = 20
        target    = max(max_results, page_size * MAX_PAGES)
        collected: list[dict] = []

        for url in _API_ENDPOINTS:
            collected = []
            # Falabella usa page=1,2,3 con rows fijo
            param_key_sets = [
                {"searchTerm": query, "rows": str(page_size), "sortBy": "CLOSEST_TO_IDEAL"},
                {"Ntt": query, "Nrpp": str(page_size)},
                {"q": query, "size": str(page_size)},
            ]
            for base_params in param_key_sets:
                for page_num in range(1, MAX_PAGES + 1):
                    params = dict(base_params)
                    # Adaptar el parámetro de página según el formato
                    if "searchTerm" in params or "q" in params:
                        params["page"] = str(page_num)
                    elif "Ntt" in params:
                        params["No"] = str((page_num - 1) * page_size)
                    try:
                        time.sleep(random.uniform(0.2, 0.5))
                        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
                        if resp.status_code != 200:
                            break
                        data = resp.json()
                        items = (data.get("results") or data.get("data", {}).get("results") or
                                 data.get("products") or data.get("items") or [])
                        if not items:
                            break
                        collected.extend(items)
                        logger.debug(f"[Falabella] Página {page_num}: +{len(items)} items")
                        if len(items) < page_size:
                            break
                        if len(collected) >= target:
                            break
                    except Exception:
                        break
                if collected:
                    break
            if collected:
                break

        if not collected:
            return []
        offers = [o for o in (_parse_fal_item(r) for r in collected[:target]) if o]
        if offers:
            logger.info(f"[Falabella] API paginada: {len(offers)} resultados")
        return offers


    def _try_playwright(self, query: str, max_results: int) -> list[ProductOffer]:
        if not playwright_available(): return []
        url = "https://www.falabella.com/falabella-cl/search?Ntt={}".format(requests.utils.quote(query))
        offers = scrape_with_playwright(
            url=url, store="Falabella", source="falabella",
            parser=parse_falabella_pw,
            wait_selector="[class*='product'], [class*='pod'], article",
            timeout_ms=25_000,
        )
        return offers[:max_results]

    def _try_html(self, query: str, max_results: int) -> list[ProductOffer]:
        time.sleep(random.uniform(0.5, 1.0))
        try:
            url = f"https://www.falabella.com/falabella-cl/search?Ntt={requests.utils.quote(query)}"
            resp = requests.get(url, headers={**_HEADERS, "Accept": "text/html"}, timeout=20)
            if resp.status_code != 200: return []
            soup = BeautifulSoup(resp.text, "html.parser")

            offers = _parse_jsonld_fal(soup)
            if offers:
                logger.info(f"[Falabella] HTML JSON-LD: {len(offers)} resultados")
                return offers[:max_results]

            offers = _parse_fal_script(soup)
            if offers:
                logger.info(f"[Falabella] HTML script: {len(offers)} resultados")
                return offers[:max_results]

            offers = _parse_fal_cards(soup)
            if offers:
                logger.info(f"[Falabella] HTML cards: {len(offers)} resultados")
                return offers[:max_results]

        except Exception as exc:
            logger.debug(f"[Falabella] HTML fallback fallo: {exc}")
        return []


def _parse_fal_item(item: dict) -> ProductOffer | None:
    try:
        title = (item.get("displayName") or item.get("name") or item.get("title") or "").strip()
        if not title: return None
        prices = item.get("prices") or {}
        price = clp_to_float(prices.get("offerPrice") or prices.get("normalPrice") or
                              item.get("price") or item.get("offerPrice"))
        if not price: return None  # sin precio válido, no incluir
        pid = item.get("productId") or item.get("id") or ""
        link = item.get("url") or f"https://www.falabella.com/falabella-cl/product/{pid}"
        media = item.get("mediaUrls") or item.get("images") or []
        thumb = media[0] if media and isinstance(media[0], str) else None
        avail = "En stock" if item.get("inStock") or item.get("available") else None
        shipping = item.get("shipping") or {}
        delivery = "Envío gratis" if (shipping.get("freeShipping") or item.get("freeShipping")) else "Despacho disponible"
        return ProductOffer(title=title, store="Falabella", source="falabella",
                            price_text=f"CLP {price:,.0f}",
                            extracted_price=price, currency="CLP",
                            delivery=delivery, availability=avail,
                            rating=clp_to_float(item.get("rating") or item.get("ratingValue")),
                            reviews=to_int(item.get("ratingsCount") or item.get("reviewCount")),
                            link=link, thumbnail=thumb)
    except Exception:
        return None

def _parse_jsonld_fal(soup: BeautifulSoup) -> list[ProductOffer]:
    offers = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            for item in (data if isinstance(data, list) else [data]):
                if item.get("@type") == "Product":
                    title = item.get("name", "")
                    od = item.get("offers", {})
                    if isinstance(od, list): od = od[0] if od else {}
                    price = clp_to_float(od.get("price"))
                    link = item.get("url") or od.get("url")
                    img = item.get("image")
                    thumb = img[0] if isinstance(img, list) else img
                    if title and price:
                        offers.append(ProductOffer(title=title, store="Falabella", source="falabella",
                                                   extracted_price=price,
                                                   price_text=f"CLP {price:,.0f}",
                                                   currency="CLP", link=link, thumbnail=thumb,
                                                   delivery="Despacho disponible"))
        except Exception:
            continue
    return offers

def _parse_fal_script(soup: BeautifulSoup) -> list[ProductOffer]:
    for script in soup.find_all("script"):
        text = script.string or ""
        if "displayName" not in text and "productId" not in text: continue
        for pattern in [r'"results"\s*:\s*(\[.{20,}\])', r'"products"\s*:\s*(\[.{20,}\])']:
            for match in re.findall(pattern, text, re.DOTALL)[:1]:
                try:
                    offers = [o for o in (_parse_fal_item(p) for p in json.loads(match)[:20]) if o]
                    if offers: return offers
                except Exception:
                    continue
    return []

def _parse_fal_cards(soup: BeautifulSoup) -> list[ProductOffer]:
    offers = []
    for card in soup.find_all(["article","div"], class_=re.compile(r"product|ProductCard|pod"), limit=20):
        title_el = card.find(["h2","h3","b","span"], class_=re.compile(r"title|name|description"))
        price_el = card.find(["span","b","div"], class_=re.compile(r"price|precio|offer"))
        link_el  = card.find("a", href=True)
        img_el   = card.find("img")
        if not title_el: continue
        title    = title_el.get_text(strip=True)
        price_raw = price_el.get_text(strip=True) if price_el else ""
        price    = clp_to_float(price_raw)  # usa el parser robusto directamente
        if not price: continue  # rechazar si precio inválido o fuera de rango
        link = link_el["href"] if link_el else None
        if link and not link.startswith("http"): link = "https://www.falabella.com" + link
        thumb = img_el.get("src") or img_el.get("data-src") if img_el else None
        if title:
            offers.append(ProductOffer(title=title, store="Falabella", source="falabella",
                                       extracted_price=price,
                                       price_text=f"CLP {price:,.0f}",
                                       currency="CLP", link=link, thumbnail=thumb,
                                       delivery="Despacho disponible"))
    return offers
