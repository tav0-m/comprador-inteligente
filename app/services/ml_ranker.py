"""Ranking hibrido: heuristica transparente hasta disponer de feedback real."""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)
MODEL_DIR = Path("data/models")
MODEL_PATH = MODEL_DIR / "ranker.joblib"
METADATA_PATH = MODEL_DIR / "ranker_metadata.json"
MODEL_SCHEMA_VERSION = 2

TRUSTED_STORES = {
    "sodimac": 0.90,
    "easy": 0.88,
    "construmart": 0.86,
    "homecenter": 0.88,
    "imperial": 0.84,
    "falabella": 0.82,
    "paris": 0.78,
    "mercado libre": 0.72,
}

FEATURE_COLS = [
    "price_ratio_to_min", "price_ratio_to_median", "price_log",
    "title_sim", "store_trust", "has_free_shipping",
    "has_rating", "rating_norm", "log_reviews", "has_stock",
    "source_serpapi", "source_ml", "source_sodimac",
    "source_easy", "source_falabella", "source_csv",
]

HEURISTIC_WEIGHTS = {
    "price_ratio_to_min": 27.0,
    "price_ratio_to_median": 8.0,
    "title_sim": 25.0,
    "store_trust": 12.0,
    "has_free_shipping": 8.0,
    "rating_norm": 6.0,
    "log_reviews": 4.0,
    "has_stock": 10.0,
}


def feature_engineering(offers: list, query: str) -> pd.DataFrame:
    valid_prices = [offer.extracted_price for offer in offers if offer.extracted_price and offer.extracted_price > 0]
    min_price = min(valid_prices) if valid_prices else 1.0
    median_price = float(np.median(valid_prices)) if valid_prices else 1.0
    rows = []
    for offer in offers:
        price = float(offer.extracted_price or 0)
        store_key = (offer.store or "").lower()
        source = (offer.source or "").lower()
        delivery = (offer.delivery or "").lower()
        availability = (offer.availability or "").lower()
        rows.append({
            "price_ratio_to_min": min_price / price if price > 0 else 0.0,
            "price_ratio_to_median": median_price / price if price > 0 else 0.0,
            "price_log": math.log1p(price),
            "title_sim": fuzz.token_set_ratio((query or "").lower(), (offer.title or "").lower()) / 100.0,
            "store_trust": max((value for key, value in TRUSTED_STORES.items() if key in store_key), default=0.60),
            "has_free_shipping": int(any(term in delivery for term in ("gratis", "free", "sin costo"))),
            "has_rating": int(offer.rating is not None),
            "rating_norm": float(offer.rating or 0) / 5.0,
            "log_reviews": math.log1p(offer.reviews or 0),
            "has_stock": int(any(term in availability for term in ("disponible", "stock", "available", "en stock"))),
            "source_serpapi": int("serpapi" in source),
            "source_ml": int("mercadolibre" in source),
            "source_sodimac": int("sodimac" in source),
            "source_easy": int("easy" in source),
            "source_falabella": int("falabella" in source),
            "source_csv": int("csv" in source),
        })
    return pd.DataFrame(rows, columns=FEATURE_COLS)


