from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.models import OfferLog, SearchLog, UserFeedback
from app.schemas import ProductOffer
from app.services.ml_ranker import feature_engineering, get_ranker


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

    latest_feedback = {}
    searches = {}
    for feedback, offer, search in feedback_rows:
        latest_feedback[offer.id] = feedback
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
        frame = feature_engineering(pseudo, search.query)
        frame["group_id"] = search_id
        frame["label"] = [
            2 if latest_feedback.get(row.id) and latest_feedback[row.id].useful
            else 0 if latest_feedback.get(row.id) and not latest_feedback[row.id].useful
            else 1
            for row in offers
        ]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def train_from_database(db: Session) -> dict:
    frame = build_feedback_training_frame(db)
    if frame.empty:
        raise ValueError("No existe feedback real para entrenar.")
    return get_ranker().train_from_feedback(frame)
