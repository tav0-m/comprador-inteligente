"""Normalizacion y agrupacion semantica conservando la comparacion entre tiendas."""
from __future__ import annotations

import html
import logging
import re
import unicodedata

from app.adapters._price_utils import clp_to_float

logger = logging.getLogger(__name__)
DEDUP_SIMILARITY_THRESHOLD = 0.80


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(text: str) -> str:
    return clean_text(text or "")


def canonical_title(text: str) -> str:
    value = unicodedata.normalize("NFKD", normalize_title(text).lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"(\d)\s+(mm|cm|m|kg|g|lt|l|oz|w)\b", r"\1\2", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _numeric_signature(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+(?:[.,]\d+)?", canonical_title(text)))


def normalize_offer(offer):
    offer.title = normalize_title(offer.title)
    offer.store = clean_text(offer.store or "Tienda no identificada")
    offer.delivery = clean_text(offer.delivery or "") or None
    offer.availability = clean_text(offer.availability or "") or None
    offer.currency = (offer.currency or "CLP").upper()
    if not offer.extracted_price and offer.price_text:
        offer.extracted_price = clp_to_float(offer.price_text)
    if not offer.price_text and offer.extracted_price:
        offer.price_text = f"{offer.currency} {offer.extracted_price:,.0f}"
    return offer


def semantic_deduplicate(offers: list, threshold: float = DEDUP_SIMILARITY_THRESHOLD) -> list:
    """Agrupa productos equivalentes y elimina solo duplicados dentro de una tienda.

    Ofertas equivalentes de tiendas distintas se conservan: son precisamente lo que
    el producto necesita comparar.
    """
    if len(offers) <= 1:
        if offers:
            offers[0].semantic_group = 0
        return offers
    try:
        return _tfidf_group_and_dedup(offers, threshold)
    except Exception as exc:
        logger.warning("[Normalizer] Agrupacion TF-IDF fallo: %s. Usando dedup exacto.", exc)
        return _exact_dedup(offers)


def _tfidf_group_and_dedup(offers: list, threshold: float) -> list:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    titles = [canonical_title(o.title) for o in offers]
    signatures = [_numeric_signature(o.title) for o in offers]
    vectors = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1).fit_transform(titles)
    similarity = cosine_similarity(vectors)
    parent = list(range(len(offers)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(offers)):
        for right in range(left + 1, len(offers)):
            specs_compatible = not signatures[left] or not signatures[right] or signatures[left] == signatures[right]
            if specs_compatible and similarity[left, right] >= threshold:
                root_left, root_right = find(left), find(right)
                if root_left != root_right:
                    parent[root_right] = root_left

    roots = {}
    next_group = 0
    for index, offer in enumerate(offers):
        root = find(index)
        if root not in roots:
            roots[root] = next_group
            next_group += 1
        offer.semantic_group = roots[root]

    best_by_store_group: dict[tuple[int, str], object] = {}
    for offer in offers:
        key = (offer.semantic_group or 0, (offer.store or "").casefold())
        previous = best_by_store_group.get(key)
        if previous is None or _quality(offer) > _quality(previous):
            best_by_store_group[key] = offer

    result = list(best_by_store_group.values())
    logger.debug("[Normalizer] %d duplicados internos eliminados.", len(offers) - len(result))
    return result


def _quality(offer) -> tuple:
    return (
        int(bool(offer.extracted_price)),
        int(bool(offer.link)),
        int(bool(offer.availability)),
        int(bool(offer.thumbnail)),
        int(offer.reviews or 0),
    )


def _exact_dedup(offers: list) -> list:
    seen, result = set(), []
    for offer in offers:
        key = (canonical_title(offer.title), (offer.store or "").casefold(), int(offer.extracted_price or 0))
        if key not in seen:
            offer.semantic_group = len(result)
            seen.add(key)
            result.append(offer)
    return result
