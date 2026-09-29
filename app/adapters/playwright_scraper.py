"""
Playwright Scraper — navegador headless real para tiendas con JavaScript.

Sodimac, Easy y Falabella renderizan con React/JS. BeautifulSoup no puede
leer su contenido. Este módulo abre un Chrome headless, espera que el DOM
cargue completamente y extrae los productos reales.

Instalación (una sola vez):
    pip install playwright
    playwright install chromium

Si Playwright no está instalado, el scraper retorna [] silenciosamente
y los adaptadores caen al modo BeautifulSoup de siempre.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
import threading
from typing import Callable
from app.adapters._price_utils import clp_to_float, to_int
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)

# Flag global: se comprueba una vez al importar
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False
    logger.info("[Playwright] No instalado — usando BeautifulSoup como fallback.")


def playwright_available() -> bool:
    return _PLAYWRIGHT_OK


def scrape_with_playwright(
    url: str,
    store: str,
    source: str,
    parser: Callable,           # función que recibe el HTML y devuelve list[ProductOffer]
    wait_selector: str = "body",
    timeout_ms: int = 20_000,
) -> list[ProductOffer]:
    """
    Abre `url` en Chrome headless, espera `wait_selector` y llama `parser(html)`.
    Ejecuta Playwright en un hilo separado con su propio event loop para evitar
    el conflicto con el event loop de asyncio de FastAPI/uvicorn en Windows.
    Retorna [] si Playwright no está instalado o si hay cualquier error.
    """
    if not _PLAYWRIGHT_OK:
        return []

    results: list[ProductOffer] = []
    error_holder: list[str] = []

    def _run_in_thread():
        # Crear un event loop propio para este hilo —
        # evita el NotImplementedError de asyncio en Windows cuando
        # sync_playwright() intenta crear subprocesos dentro del loop de uvicorn.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ],
                )
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0.0.0 Safari/537.36",
                    locale="es-CL",
                    viewport={"width": 1280, "height": 900},
                )
                page = ctx.new_page()

                # Bloquear recursos pesados para acelerar la carga
                page.route(
                    "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3}",
                    lambda route: route.abort()
                )

                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                # Esperar que aparezcan productos (selector flexible)
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms // 2)
                except PWTimeout:
                    logger.debug(
                        f"[Playwright:{store}] Timeout esperando '{wait_selector}', extrayendo igual."
                    )

                # ── Scroll infinito + clic en "Ver más" ──────────────────────
                # Muchas tiendas usan lazy-loading o paginación por scroll/botón.
                # Hacemos hasta 5 ciclos: scroll al fondo → esperar carga → intentar
                # clic en botón "Ver más" → comparar altura anterior vs nueva.
                _infinite_scroll(page, max_cycles=5, wait_ms=1800)

                html = page.content()
                browser.close()

            offers = parser(html, store, source)
            results.extend(offers)
            logger.info(f"[Playwright:{store}] {len(offers)} productos extraídos de {url}")

        except Exception as exc:
            error_holder.append(str(exc))
        finally:
            loop.close()

    t = threading.Thread(target=_run_in_thread, daemon=True)
    t.start()
    # Esperar hasta timeout_ms + 10 segundos de margen
    t.join(timeout=(timeout_ms / 1000) + 10)

    if t.is_alive():
        logger.warning(f"[Playwright:{store}] Timeout: hilo no terminó a tiempo.")
    elif error_holder:
        logger.warning(f"[Playwright:{store}] Error en hilo: {error_holder[0]}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Scroll infinito
# ─────────────────────────────────────────────────────────────────────────────

# Selectores de botón "cargar más" que usan las tiendas chilenas
_LOAD_MORE_SELECTORS = [
    "button[class*='load-more']",
    "button[class*='loadMore']",
    "button[class*='ver-mas']",
    "button[class*='verMas']",
    "a[class*='load-more']",
    "[data-testid='load-more']",
    "button:has-text('Ver más')",
    "button:has-text('Cargar más')",
    "button:has-text('Mostrar más')",
    "button:has-text('Ver todos')",
    ".show-more",
    ".load-more",
]


def _infinite_scroll(page, max_cycles: int = 5, wait_ms: int = 1800) -> None:
    """
    Hace scroll hasta el fondo de la página en bucle para activar lazy-load
    y hace clic en botones "Ver más" / "Cargar más" si aparecen.

    Se detiene cuando:
    - Se alcanza max_cycles
    - La altura de la página no cambia después de un scroll (ya llegó al fondo)
    - No hay más productos nuevos
    """
    prev_height = 0

    for cycle in range(max_cycles):
        # Scroll gradual: primero a 50%, luego al 100%
        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
        page.wait_for_timeout(wait_ms // 3)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(wait_ms)

        # Intentar clic en botón "Ver más" o "Cargar más"
        clicked = False
        for selector in _LOAD_MORE_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    page.wait_for_timeout(wait_ms)
                    clicked = True
                    logger.debug(f"[Playwright] Clic en '{selector}' (ciclo {cycle+1})")
                    break
            except Exception:
                continue

        # Comprobar si la página creció (hay contenido nuevo)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == prev_height and not clicked:
            logger.debug(f"[Playwright] Sin cambio en altura tras ciclo {cycle+1} — fin de scroll")
            break
        prev_height = new_height

    # Scroll final al fondo para asegurar última carga
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(800)


# ─────────────────────────────────────────────────────────────────────────────
# Parsers por tienda
# ─────────────────────────────────────────────────────────────────────────────

def parse_sodimac_pw(html: str, store: str = "Sodimac", source: str = "sodimac") -> list[ProductOffer]:
    """Extrae productos del HTML renderizado de Sodimac."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    offers = []

    # Intentar JSON embebido en __NEXT_DATA__ o window.__INITIAL_STATE__
    for script in soup.find_all("script", id="__NEXT_DATA__"):
        try:
            data = json.loads(script.string or "")
            products = _deep_find_products(data)
            for p in products[:20]:
                o = _parse_generic_item(p, store, source)
                if o: offers.append(o)
            if offers:
                return offers
        except Exception:
            pass

    # Fallback: product cards
    for card in soup.find_all(["article", "div"],
                               class_=re.compile(r"product-card|ProductCard|pod-|vtex-product"), limit=25):
        title_el = card.find(["h2", "h3", "h4", "span"],
                              class_=re.compile(r"title|name|product-name|displayName"))
        price_el = card.find(["span", "b", "div"],
                              class_=re.compile(r"price|precio|offer"))
        link_el  = card.find("a", href=True)
        img_el   = card.find("img")
        if not title_el: continue
        title = title_el.get_text(strip=True)
        price = clp_to_float(price_el.get_text(strip=True) if price_el else "")
        if not price or not title: continue
        link  = link_el["href"] if link_el else None
        if link and not link.startswith("http"): link = "https://www.sodimac.cl" + link
        thumb = (img_el.get("src") or img_el.get("data-src")) if img_el else None
        offers.append(ProductOffer(title=title, store=store, source=source,
                                   price_text=f"CLP {price:,.0f}", extracted_price=price,
                                   currency="CLP", link=link, thumbnail=thumb,
                                   delivery="Despacho disponible"))
    return offers


