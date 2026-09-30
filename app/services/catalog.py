"""Catalogo propio alimentado por ingesta programada y por busquedas en vivo.

Flujo:
- Cada busqueda en vivo y cada corrida programada guarda los productos
  (CatalogProduct), un precio por producto y dia (PriceObservation), que
  productos devolvio la consulta (CatalogQueryHit) y el resultado de cada
  fuente (IngestionRun).
- Si una consulta se refresco hace menos de CATALOG_FRESHNESS_HOURS, /search
  responde desde la base en milisegundos, sin tocar las tiendas.
- Las observaciones diarias forman la serie de tiempo para el indice de
  precios y futuros modelos de "cuando comprar".
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CatalogProduct, CatalogQueryHit, IngestionRun, PriceObservation, WatchQuery
from app.schemas import ProductOffer
from app.services.specs import annotate_offers, canonical, dominant_unit, is_comparable

logger = logging.getLogger(__name__)

WATCHLIST_SEED = Path("data/watchlist.txt")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite devuelve datetimes sin zona (guardados en UTC); Postgres con zona."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def query_key(query: str) -> str:
    return re.sub(r"\s+", " ", canonical(query)).strip()[:200]


def _normalize_link(link: str) -> str:
    parts = urlsplit(link.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def url_key(source: str, link: str | None, title: str) -> str:
    identity = _normalize_link(link) if link else f"{source}|{canonical(title)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


# ── Escritura ────────────────────────────────────────────────────────────────
def ensure_watch(db: Session, query: str, origin: str = "user", count_request: bool = False) -> WatchQuery | None:
    key = query_key(query)
    watch = db.query(WatchQuery).filter(WatchQuery.query_key == key).first()
    if watch is None:
        if origin == "user":
            active = db.query(func.count(WatchQuery.id)).filter(WatchQuery.active.is_(True)).scalar()
            if active >= settings.catalog_max_watch_queries:
                return None
        watch = WatchQuery(query_key=key, query=query.strip()[:200], origin=origin, active=True, requests=0)
        db.add(watch)
    elif origin in ("seed", "admin") and not watch.active:
        watch.active = True
    if count_request:
        watch.requests = (watch.requests or 0) + 1
        watch.last_requested_at = utcnow()
    return watch


def record_offers(db: Session, query: str, offers: list[ProductOffer], runs: list, trigger: str) -> int:
    """Upsert de productos, observacion diaria y hits de la consulta. Retorna productos guardados."""
    key = query_key(query)
    now = utcnow()
    today = now.date()

    by_identity: dict[tuple[str, str], ProductOffer] = {}
    for offer in offers:
        if offer.title and offer.extracted_price and offer.extracted_price > 0:
            by_identity[(offer.source, url_key(offer.source, offer.link, offer.title))] = offer

    existing = {}
    if by_identity:
        keys = {identity[1] for identity in by_identity}
        for product in db.query(CatalogProduct).filter(CatalogProduct.url_key.in_(keys)).all():
            existing[(product.source, product.url_key)] = product

    products = []
    for (source, identity), offer in by_identity.items():
        product = existing.get((source, identity))
        if product is None:
            product = CatalogProduct(source=source, url_key=identity, first_seen_at=now)
            db.add(product)
        product.store = offer.store
        product.seller = offer.seller
        product.title = offer.title[:500]
        product.link = offer.link
        product.thumbnail = offer.thumbnail
        product.currency = offer.currency or "CLP"
        product.last_price = offer.extracted_price
        product.last_price_text = (offer.price_text or "")[:100] or None
        product.delivery = offer.delivery
        product.availability = offer.availability
        product.rating = offer.rating
        product.reviews = offer.reviews
        product.last_seen_at = now
        products.append(product)
    db.flush()

    product_ids = [product.id for product in products]
    observations = {}
    hits = {}
    if product_ids:
        observations = {
            row.product_id: row
            for row in db.query(PriceObservation)
            .filter(PriceObservation.product_id.in_(product_ids), PriceObservation.observed_on == today)
            .all()
        }
        hits = {
            row.product_id: row
            for row in db.query(CatalogQueryHit)
            .filter(CatalogQueryHit.query_key == key, CatalogQueryHit.product_id.in_(product_ids))
            .all()
        }
    for product in products:
        observation = observations.get(product.id)
        if observation is None:
            db.add(PriceObservation(
                product_id=product.id, observed_on=today, price=product.last_price,
                min_price=product.last_price, price_text=product.last_price_text, observed_at=now,
            ))
        else:
            observation.price = product.last_price
            observation.min_price = min(observation.min_price, product.last_price)
            observation.price_text = product.last_price_text
            observation.observed_at = now
        hit = hits.get(product.id)
        if hit is None:
            db.add(CatalogQueryHit(query_key=key, product_id=product.id, last_seen_at=now))
        else:
            hit.last_seen_at = now

    for run in runs:
        db.add(IngestionRun(
            query_key=key, source=run.source, trigger=trigger, offers=run.offers,
            duration_ms=run.duration_ms, error=run.error,
        ))
    # origin="user": nunca reactiva una consulta que un administrador desactivo.
    watch = ensure_watch(db, query, origin="user")
    if watch is not None:
        watch.last_ingested_at = now
    db.commit()
    return len(products)


# ── Lectura ──────────────────────────────────────────────────────────────────
def _to_offer(product: CatalogProduct) -> ProductOffer:
    return ProductOffer(
        title=product.title,
        store=product.store,
        seller=product.seller,
        source=product.source,
        price_text=product.last_price_text,
        extracted_price=product.last_price,
        currency=product.currency or "CLP",
        delivery=product.delivery,
        availability=product.availability,
        rating=product.rating,
        reviews=product.reviews,
        link=product.link,
        thumbnail=product.thumbnail,
    )


def fresh_offers(db: Session, query: str, max_age_hours: int) -> tuple[list[ProductOffer], datetime] | None:
    """Ofertas de la ultima ingesta de la consulta si tiene menos de max_age_hours."""
    watch = db.query(WatchQuery).filter(WatchQuery.query_key == query_key(query)).first()
    ingested_at = as_utc(watch.last_ingested_at) if watch else None
    if ingested_at is None or ingested_at < utcnow() - timedelta(hours=max_age_hours):
        return None
    # Solo productos vistos en esa ultima ingesta: los que desaparecieron no se sirven.
    since = ingested_at - timedelta(minutes=30)
    products = (
        db.query(CatalogProduct)
        .join(CatalogQueryHit, CatalogQueryHit.product_id == CatalogProduct.id)
        .filter(CatalogQueryHit.query_key == watch.query_key, CatalogQueryHit.last_seen_at >= since)
        .all()
    )
    if not products:
        return None
    return [_to_offer(product) for product in products], ingested_at


def price_index(db: Session, query: str, days: int = 30) -> dict:
    """Serie diaria de precios de las ofertas comparables de una consulta.

    Por dia: n ofertas, precio minimo y mediano del envase y, si comparten
    unidad, precio minimo y mediano por unidad (CLP/kg, CLP/l...).
    """
    key = query_key(query)
    since = utcnow().date() - timedelta(days=days)
    rows = (
        db.query(PriceObservation, CatalogProduct)
        .join(CatalogProduct, CatalogProduct.id == PriceObservation.product_id)
        .join(CatalogQueryHit, CatalogQueryHit.product_id == CatalogProduct.id)
        .filter(CatalogQueryHit.query_key == key, PriceObservation.observed_on >= since)
        .all()
    )
    offers_by_product = {product.id: _to_offer(product) for _, product in rows}
    annotate_offers(query, list(offers_by_product.values()))
    comparable = {pid: offer for pid, offer in offers_by_product.items() if is_comparable(offer)}
    unit = dominant_unit(list(comparable.values()))

    daily: dict = defaultdict(lambda: {"prices": [], "unit_prices": []})
    for observation, product in rows:
        offer = comparable.get(product.id)
        if offer is None:
            continue
        bucket = daily[observation.observed_on]
        bucket["prices"].append(observation.min_price)
        if unit and offer.unit == unit and offer.pack_quantity:
            bucket["unit_prices"].append(observation.min_price / offer.pack_quantity)

    series = []
    for day in sorted(daily):
        prices, unit_prices = daily[day]["prices"], daily[day]["unit_prices"]
        series.append({
            "date": day.isoformat(),
            "offers": len(prices),
            "min_price": round(min(prices), 0),
            "median_price": round(median(prices), 0),
            "min_unit_price": round(min(unit_prices), 2) if unit_prices else None,
            "median_unit_price": round(median(unit_prices), 2) if unit_prices else None,
        })
    return {"query": query, "query_key": key, "unit": unit, "days": days, "series": series}


def catalog_status(db: Session, hours: int = 24) -> dict:
    """Salud del catalogo y de cada fuente en la ventana indicada."""
    since = utcnow() - timedelta(hours=hours)
    runs = db.query(IngestionRun).filter(IngestionRun.created_at >= since).all()
    by_source: dict[str, list[IngestionRun]] = defaultdict(list)
    for run in runs:
        by_source[run.source].append(run)
    sources = {}
    for source, items in sorted(by_source.items()):
        ok = [run for run in items if run.offers > 0 and not run.error]
        durations = [run.duration_ms for run in items if run.duration_ms is not None]
        sources[source] = {
            "runs": len(items),
            "success_rate": round(len(ok) / len(items), 3),
            "avg_offers": round(sum(run.offers for run in items) / len(items), 1),
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
            "last_error": next((run.error for run in sorted(items, key=lambda r: r.id, reverse=True) if run.error), None),
        }
    from app.services.sources import get_adapters, source_name

    last_ingestion = db.query(func.max(WatchQuery.last_ingested_at)).scalar()
    return {
        "active_sources": sorted(source_name(adapter) for adapter in get_adapters()),
        "products": db.query(func.count(CatalogProduct.id)).scalar() or 0,
        "observations": db.query(func.count(PriceObservation.id)).scalar() or 0,
        "watch_queries_active": db.query(func.count(WatchQuery.id)).filter(WatchQuery.active.is_(True)).scalar() or 0,
        "last_ingestion_at": as_utc(last_ingestion),
        "window_hours": hours,
        "sources": sources,
    }


# ── Ingesta programada ───────────────────────────────────────────────────────
def seed_watchlist(db: Session) -> int:
    if not WATCHLIST_SEED.exists():
        return 0
    added = 0
    for line in WATCHLIST_SEED.read_text(encoding="utf-8").splitlines():
        query = line.split("#", 1)[0].strip()
        if len(query) >= 2 and ensure_watch(db, query, origin="seed") is not None:
            added += 1
    db.commit()
    return added


def ingest_query(db: Session, query: str, trigger: str = "scheduled") -> dict:
    from app.services.buyer_service import record_price_history
    from app.services.normalizer import normalize_offer
    from app.services.sources import fetch_live_offers

    started = time.perf_counter()
    raw, runs = fetch_live_offers(query, settings.default_country, settings.catalog_ingest_limit_per_source)
    offers = [normalize_offer(offer) for offer in raw if offer and offer.title]
    saved = record_offers(db, query, offers, runs, trigger=trigger)
    record_price_history(db, query, offers)  # mantiene las alertas de precio alimentadas
    db.commit()
    return {
        "query": query,
        "products": saved,
        "sources": {run.source: run.offers for run in runs},
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


def ingest_watchlist(db: Session, limit: int | None = None, pause_range: tuple[float, float] = (2.0, 5.0)) -> dict:
    """Refresca las consultas vigiladas menos recientes, con pausas entre consultas."""
    if db.query(func.count(WatchQuery.id)).scalar() == 0:
        seed_watchlist(db)
    batch = (
        db.query(WatchQuery)
        .filter(WatchQuery.active.is_(True))
        .order_by(WatchQuery.last_ingested_at.is_(None).desc(), WatchQuery.last_ingested_at.asc())
        .limit(limit or settings.catalog_ingest_batch)
        .all()
    )
    results, failures = [], []
    for index, watch in enumerate(batch):
        if index:
            time.sleep(random.uniform(*pause_range))
        try:
            results.append(ingest_query(db, watch.query))
        except Exception as exc:
            db.rollback()
            logger.warning("[Catalogo] Ingesta fallo para '%s': %s", watch.query, exc)
            failures.append(watch.query)
    return {
        "queries": len(batch),
        "ok": len(results),
        "failed": failures,
        "products": sum(item["products"] for item in results),
    }
