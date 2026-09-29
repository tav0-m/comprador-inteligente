"""Deteccion robusta de anomalias dentro de productos semanticamente equivalentes."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

IQR_LOW = 2.0
IQR_HIGH = 2.5


def detect_price_anomalies(offers: list) -> list:
    groups = defaultdict(list)
    for offer in offers:
        if offer.extracted_price and offer.extracted_price > 0:
            groups[offer.semantic_group].append(offer)
        else:
            offer.anomaly_flag = "sin_precio"

    for members in groups.values():
        prices = [member.extracted_price for member in members]
        if len(prices) < 3:
            for member in members:
                member.anomaly_flag = "ok"
            continue
        low, high = _iqr_bounds(prices)
        outlier_indexes = _isolation_forest(prices) if len(prices) >= 10 else set()
        median = float(np.median(prices))
        for index, member in enumerate(members):
            price = member.extracted_price
            if price < low:
                member.anomaly_flag = "precio_muy_bajo"
            elif price > high:
                member.anomaly_flag = "precio_muy_alto"
            elif index in outlier_indexes:
                member.anomaly_flag = "precio_muy_alto" if price > median else "precio_muy_bajo"
            else:
                member.anomaly_flag = "ok"
    return offers


def _iqr_bounds(prices):
    values = np.asarray(prices, dtype=float)
    q1, q3 = float(np.percentile(values, 25)), float(np.percentile(values, 75))
    iqr = q3 - q1
    if iqr == 0:
        median = float(np.median(values))
        return median * 0.80, median * 1.20
    return max(q1 - IQR_LOW * iqr, 0.0), q3 + IQR_HIGH * iqr


def _isolation_forest(prices):
    try:
        from sklearn.ensemble import IsolationForest

        values = np.asarray(prices, dtype=float).reshape(-1, 1)
        predictions = IsolationForest(contamination=0.1, random_state=42, n_estimators=50).fit_predict(values)
        return {index for index, label in enumerate(predictions) if label == -1}
    except Exception:
        return set()


def anomaly_summary(offers: list) -> dict:
    flags = [offer.anomaly_flag for offer in offers]
    return {
        "total": len(offers),
        "ok": flags.count("ok"),
        "precio_muy_bajo": flags.count("precio_muy_bajo"),
        "precio_muy_alto": flags.count("precio_muy_alto"),
        "sin_precio": flags.count("sin_precio"),
    }