def heuristic_scores(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty:
        return np.zeros(0)
    scores = np.zeros(len(frame), dtype=float)
    for feature, weight in HEURISTIC_WEIGHTS.items():
        values = frame[feature].fillna(0).to_numpy(dtype=float)
        if feature == "log_reviews":
            values = np.minimum(values / math.log1p(500), 1.0)
        scores += values * weight
    return np.clip(scores, 0, 100)


def scale_ranker_scores(raw: np.ndarray) -> np.ndarray:
    """Lleva scores de LambdaRank (sin escala fija, a menudo negativos) a 0-100.

    Solo el orden relativo dentro de una busqueda tiene significado, por lo que
    se usa min-max por consulta; recortar a [0, 100] colapsaria los negativos en 0.
    """
    values = np.asarray(raw, dtype=float)
    if values.size == 0:
        return values
    low, high = float(values.min()), float(values.max())
    if not np.isfinite(low) or not np.isfinite(high) or high - low < 1e-12:
        return np.full(values.shape, 50.0)
    return (values - low) / (high - low) * 100.0


class MLRanker:
    def __init__(self):
        self.model = None
        self.metadata: dict = {"mode": "heuristic", "schema_version": MODEL_SCHEMA_VERSION}
        self._load_if_compatible()

    @property
    def mode(self) -> str:
        return "feedback_model" if self.model is not None else "heuristic"

    def _load_if_compatible(self) -> None:
        if not MODEL_PATH.exists() or not METADATA_PATH.exists():
            return
        try:
            metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
            if metadata.get("schema_version") != MODEL_SCHEMA_VERSION:
                logger.info("[Ranker] Artefacto incompatible; se usara heuristica.")
                return
            self.model = joblib.load(MODEL_PATH)
            self.metadata = metadata
            logger.info("[Ranker] Modelo de feedback cargado.")
        except Exception as exc:
            logger.warning("[Ranker] No se pudo cargar el modelo: %s", exc)
            self.model = None

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if frame.empty:
            return np.zeros(0)
        clean = frame[FEATURE_COLS].fillna(0.0)
        if self.model is None:
            return heuristic_scores(clean)
        return scale_ranker_scores(self.model.predict(clean))

    def train_from_feedback(self, frame: pd.DataFrame) -> dict:
        required = set(FEATURE_COLS) | {"label", "group_id"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"Faltan columnas para entrenar: {sorted(missing)}")
        group_count = frame["group_id"].nunique()
        if len(frame) < 100 or group_count < 20:
            raise ValueError(
                f"Se requieren al menos 100 ofertas etiquetadas y 20 busquedas; hay {len(frame)} y {group_count}."
            )

        from lightgbm import LGBMRanker
        from sklearn.metrics import ndcg_score

        group_ids = sorted(frame["group_id"].unique())
        split = max(1, int(len(group_ids) * 0.8))
        train_ids, validation_ids = set(group_ids[:split]), set(group_ids[split:])
        train = frame[frame["group_id"].isin(train_ids)].sort_values("group_id")
        validation = frame[frame["group_id"].isin(validation_ids)].sort_values("group_id")
        if validation.empty:
            raise ValueError("No hay suficientes grupos para validacion temporal.")

        model = LGBMRanker(
            objective="lambdarank",
            metric="ndcg",
            n_estimators=250,
            learning_rate=0.04,
            num_leaves=31,
            max_depth=6,
            min_child_samples=10,
            reg_lambda=1.0,
            random_state=42,
            verbose=-1,
        )
        train_groups = train.groupby("group_id", sort=True).size().tolist()
        model.fit(train[FEATURE_COLS], train["label"], group=train_groups)

        ndcg_values = []
        for _, group in validation.groupby("group_id", sort=False):
            predicted = model.predict(group[FEATURE_COLS])
            ndcg_values.append(ndcg_score([group["label"].to_numpy()], [predicted], k=min(5, len(group))))
        ndcg_at_5 = float(np.mean(ndcg_values)) if ndcg_values else 0.0

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        metadata = {
            "mode": "feedback_model",
            "schema_version": MODEL_SCHEMA_VERSION,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "training_rows": len(train),
            "validation_rows": len(validation),
            "training_groups": len(train_ids),
            "validation_groups": len(validation_ids),
            "ndcg_at_5": round(ndcg_at_5, 4),
            "features": FEATURE_COLS,
        }
        joblib.dump(model, MODEL_PATH)
        METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        self.model = model
        self.metadata = metadata
        return metadata

    def feature_importance(self) -> dict:
        if self.model is None:
            return dict(sorted(HEURISTIC_WEIGHTS.items(), key=lambda item: item[1], reverse=True))
        values = self.model.feature_importances_.tolist()
        return dict(sorted(zip(FEATURE_COLS, values), key=lambda item: item[1], reverse=True))

    def status(self) -> dict:
        return {**self.metadata, "mode": self.mode}


_ranker: MLRanker | None = None


def get_ranker() -> MLRanker:
    global _ranker
    if _ranker is None:
        _ranker = MLRanker()
    return _ranker


def rank_with_ml(query: str, offers: list) -> list:
    if not offers:
        return offers
    frame = feature_engineering(offers, query)
    scores = get_ranker().predict(frame)
    normal_prices = [
        offer.extracted_price for offer in offers
        if offer.extracted_price and offer.anomaly_flag in (None, "ok")
    ]
    average = float(np.mean(normal_prices)) if normal_prices else None
    for index, offer in enumerate(offers):
        offer.ml_score = round(float(scores[index]), 2)
        if offer.anomaly_flag in ("precio_muy_alto", "precio_muy_bajo"):
            offer.ml_score = max(0.0, offer.ml_score - 25.0)
        if offer.extracted_price and normal_prices:
            offer.price_percentile = round(
                sum(price <= offer.extracted_price for price in normal_prices) / len(normal_prices) * 100,
                1,
            )
        if offer.extracted_price and average:
            offer.price_vs_avg_pct = round((offer.extracted_price - average) / average * 100, 1)
        offer.free_shipping = any(
            term in (offer.delivery or "").lower() for term in ("gratis", "free", "sin costo")
        )
    return sorted(offers, key=lambda item: item.ml_score or 0, reverse=True)