def parse_easy_pw(html: str, store: str = "Easy", source: str = "easy") -> list[ProductOffer]:
    """Extrae productos del HTML renderizado de Easy."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    offers = []

    # JSON-LD primero
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data  = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    price = clp_to_float(
                        (item.get("offers", {}) if isinstance(item.get("offers"), dict)
                         else (item.get("offers") or [{}])[0]).get("price")
                    )
                    title = item.get("name", "")
                    if title and price:
                        offers.append(ProductOffer(
                            title=title, store=store, source=source,
                            price_text=f"CLP {price:,.0f}", extracted_price=price,
                            currency="CLP", link=item.get("url"), thumbnail=None,
                            delivery="Despacho disponible"))
        except Exception:
            pass
    if offers: return offers

    # VTEX state
    for script in soup.find_all("script"):
        text = script.string or ""
        if "productName" not in text: continue
        for match in re.findall(r'"products"\s*:\s*(\[.{20,}\])', text, re.DOTALL)[:1]:
            try:
                for p in json.loads(match)[:20]:
                    o = _parse_generic_item(p, store, source)
                    if o: offers.append(o)
            except Exception:
                pass
        if offers: return offers

    return offers


def parse_falabella_pw(html: str, store: str = "Falabella", source: str = "falabella") -> list[ProductOffer]:
    """Extrae productos del HTML renderizado de Falabella."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    offers = []

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data  = json.loads(script.string or "")
            for item in (data if isinstance(data, list) else [data]):
                if item.get("@type") == "Product":
                    od    = item.get("offers", {})
                    if isinstance(od, list): od = od[0] if od else {}
                    price = clp_to_float(od.get("price"))
                    title = item.get("name", "")
                    if title and price:
                        offers.append(ProductOffer(
                            title=title, store=store, source=source,
                            price_text=f"CLP {price:,.0f}", extracted_price=price,
                            currency="CLP", link=item.get("url"), thumbnail=None,
                            delivery="Despacho disponible"))
        except Exception:
            pass
    if offers: return offers

    # Script con displayName
    for script in soup.find_all("script"):
        text = script.string or ""
        if "displayName" not in text: continue
        for pattern in [r'"results"\s*:\s*(\[.{20,}\])', r'"products"\s*:\s*(\[.{20,}\])']:
            for match in re.findall(pattern, text, re.DOTALL)[:1]:
                try:
                    for p in json.loads(match)[:20]:
                        o = _parse_generic_item(p, store, source)
                        if o: offers.append(o)
                except Exception:
                    pass
        if offers: return offers

    return offers


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_generic_item(item: dict, store: str, source: str) -> ProductOffer | None:
    try:
        title = (item.get("displayName") or item.get("productName") or
                 item.get("name") or item.get("title") or "").strip()
        if not title: return None

        # Intentar extraer precio de múltiples lugares
        raw_price = (
            item.get("price") or item.get("offerPrice") or
            item.get("prices", {}).get("offerPrice") or item.get("prices", {}).get("normalPrice") or
            _vtex_price(item)
        )
        price = clp_to_float(raw_price)
        if not price: return None

        pid   = item.get("productId") or item.get("id") or ""
        link  = item.get("url") or item.get("link") or item.get("permalink")
        if link and not link.startswith("http"):
            base = {"sodimac": "https://www.sodimac.cl",
                    "easy":    "https://www.easy.cl",
                    "falabella": "https://www.falabella.com"}.get(source, "")
            link = base + link

        media = item.get("mediaUrls") or item.get("images") or []
        thumb = media[0] if media and isinstance(media[0], str) else None

        return ProductOffer(title=title, store=store, source=source,
                            price_text=f"CLP {price:,.0f}", extracted_price=price,
                            currency="CLP", link=link, thumbnail=thumb,
                            delivery="Despacho disponible",
                            rating=clp_to_float(item.get("rating") or item.get("ratingValue")),
                            reviews=to_int(item.get("ratingsCount") or item.get("reviewCount")))
    except Exception:
        return None


def _vtex_price(item: dict) -> float | None:
    """Extrae precio de estructura VTEX sellers/commertialOffer."""
    try:
        skus    = item.get("items", [])
        sku     = skus[0] if skus else {}
        sellers = sku.get("sellers", [])
        seller  = sellers[0] if sellers else {}
        comm    = seller.get("commertialOffer", {})
        return comm.get("Price") or comm.get("ListPrice")
    except Exception:
        return None


def _deep_find_products(data, depth: int = 0) -> list:
    """Busca recursivamente arrays de productos en JSON anidado."""
    if depth > 5: return []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if any(k in data[0] for k in ("displayName", "productName", "name", "title")):
            return data
    if isinstance(data, dict):
        for key in ("products", "results", "items", "data"):
            val = data.get(key)
            if val:
                found = _deep_find_products(val, depth + 1)
                if found: return found
        for v in data.values():
            if isinstance(v, (dict, list)):
                found = _deep_find_products(v, depth + 1)
                if found: return found
    return []
