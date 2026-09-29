from __future__ import annotations

import json
from pathlib import Path

from rapidfuzz import fuzz

from app.schemas import ProductOffer


def load_store_priorities() -> dict:
    path = Path("data/store_priorities.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def rank_offers(query: str, offers: list[ProductOffer]) -> list[ProductOffer]:
    priorities = load_store_priorities()
    valid_prices = [offer.extracted_price for offer in offers if offer.extracted_price and offer.extracted_price > 0]
    min_price = min(valid_prices) if valid_prices else None
    for offer in offers:
        relevance = fuzz.token_set_ratio(query.casefold(), offer.title.casefold())
        offer.score = round(
            _price_score(offer.extracted_price, min_price)
            + relevance * 0.30
            + _store_score(offer.store, priorities)
            + _availability_score(offer.availability, offer.delivery)
            + _rating_score(offer.rating, offer.reviews),
            2,
        )
        if relevance < 35:
            offer.score = max(0, offer.score - 25)
        offer.recommendation = _recommendation(offer)
    return sorted(offers, key=lambda item: item.score or 0, reverse=True)


def _price_score(price, min_price):
    if not price or not min_price or price <= 0:
        return 0
    return min(30, 30 * min_price / price)


def _store_score(store, priorities):
    store_name = (store or "").casefold()
    for key, value in priorities.items():
        if key.casefold() in store_name:
            return float(value)
    return 6


def _availability_score(availability, delivery):
    text = f"{availability or ''} {delivery or ''}".casefold()
    score = 8 if any(term in text for term in ("disponible", "stock", "available")) else 0
    if any(term in text for term in ("envio gratis", "envío gratis", "free shipping", "despacho gratis")):
        score += 7
    elif any(term in text for term in ("delivery", "despacho", "envio", "envío", "retiro")):
        score += 4
    return score


def _rating_score(rating, reviews):
    rating_points = 5 if rating and rating >= 4.5 else 3 if rating and rating >= 4 else 0
    review_points = 3 if reviews and reviews >= 100 else 1 if reviews and reviews >= 10 else 0
    return rating_points + review_points


def _recommendation(offer: ProductOffer) -> str:
    if not offer.extracted_price:
        return "Precio no verificable; revisar manualmente."
    if offer.relevance is not None and offer.relevance < 0.75:
        return "Producto distinto o accesorio de lo buscado; no comparable."
    if offer.spec_match == "mismatch":
        return "Medida o formato distinto al buscado; comparar por precio por unidad."
    if offer.anomaly_flag in ("precio_muy_alto", "precio_muy_bajo"):
        return "Precio atipico; confirmar directamente con la tienda."
    if offer.spec_match == "unknown":
        return "El titulo no informa la medida buscada; verificar ficha del producto."
    if offer.score and offer.score >= 70:
        return "Oferta relevante; confirmar stock y costo total de despacho."
    return "Comparar especificacion, stock y despacho antes de comprar."
