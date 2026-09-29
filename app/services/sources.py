"""Ejecucion en paralelo de las fuentes (tiendas) con metricas por fuente."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass

from app.adapters.construmart import ConstrumartAdapter
from app.adapters.easy import EasyAdapter
from app.adapters.falabella import FalabellaAdapter
from app.adapters.local_csv import LocalCSVAdapter
from app.adapters.mercadolibre import MercadoLibreAdapter
from app.adapters.paris import ParisAdapter
from app.adapters.serpapi_google_shopping import SerpApiGoogleShoppingAdapter
from app.adapters.sodimac import SodimacAdapter
from app.core.config import settings
from app.schemas import ProductOffer

logger = logging.getLogger(__name__)


@dataclass
class SourceRun:
    source: str
    offers: int = 0
    duration_ms: int | None = None
    error: str | None = None


def get_adapters():
    adapters = []
    if settings.enable_serpapi and settings.serpapi_key:
        adapters.append(SerpApiGoogleShoppingAdapter())
    if settings.enable_mercadolibre:
        adapters.append(MercadoLibreAdapter())
    if settings.enable_sodimac:
        adapters.append(SodimacAdapter())
    if settings.enable_easy:
        adapters.append(EasyAdapter())
    if settings.enable_falabella:
        adapters.append(FalabellaAdapter())
    if settings.enable_paris:
        adapters.append(ParisAdapter())
    if settings.enable_construmart:
        adapters.append(ConstrumartAdapter())
    if settings.enable_local_csv:
        adapters.append(LocalCSVAdapter())
    return adapters


def source_name(adapter) -> str:
    return adapter.__class__.__name__.removesuffix("Adapter").lower()


def fetch_live_offers(query: str, country: str, limit: int) -> tuple[list[ProductOffer], list[SourceRun]]:
    """Consulta todas las fuentes habilitadas en paralelo, con timeout global."""
    adapters = get_adapters()
    runs = {source_name(adapter): SourceRun(source_name(adapter)) for adapter in adapters}
    offers: list[ProductOffer] = []

    def run_adapter(adapter):
        run = runs[source_name(adapter)]
        started = time.perf_counter()
        try:
            return adapter.search(query=query, country=country, max_results=limit)
        except Exception as exc:
            run.error = str(exc)[:300]
            logger.warning("[%s] fallo: %s", run.source, exc)
            return []
        finally:
            run.duration_ms = round((time.perf_counter() - started) * 1000)

    if not adapters:
        return offers, []
    executor = ThreadPoolExecutor(max_workers=len(adapters), thread_name_prefix="store")
    futures = {executor.submit(run_adapter, adapter): source_name(adapter) for adapter in adapters}
    done, pending = wait(futures, timeout=settings.search_timeout_seconds)
    for future in done:
        results = future.result() or []
        runs[futures[future]].offers = len(results)
        offers.extend(results)
    for future in pending:
        future.cancel()
        runs[futures[future]].error = "timeout global de busqueda"
    executor.shutdown(wait=False, cancel_futures=True)
    if pending:
        logger.warning("[Sources] %d fuentes excedieron el timeout global.", len(pending))
    return offers, list(runs.values())
