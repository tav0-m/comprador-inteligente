from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import OfferLog, PriceHistory, SearchLog
from app.schemas import ProductOffer, SearchResponse
from app.services.anomaly_detector import anomaly_summary, detect_price_anomalies
from app.services.cache import cache_get, cache_key, cache_set
from app.services.ml_ranker import rank_with_ml
from app.services.normalizer import normalize_offer, semantic_deduplicate
from app.services.product_guardrails import validate_country, validate_query
from app.services.ranking import rank_offers
from app.services.sources import fetch_live_offers, get_adapters  # noqa: F401 (reexport)
from app.services.specs import annotate_offers, dominant_unit, is_comparable

logger = logging.getLogger(__name__)


def search_products(
    db: Session,
    query: str,
    country: str = "cl",
    city: str | None = None,
    max_results: int = 20,
    use_cache: bool = True,
) -> SearchResponse:
    started = time.perf_counter()
    query = validate_query(query)
    country = validate_country(country)
    city = city.strip() if city else None
    key = cache_key(query, country, city, max_results)
    if use_cache and (cached := cache_get(key)):
        response = SearchResponse(**cached)
        response.elapsed_ms = round((time.perf_counter() - started) * 1000)
        return response

    catalog_hit = load_catalog_offers(db, query) if use_cache else None
    if catalog_hit:
        raw_offers, data_as_of = catalog_hit
        data_source, runs = "catalog", []
    else:
        limit = max(max_results * 2, 36)
        raw_offers, runs = fetch_live_offers(query, country, limit)
        data_source, data_as_of = "live", datetime.now(timezone.utc)

    ranked = process_offers(query, raw_offers)
    stats = summarize_offers(ranked)
    search_id = _save_search(
        db, query, country, city, ranked, stats["best_price"], stats["avg_price"],
        record_history=data_source == "live",
    )
    update_catalog(db, query, raw_offers, runs, live=data_source == "live")
    response = SearchResponse(
        query=query,
        country=country,
        city=city,
        total_results=min(len(ranked), max_results),
        offers=ranked[:max_results],
        **stats,
        search_id=search_id,
        data_source=data_source,
        data_as_of=data_as_of,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )
    if use_cache:
        cache_set(key, response.model_dump())
    return response


def load_catalog_offers(db: Session, query: str):
    """Ofertas frescas del catalogo propio; None si no hay o fallo la lectura."""
    from app.services.catalog import fresh_offers

    try:
        return fresh_offers(db, query, settings.catalog_freshness_hours)
    except Exception as exc:
        db.rollback()
        logger.warning("[Catalogo] Lectura fallida; se consulta en vivo: %s", exc)
        return None


def update_catalog(db: Session, query: str, offers: list[ProductOffer], runs: list, live: bool) -> None:
    """Registra la demanda y, si fue en vivo, guarda las ofertas en el catalogo.

    Nunca interrumpe la busqueda: un fallo del catalogo solo se registra.
    """
    from app.services.catalog import ensure_watch, record_offers

    try:
        if live:
            record_offers(db, query, offers, runs, trigger="live")
        ensure_watch(db, query, origin="user", count_request=True)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("[Catalogo] No se pudo actualizar: %s", exc)


MIN_COMPARABLE_TO_HIDE_UNRELATED = 3
UNRELATED_RELEVANCE = 0.5


def process_offers(query: str, raw_offers: list[ProductOffer]) -> list[ProductOffer]:
    """Normaliza, anota especificaciones, agrupa, detecta anomalias y rankea.

    Si hay suficientes ofertas comparables se ocultan las de otro producto
    (p. ej. arena al buscar cemento); las de otra medida quedan al final.
    """
    normalized = [normalize_offer(offer) for offer in raw_offers if offer and offer.title]
    annotated = annotate_offers(query, normalized)
    grouped = semantic_deduplicate(annotated)
    analyzed = detect_price_anomalies(grouped)
    ranked = rank_with_ml(query, rank_offers(query, analyzed))
    if sum(is_comparable(offer) for offer in ranked) >= MIN_COMPARABLE_TO_HIDE_UNRELATED:
        ranked = [offer for offer in ranked if (offer.relevance or 0) >= UNRELATED_RELEVANCE]
    return ranked


