"""Resultados progresivos de busqueda mediante Server-Sent Events (SSE)."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Generator

from app.core.config import settings
from app.schemas import ProductOffer
from app.services.buyer_service import get_adapters, process_offers, summarize_offers
from app.services.normalizer import normalize_offer

logger = logging.getLogger(__name__)


def _offer_to_dict(offer: ProductOffer) -> dict:
    return offer.model_dump(mode="json")


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def search_stream(
    query: str,
    country: str = "cl",
    max_results: int = 20,
) -> Generator[str, None, None]:
    """Emite un avance por fuente y finalmente una comparacion consolidada."""
    adapters = get_adapters()
    adapter_limit = max(max_results * 3, 72)
    all_offers: list[ProductOffer] = []

    yield _sse_event(
        {
            "type": "start",
            "stores": [a.__class__.__name__.replace("Adapter", "") for a in adapters],
            "query": query,
        }
    )

    if not adapters:
        yield _sse_event(
            {
                "type": "done",
                "total": 0,
                "best_price": None,
                "avg_price": None,
                "offers": [],
            }
        )
        return

    def _run_adapter(adapter):
        store = adapter.__class__.__name__.replace("Adapter", "")
        try:
            return store, adapter.search(
                query=query,
                country=country,
                max_results=adapter_limit,
            )
        except Exception as exc:
            logger.warning("[SSE] %s fallo: %s", store, exc)
            return store, []

    executor = ThreadPoolExecutor(max_workers=len(adapters))
    futures = {executor.submit(_run_adapter, adapter) for adapter in adapters}
    try:
        for future in as_completed(futures, timeout=settings.search_timeout_seconds):
            store_name, results = future.result()
            normalized = [normalize_offer(offer) for offer in results]
            valid = [offer for offer in normalized if offer.extracted_price is not None]
            all_offers.extend(valid)
            yield _sse_event(
                {
                    "type": "store_result",
                    "store": store_name,
                    "count": len(valid),
                    "offers": [_offer_to_dict(offer) for offer in valid[:10]],
                }
            )
    except TimeoutError:
        logger.warning("[SSE] Tiempo global de busqueda agotado")
        yield _sse_event({"type": "warning", "message": "Algunas fuentes no respondieron a tiempo."})
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    try:
        ranked = process_offers(query, all_offers)
        final = ranked[:max_results]
        stats = summarize_offers(ranked)
        yield _sse_event(
            {
                "type": "done",
                "total": len(final),
                **stats,
                "offers": [_offer_to_dict(offer) for offer in final],
            }
        )
    except Exception:
        logger.exception("[SSE] Fallo el postprocesamiento")
        yield _sse_event(
            {"type": "error", "message": "No se pudo consolidar la busqueda."}
        )
