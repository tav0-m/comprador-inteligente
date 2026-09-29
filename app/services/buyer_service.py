from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.adapters.construmart import ConstrumartAdapter
from app.adapters.easy import EasyAdapter
from app.adapters.falabella import FalabellaAdapter
from app.adapters.local_csv import LocalCSVAdapter
from app.adapters.mercadolibre import MercadoLibreAdapter
from app.adapters.paris import ParisAdapter
from app.adapters.serpapi_google_shopping import SerpApiGoogleShoppingAdapter
from app.adapters.sodimac import SodimacAdapter
from app.core.config import settings
from app.models import OfferLog, PriceHistory, SearchLog
from app.schemas import ProductOffer, SearchResponse
from app.services.anomaly_detector import anomaly_summary, detect_price_anomalies
from app.services.cache import cache_get, cache_key, cache_set
from app.services.ml_ranker import rank_with_ml
from app.services.normalizer import normalize_offer, semantic_deduplicate
from app.services.product_guardrails import validate_country, validate_query
from app.services.ranking import rank_offers
from app.services.specs import annotate_offers, dominant_unit, is_comparable

logger = logging.getLogger(__name__)


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

    adapters = get_adapters()
    raw_offers: list[ProductOffer] = []

    def run_adapter(adapter):
        try:
            limit = max(max_results * 2, 36)
            return adapter.search(query=query, country=country, max_results=limit)
        except Exception as exc:
            logger.warning("[%s] fallo: %s", adapter.__class__.__name__, exc)
            return []

    executor = ThreadPoolExecutor(max_workers=max(1, len(adapters)), thread_name_prefix="store")
    futures = [executor.submit(run_adapter, adapter) for adapter in adapters]
    done, pending = wait(futures, timeout=settings.search_timeout_seconds)
    for future in done:
        try:
            raw_offers.extend(future.result())
        except Exception as exc:
            logger.warning("[BuyerService] worker fallo: %s", exc)
    for future in pending:
        future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)
    if pending:
        logger.warning("[BuyerService] %d fuentes excedieron el timeout global.", len(pending))

    ranked = process_offers(query, raw_offers)
    stats = summarize_offers(ranked)
    search_id = _save_search(db, query, country, city, ranked, stats["best_price"], stats["avg_price"])
    response = SearchResponse(
        query=query,
        country=country,
        city=city,
        total_results=min(len(ranked), max_results),
        offers=ranked[:max_results],
        **stats,
        search_id=search_id,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )
    if use_cache:
        cache_set(key, response.model_dump())
    return response


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


def _save_search(db, query, country, city, offers, best_price, average_price) -> int:
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
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
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
            db.flush()
            offer.offer_log_id = row.id
            if offer.extracted_price and offer.extracted_price > 0:
                duplicate = (
                    db.query(PriceHistory.id)
                    .filter(PriceHistory.query == query)
                    .filter(PriceHistory.store == (offer.store or "Desconocida"))
                    .filter(PriceHistory.title == offer.title)
                    .filter(PriceHistory.price == offer.extracted_price)
                    .filter(PriceHistory.recorded_at >= cutoff)
                    .first()
                )
                if not duplicate:
                    db.add(PriceHistory(
                        query=query,
                        title=offer.title,
                        store=offer.store or "Desconocida",
                        source=offer.source,
                        price=offer.extracted_price,
                        currency=offer.currency,
                        link=offer.link,
                    ))
        db.commit()
        return search.id
    except Exception:
        db.rollback()
        raise


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