def summarize_offers(ranked: list[ProductOffer]) -> dict:
    """KPIs de la busqueda calculados solo sobre ofertas comparables y sin anomalia."""
    reliable = [
        offer for offer in ranked
        if offer.extracted_price and 10 <= offer.extracted_price <= 30_000_000
        and offer.anomaly_flag == "ok" and is_comparable(offer)
    ]
    prices = sorted(offer.extracted_price for offer in reliable)
    if prices:
        trim = len(prices) // 10
        sample = prices[trim:-trim] if trim and len(prices) > 2 * trim else prices
        average_price = round(float(np.mean(sample)), 0)
    else:
        average_price = None
    unit = dominant_unit(reliable)
    unit_prices = [offer.unit_price for offer in reliable if unit and offer.unit == unit and offer.unit_price]
    summary = anomaly_summary(ranked)
    return {
        "best_price": prices[0] if prices else None,
        "avg_price": average_price,
        "price_spread_pct": round((prices[-1] - prices[0]) / prices[0] * 100, 1) if len(prices) >= 2 else None,
        "anomaly_count": summary["precio_muy_alto"] + summary["precio_muy_bajo"],
        "comparable_count": sum(is_comparable(offer) for offer in ranked),
        "unit": unit,
        "best_unit_price": min(unit_prices) if unit_prices else None,
    }


def _save_search(db, query, country, city, offers, best_price, average_price, record_history: bool = True) -> int:
    try:
        search = SearchLog(
            query=query,
            country=country,
            city=city,
            total_results=len(offers),
            best_price=best_price,
            avg_price=average_price,
        )
        db.add(search)
        db.flush()
        rows = []
        for offer in offers:
            row = OfferLog(
                search_id=search.id,
                title=offer.title,
                store=offer.store,
                source=offer.source,
                price_text=offer.price_text,
                extracted_price=offer.extracted_price,
                currency=offer.currency,
                delivery=offer.delivery,
                availability=offer.availability,
                rating=offer.rating,
                reviews=offer.reviews,
                link=offer.link,
                thumbnail=offer.thumbnail,
                score=offer.score,
                ml_score=offer.ml_score,
                recommendation=offer.recommendation,
                price_percentile=offer.price_percentile,
                anomaly_flag=offer.anomaly_flag,
                price_vs_avg_pct=offer.price_vs_avg_pct,
                free_shipping=offer.free_shipping,
            )
            db.add(row)
            rows.append((offer, row))
        db.flush()  # un solo flush para todas las filas (antes: uno por oferta)
        for offer, row in rows:
            offer.offer_log_id = row.id
        if record_history:
            record_price_history(db, query, offers)
        db.commit()
        return search.id
    except Exception:
        db.rollback()
        raise


def record_price_history(db: Session, query: str, offers: list[ProductOffer]) -> None:
    """Agrega observaciones a PriceHistory (usado por alertas), sin duplicar en 30 min."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    recent = {
        (row.store, row.title, row.price)
        for row in db.query(PriceHistory.store, PriceHistory.title, PriceHistory.price)
        .filter(PriceHistory.query == query, PriceHistory.recorded_at >= cutoff)
        .all()
    }
    for offer in offers:
        if not offer.extracted_price or offer.extracted_price <= 0:
            continue
        identity = (offer.store or "Desconocida", offer.title, offer.extracted_price)
        if identity in recent:
            continue
        recent.add(identity)
        db.add(PriceHistory(
            query=query,
            title=offer.title,
            store=identity[0],
            source=offer.source,
            price=offer.extracted_price,
            currency=offer.currency,
            link=offer.link,
        ))


def get_price_history(db: Session, query: str, limit: int = 200) -> list:
    normalized = validate_query(query).casefold()
    return (
        db.query(PriceHistory)
        .filter(func.lower(PriceHistory.query) == normalized)
        .order_by(PriceHistory.recorded_at.asc())
        .limit(limit)
        .all()
    )


def get_stats(db: Session) -> dict:
    total_searches = db.query(func.count(SearchLog.id)).scalar() or 0
    total_offers = db.query(func.count(OfferLog.id)).scalar() or 0
    average_score = db.query(func.avg(OfferLog.ml_score)).scalar()
    top_queries = (
        db.query(SearchLog.query, func.count(SearchLog.id).label("count"))
        .group_by(SearchLog.query)
        .order_by(func.count(SearchLog.id).desc())
        .limit(10)
        .all()
    )
    stores = [row[0] for row in db.query(distinct(OfferLog.store)).filter(OfferLog.store.isnot(None)).all()]
    return {
        "total_searches": total_searches,
        "total_offers_logged": total_offers,
        "top_queries": [{"query": query, "count": count} for query, count in top_queries],
        "avg_score": round(float(average_score), 2) if average_score is not None else None,
        "stores_seen": sorted(stores),
    }
