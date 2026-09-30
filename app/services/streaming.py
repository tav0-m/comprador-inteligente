"""Resultados progresivos de busqueda mediante Server-Sent Events (SSE).

Si el catalogo propio tiene la consulta fresca, responde de inmediato desde la
base; si no, emite un avance por tienda y guarda el resultado en el catalogo
(igual que /search), de modo que las busquedas en vivo alimentan la serie diaria.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas import ProductOffer
from app.services.buyer_service import (
    load_catalog_offers, update_catalog, get_adapters, process_offers, summarize_offers,
)
from app.services.normalizer import normalize_offer
from app.services.sources import SourceRun, source_name

logger = logging.getLogger(__name__)


def _offer_to_dict(offer: ProductOffer) -> dict:
    return offer.model_dump(mode="json")


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _display_name(adapter) -> str:
    return adapter.__class__.__name__.replace("Adapter", "")


def _done_event(query: str, offers: list[ProductOffer], max_results: int, source: str, as_of: datetime) -> dict:
    ranked = process_offers(query, offers)
    final = ranked[:max_results]
    return {
        "type": "done",
        "total": len(final),
        **summarize_offers(ranked),
        "data_source": source,
        "data_as_of": as_of.isoformat(),
        "offers": [_offer_to_dict(offer) for offer in final],
    }


def search_stream(
    query: str,
    country: str = "cl",
    max_results: int = 20,
    session_factory: Callable[[], Session] | None = None,
) -> Generator[str, None, None]:
    """Emite un avance por fuente y finalmente una comparacion consolidada."""
    if session_factory is None:
        from app.database import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    try:
        cached = load_catalog_offers(db, query)
        if cached:
            offers, as_of = cached
            yield _sse_event({"type": "start", "stores": [], "query": query, "data_source": "catalog"})
            try:
                event = _done_event(query, offers, max_results, "catalog", as_of)
            except Exception:
                logger.exception("[SSE] Fallo el postprocesamiento del catalogo")
                yield _sse_event({"type": "error", "message": "No se pudo consolidar la busqueda."})
                return
            update_catalog(db, query, offers, [], live=False)  # registra la demanda
            yield _sse_event(event)
            return
        yield from _live_stream(db, query, country, max_results)
    finally:
        db.close()


def _live_stream(db: Session, query: str, country: str, max_results: int) -> Generator[str, None, None]:
    adapters = get_adapters()
    adapter_limit = max(max_results * 3, 72)
    all_offers: list[ProductOffer] = []
    runs = {source_name(adapter): SourceRun(source_name(adapter)) for adapter in adapters}

    yield _sse_event(
        {"type": "start", "stores": [_display_name(a) for a in adapters], "query": query, "data_source": "live"}
    )

    if not adapters:
        yield _sse_event({"type": "done", "total": 0, "best_price": None, "avg_price": None, "offers": []})
        return

    def _run_adapter(adapter):
        run = runs[source_name(adapter)]
        started = time.perf_counter()
        try:
            return adapter, adapter.search(query=query, country=country, max_results=adapter_limit)
        except Exception as exc:
            run.error = str(exc)[:300]
            logger.warning("[SSE] %s fallo: %s", run.source, exc)
            return adapter, []
        finally:
            run.duration_ms = round((time.perf_counter() - started) * 1000)

    executor = ThreadPoolExecutor(max_workers=len(adapters))
    futures = {executor.submit(_run_adapter, adapter): adapter for adapter in adapters}
    try:
        for future in as_completed(futures, timeout=settings.search_timeout_seconds):
            adapter, results = future.result()
            normalized = [normalize_offer(offer) for offer in results if offer and offer.title]
            valid = [offer for offer in normalized if offer.extracted_price is not None]
            runs[source_name(adapter)].offers = len(valid)
            all_offers.extend(valid)
            yield _sse_event(
                {
                    "type": "store_result",
                    "store": _display_name(adapter),
                    "count": len(valid),
                    "offers": [_offer_to_dict(offer) for offer in valid[:10]],
                }
            )
    except TimeoutError:
        logger.warning("[SSE] Tiempo global de busqueda agotado")
        for future, adapter in futures.items():
            if not future.done():
                runs[source_name(adapter)].error = "timeout global de busqueda"
        yield _sse_event({"type": "warning", "message": "Algunas fuentes no respondieron a tiempo."})
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    try:
        event = _done_event(query, all_offers, max_results, "live", datetime.now(timezone.utc))
    except Exception:
        logger.exception("[SSE] Fallo el postprocesamiento")
        yield _sse_event({"type": "error", "message": "No se pudo consolidar la busqueda."})
        return
    # Se guarda antes del evento final: si el cliente cierra la conexion al recibirlo,
    # el generador puede no reanudarse y el catalogo quedaria sin actualizar.
    update_catalog(db, query, all_offers, list(runs.values()), live=True)
    yield _sse_event(event)
