"""Parseo defensivo de precios CLP en una unica implementacion Python."""
from __future__ import annotations

import math
import re

MAX_REASONABLE_PRICE_CLP = 30_000_000
MIN_REASONABLE_PRICE_CLP = 10

_NUMBER = r"\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d+)?"


def clp_to_float(value) -> float | None:
    """Convierte formatos chilenos, americanos y europeos a un precio valido."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _valid(float(value))

    text = str(value).strip()
    if not text:
        return None

    currency_match = re.search(rf"(?:CLP\s*|\$\s*)({_NUMBER})", text, flags=re.IGNORECASE)
    if currency_match:
        return _parse_token(currency_match.group(1))

    tokens = []
    for match in re.finditer(_NUMBER, text):
        suffix = text[match.end():].lstrip()
        if suffix.startswith("%"):
            continue
        parsed = _parse_token(match.group(0))
        if parsed is not None:
            tokens.append(parsed)
    return max(tokens) if tokens else None


def _parse_token(token: str) -> float | None:
    compact = token.replace(" ", "")
    dot_count, comma_count = compact.count("."), compact.count(",")
    try:
        if dot_count and comma_count:
            if compact.rfind(",") > compact.rfind("."):
                number = float(compact.replace(".", "").replace(",", "."))
            else:
                number = float(compact.replace(",", ""))
        elif dot_count > 1:
            number = float(compact.replace(".", ""))
        elif comma_count > 1:
            number = float(compact.replace(",", ""))
        elif dot_count == 1:
            whole, fraction = compact.split(".")
            number = float(whole + fraction) if len(fraction) == 3 else float(compact)
        elif comma_count == 1:
            whole, fraction = compact.split(",")
            number = float(whole + fraction) if len(fraction) == 3 else float(f"{whole}.{fraction}")
        else:
            number = float(compact)
    except (TypeError, ValueError):
        return None
    return _valid(number)


def _valid(number: float) -> float | None:
    if not math.isfinite(number):
        return None
    if MIN_REASONABLE_PRICE_CLP <= number <= MAX_REASONABLE_PRICE_CLP:
        return number
    return None


def to_int(value) -> int | None:
    parsed = clp_to_float(value)
    return int(parsed) if parsed is not None else None
