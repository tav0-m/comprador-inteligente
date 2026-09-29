from __future__ import annotations

from collections import defaultdict

import pandas as pd
from sqlalchemy.orm import Session

from app.models import OfferLog, SearchLog, UserFeedback
from app.schemas import ProductOffer
from app.services.ml_ranker import feature_engineering, get_ranker
from app.services.specs import annotate_offers


def label_from_votes(votes: list[bool]) -> int:
    """2 = util, 0 = no util, 1 = sin evaluar o empate."""
    if not votes:
        return 1
    useful = sum(votes)
    if useful * 2 > len(votes):
        return 2
    if useful * 2 < len(votes):
        return 0
    return 1


def build_feedback_training_frame(db: Session) -> pd.DataFrame:
    feedback_rows = (
        db.query(UserFeedback, OfferLog, SearchLog)
        .join(OfferLog, UserFeedback.offer_log_id == OfferLog.id)
        .join(SearchLog, OfferLog.search_id == SearchLog.id)
        .order_by(SearchLog.created_at.asc(), UserFeedback.created_at.asc())
        .all()
    )
    if not feedback_rows:
        return pd.DataFrame()

    # Voto mayoritario por oferta: con un voto por cliente (client_hash), un solo
    # cliente no puede invertir la etiqueta de una oferta evaluada por varios.
    votes: dict[int, list[bool]] = defaultdict(list)
    searches = {}
    for feedback, offer, search in feedback_rows:
        votes[offer.id].append(bool(feedback.useful))
        searches[search.id] = search

    frames = []
    for search_id, search in searches.items():
        offers = db.query(OfferLog).filter(OfferLog.search_id == search_id).all()
        if len(offers) < 2:
            continue
        pseudo = [
            ProductOffer(
                title=row.title or "Sin titulo",
                store=row.store,
                source=row.source or "unknown",
                price_text=row.price_text,
                extracted_price=row.extracted_price,
                currency=row.currency or "CLP",
                delivery=row.delivery,
                availability=row.availability,
                rating=row.rating,
                reviews=row.reviews,
                anomaly_flag=row.anomaly_flag or "ok",
            )
            for row in offers
        ]
        frame = feature_engineering(annotate_offers(search.query, pseudo), search.query)
        frame["group_id"] = search_id
        frame["label"] = [label_from_votes(votes.get(row.id, [])) for row in offers]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def train_from_database(db: Session) -> dict:
    frame = build_feedback_training_frame(db)
    if frame.empty:
        raise ValueError("No existe feedback real para entrenar.")
    return get_ranker().train_from_feedback(frame)
