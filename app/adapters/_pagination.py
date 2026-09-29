"""
Helpers de paginación reutilizables para los adaptadores.

Cada tienda tiene su propio formato de paginación:
- VTEX   → _from / _to  (Easy, Paris, Construmart)
- ATG    → No / Nrpp    (Sodimac)
- Offset → page / rows  (Falabella)
- ML     → offset / limit (MercadoLibre)

El helper `paginate_requests` abstrae el loop y devuelve una lista
acumulada de dicts crudos (JSON) respetando el límite total pedido.
"""
from __future__ import annotations
import logging
import time
import random
from typing import Callable

import requests

logger = logging.getLogger(__name__)

# Máximo de páginas por adaptador para mantener tiempos razonables.
# 3 páginas × ~24 productos = ~72 productos por tienda como máximo.
MAX_PAGES = 3


def vtex_paginate(
    url: str,
    query: str,
    max_results: int,
    headers: dict,
    extra_params: dict | None = None,
    page_size: int = 24,
    timeout: int = 15,
) -> list[dict]:
    """
    Pagina una API VTEX usando _from / _to.
    Retorna lista de items JSON crudos.
    """
    collected: list[dict] = []
    pages = min(MAX_PAGES, -(-max_results // page_size))  # ceil division

    for page in range(pages):
        from_idx = page * page_size
        to_idx   = from_idx + page_size - 1
        params   = {"ft": query, "_from": str(from_idx), "_to": str(to_idx),
                    "O": "OrderByScoreDESC"}
        if extra_params:
            params.update(extra_params)
        try:
            time.sleep(random.uniform(0.15, 0.4))
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data if isinstance(data, list) else (data.get("products") or data.get("items") or [])
            if not items:
                break  # no hay más resultados
            collected.extend(items)
            logger.debug(f"[vtex_paginate] Página {page+1}: +{len(items)} items (total {len(collected)})")
            if len(items) < page_size:
                break  # última página
        except Exception as exc:
            logger.debug(f"[vtex_paginate] Error página {page+1}: {exc}")
            break

    return collected[:max_results]


def atg_paginate(
    url: str,
    query_params_builder: Callable[[int], dict],
    max_results: int,
    headers: dict,
    page_size: int = 24,
    timeout: int = 15,
) -> list[dict]:
    """
    Pagina una API ATG (Sodimac) usando No (offset) / Nrpp (page size).
    `query_params_builder(offset)` devuelve el dict de params para esa página.
    """
    collected: list[dict] = []
    pages = min(MAX_PAGES, -(-max_results // page_size))

    for page in range(pages):
        offset = page * page_size
        params = query_params_builder(offset)
        try:
            time.sleep(random.uniform(0.15, 0.4))
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                break
            data  = resp.json()
            items = (data.get("products") or data.get("results") or
                     data.get("data", {}).get("products") or [])
            if not items:
                break
            collected.extend(items)
            logger.debug(f"[atg_paginate] Página {page+1}: +{len(items)} items (total {len(collected)})")
            if len(items) < page_size:
                break
        except Exception as exc:
            logger.debug(f"[atg_paginate] Error página {page+1}: {exc}")
            break

    return collected[:max_results]


def offset_paginate(
    url: str,
    base_params: dict,
    offset_key: str,
    limit_key: str,
    max_results: int,
    headers: dict,
    results_key: str = "results",
    page_size: int = 50,
    timeout: int = 20,
) -> list[dict]:
    """
    Pagina APIs con offset explícito (MercadoLibre, Falabella).
    `offset_key` = nombre del param de offset, `limit_key` = nombre del param de tamaño.
    """
    collected: list[dict] = []
    pages = min(MAX_PAGES, -(-max_results // page_size))

    for page in range(pages):
        params = dict(base_params)
        params[limit_key]  = str(page_size)
        params[offset_key] = str(page * page_size)
        try:
            time.sleep(random.uniform(0.15, 0.4))
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code not in (200, 206):
                break
            data  = resp.json()
            items = (data.get(results_key) or data.get("items") or
                     data.get("products") or (data if isinstance(data, list) else []))
            if not items:
                break
            collected.extend(items)
            logger.debug(f"[offset_paginate] Página {page+1}: +{len(items)} items (total {len(collected)})")
            if len(items) < page_size:
                break
        except Exception as exc:
            logger.debug(f"[offset_paginate] Error página {page+1}: {exc}")
            break

    return collected[:max_results]
