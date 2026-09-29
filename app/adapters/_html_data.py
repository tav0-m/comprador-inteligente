"""Extraccion de datos estructurados embebidos en paginas de busqueda.

Las tiendas chilenas relevantes (Falabella, Sodimac, Easy) renderizan con
Next.js y publican los resultados en <script id="__NEXT_DATA__">; Paris publica
un ItemList en JSON-LD. Leer esos bloques es mas estable y ~100x mas rapido
que un navegador headless o que selectores CSS sobre tarjetas.
"""
from __future__ import annotations

import json
import logging
import re

import requests

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-CL,es;q=0.9",
}

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)
_JSONLD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)


def fetch_html(url: str, params: dict | None = None, store: str = "", timeout: int = 20) -> str | None:
    headers = dict(BROWSER_HEADERS)
    try:
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("[%s] Error de red: %s", store, exc)
        return None
    if response.status_code != 200:
        logger.warning("[%s] HTTP %d en %s", store, response.status_code, response.url)
        return None
    return response.text


def next_data_page_props(html: str) -> dict | None:
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1))["props"]["pageProps"]
    except (ValueError, KeyError, TypeError):
        return None


def jsonld_blocks(html: str) -> list:
    blocks = []
    for raw in _JSONLD_RE.findall(html or ""):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        blocks.extend(data if isinstance(data, list) else [data])
    return blocks


def dig(data, *path, default=None):
    """Acceso seguro a estructuras anidadas: dig(d, "a", "b", 0)."""
    current = data
    for key in path:
        try:
            current = current[key]
        except (KeyError, IndexError, TypeError):
            return default
    return current if current is not None else default


def strip_tags(text: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def format_clp(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")
