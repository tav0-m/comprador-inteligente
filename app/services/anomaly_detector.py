"""Deteccion robusta de anomalias dentro de productos semanticamente equivalentes."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

IQR_LOW = 2.0
IQR_HIGH = 2.5
MAD_Z_THRESHOLD = 3.5          # Iglewicz-Hoaglin: |z modificado| > 3.5 es atipico
SMALL_GROUP_MAX_RATIO = 20.0   # grupos < 3 precios: atipico si se aleja 20x de la mediana global
MIN_OFFERS_FOR_GLOBAL_CHECK = 5


def detect_price_anomalies(offers: list) -> list:
    groups = defaultdict(list)
    for offer in offers:
        if offer.extracted_price and offer.extracted_price > 0:
            groups[offer.semantic_group].append(offer)
        else:
            offer.anomaly_flag = "sin_precio"

    all_prices = [member.extracted_price for members in groups.values() for member in members]
    global_median = float(np.median(all_prices)) if len(all_prices) >= MIN_OFFERS_FOR_GLOBAL_CHECK else None

    for members in groups.values():
        prices = [member.extracted_price for member in members]
        if len(prices) < 3:
            # Sin muestra suficiente dentro del grupo: solo se descartan precios
            # extremos respecto de toda la busqueda (p. ej. precios concatenados).
            for member in members:
                member.anomaly_flag = _small_group_flag(member.extracted_price, global_median)
            continue
        low, high = _iqr_bounds(prices)
        outlier_indexes = _mad_outliers(prices)
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


def _small_group_flag(price: float, global_median: float | None) -> str:
    if global_median is None or global_median <= 0:
        return "ok"
    if price > global_median * SMALL_GROUP_MAX_RATIO:
        return "precio_muy_alto"
    if price < global_median / SMALL_GROUP_MAX_RATIO:
        return "precio_muy_bajo"
    return "ok"


def _iqr_bounds(prices):
    values = np.asarray(prices, dtype=float)
    q1, q3 = float(np.percentile(values, 25)), float(np.percentile(values, 75))
    iqr = q3 - q1
    if iqr == 0:
        median = float(np.median(values))
        return median * 0.80, median * 1.20
    return max(q1 - IQR_LOW * iqr, 0.0), q3 + IQR_HIGH * iqr


def _mad_outliers(prices) -> set[int]:
    """Atipicos por z-score modificado sobre log(precio).

    A diferencia de IsolationForest(contamination=0.1), no obliga a marcar una
    fraccion fija: si todos los precios son coherentes, no marca ninguno.
    """
    values = np.log(np.asarray(prices, dtype=float))
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0:
        return set()
    z_scores = 0.6745 * (values - median) / mad
    return {index for index, z in enumerate(z_scores) if abs(z) > MAD_Z_THRESHOLD}


def anomaly_summary(offers: list) -> dict:
    flags = [offer.anomaly_flag for offer in offers]
    return {
        "total": len(offers),
        "ok": flags.count("ok"),
        "precio_muy_bajo": flags.count("precio_muy_bajo"),
        "precio_muy_alto": flags.count("precio_muy_alto"),
        "sin_precio": flags.count("sin_precio"),
    }
