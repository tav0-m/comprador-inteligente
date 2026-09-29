"""Relevancia por especificacion y precio por unidad.

La similitud difusa de titulos no distingue "cemento 25 kg" de "arena 25 kg"
ni de "cemento 1 kg". Este modulo separa la consulta en:

- terminos nucleo ("cemento"): deben aparecer en el titulo (no solo como
  accesorio: "mandril PARA taladro" no es un taladro);
- especificaciones ("25 kg", "13 mm", "750 W"): si el titulo declara otra
  magnitud de la misma dimension, la oferta no es comparable.

Ademas deriva el contenido del envase para calcular precio por unidad
(CLP/kg, CLP/l, CLP/m2, CLP/unidad) y comparar formatos distintos.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

RELEVANCE_THRESHOLD = 0.75       # fraccion de terminos nucleo presentes para ser comparable
ACCESSORY_CREDIT = 0.3           # credito de un termino que solo aparece tras "para"
SPEC_TOLERANCE = 0.03            # 3%: absorbe 1/2" = 12,7 mm ~ 13 mm y redondeos

# unidad -> (dimension, factor a unidad base). Base: g, ml, m, m2, W, V, u.
_UNITS: dict[str, tuple[str, float]] = {
    "kg": ("masa", 1000), "kgs": ("masa", 1000), "kilo": ("masa", 1000), "kilos": ("masa", 1000),
    "g": ("masa", 1), "gr": ("masa", 1), "grs": ("masa", 1), "gramos": ("masa", 1),
    "l": ("volumen", 1000), "lt": ("volumen", 1000), "lts": ("volumen", 1000),
    "litro": ("volumen", 1000), "litros": ("volumen", 1000),
    "ml": ("volumen", 1), "cc": ("volumen", 1),
    "gl": ("volumen", 3785.41), "gal": ("volumen", 3785.41), "galon": ("volumen", 3785.41),
    "galones": ("volumen", 3785.41),
    "m2": ("area", 1), "mt2": ("area", 1), "mts2": ("area", 1),
    "mm": ("largo", 0.001), "cm": ("largo", 0.01),
    "m": ("largo", 1), "mt": ("largo", 1), "mts": ("largo", 1), "metro": ("largo", 1), "metros": ("largo", 1),
    '"': ("largo", 0.0254), "pulg": ("largo", 0.0254), "pulgada": ("largo", 0.0254),
    "pulgadas": ("largo", 0.0254),
    "w": ("potencia", 1), "watts": ("potencia", 1), "watt": ("potencia", 1),
    "v": ("voltaje", 1), "volts": ("voltaje", 1),
}
# Dimensiones que describen el contenido vendido (sirven para precio por unidad).
PACK_DIMENSIONS = ("masa", "volumen", "area", "conteo")
_DISPLAY_UNIT = {"masa": ("kg", 1000), "volumen": ("l", 1000), "area": ("m2", 1), "conteo": ("u", 1)}

_UNIT_ALTERNATION = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))
_NUMBER = r"\d+(?:[.,]\d+)?"
_FRACTION = r"(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)"
# Se permite una "x" pegada antes del numero: "6x1 1/4\"" es tornillo 6 x 1 1/4".
_QUANTITY_RE = re.compile(rf"(?<![0-9a-wyz_.,/])(?:{_FRACTION}|({_NUMBER}))\s*({_UNIT_ALTERNATION})(?![a-z0-9])")
# "set/kit de 100 piezas" son accesorios incluidos, no contenido vendible: no cuentan.
_COUNT_RE = re.compile(
    r"(?:(?:caja|pack|bolsa|paquete)\s*(?:de|x)?\s*(\d+)(?![.,]?\d)"
    r"|(\d+)\s*(?:unidades|unids?|uds?|un|u)(?![a-z0-9]))"
)

_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "para", "con", "sin", "y", "o", "en", "a", "al",
    "por", "un", "una", "x", "tipo", "marca", "color", "caja", "pack", "saco", "bolsa",
    "unidad", "unidades", "precio", "barato", "oferta",
}


@dataclass(frozen=True)
class Quantity:
    dimension: str
    value: float  # en unidad base

    def matches(self, other: "Quantity") -> bool:
        if self.dimension != other.dimension:
            return False
        largest = max(abs(self.value), abs(other.value), 1e-9)
        return abs(self.value - other.value) / largest <= SPEC_TOLERANCE


def canonical(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("”", '"').replace("''", '"')
    return re.sub(r"\s+", " ", value).strip()


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def extract_quantities(text: str) -> list[Quantity]:
    """Magnitudes declaradas en un texto: '25 kg', '1/2"', '0,25 l', 'caja 100 unidades'."""
    value = canonical(text)
    quantities: list[Quantity] = []
    for match in _QUANTITY_RE.finditer(value):
        whole, numerator, denominator, number, unit = match.groups()
        if number is not None:
            amount = _to_float(number)
        else:
            if int(denominator) == 0:
                continue
            amount = int(whole or 0) + int(numerator) / int(denominator)
        dimension, factor = _UNITS[unit]
        quantities.append(Quantity(dimension, amount * factor))
    for match in _COUNT_RE.finditer(value):
        count = next((int(group) for group in match.groups() if group), None)
        if count and count > 1:
            quantities.append(Quantity("conteo", float(count)))
    return quantities


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", canonical(text)) if token]


def core_terms(query: str) -> list[str]:
    """Terminos que identifican el producto (sin numeros, unidades ni relleno)."""
    terms = []
    for token in _tokens(query):
        if token in _STOPWORDS or token in _UNITS or re.fullmatch(r"\d+[a-z0-9]*", token):
            continue
        if len(token) < 3:
            continue
        stem = _stem(token)
        if stem not in terms:
            terms.append(stem)
    return terms


def relevance(query: str, title: str) -> float:
    """Fraccion de terminos nucleo presentes en el titulo (accesorios con credito parcial)."""
    terms = core_terms(query)
    if not terms:
        return 1.0
    text = canonical(title)
    head, _, tail = text.partition(" para ")
    head_stems = {_stem(token) for token in _tokens(head)}
    tail_stems = {_stem(token) for token in _tokens(tail)}
    score = 0.0
    for term in terms:
        if term in head_stems:
            score += 1.0
        elif term in tail_stems:
            score += ACCESSORY_CREDIT
    return round(score / len(terms), 3)


def spec_match(query: str, title: str) -> str:
    """'ok' si cumple todas las magnitudes pedidas, 'mismatch' si declara otra, 'unknown' si no informa."""
    wanted = extract_quantities(query)
    if not wanted:
        return "ok"
    offered = extract_quantities(title)
    status = "ok"
    for spec in wanted:
        same_dimension = [quantity for quantity in offered if quantity.dimension == spec.dimension]
        if not same_dimension:
            status = "unknown"
        elif not any(spec.matches(quantity) for quantity in same_dimension):
            return "mismatch"
    return status


def pack_content(title: str) -> tuple[float, str] | None:
    """Contenido vendido en unidad de despliegue: (25.0, 'kg'), (0.25, 'l'), (100.0, 'u')."""
    quantities = extract_quantities(title)
    for dimension in PACK_DIMENSIONS:
        candidates = [quantity.value for quantity in quantities if quantity.dimension == dimension]
        if candidates:
            unit, factor = _DISPLAY_UNIT[dimension]
            amount = max(candidates) / factor
            if amount > 0 and math.isfinite(amount):
                return amount, unit
    return None


def annotate_offers(query: str, offers: list) -> list:
    """Agrega relevance, spec_match, pack_quantity, unit y unit_price a cada oferta."""
    for offer in offers:
        offer.relevance = relevance(query, offer.title)
        offer.spec_match = spec_match(query, offer.title)
        content = pack_content(offer.title)
        if content and offer.extracted_price:
            offer.pack_quantity, offer.unit = content
            offer.unit_price = round(offer.extracted_price / offer.pack_quantity, 2)
        else:
            offer.pack_quantity = offer.unit = offer.unit_price = None
    return offers


def is_comparable(offer) -> bool:
    return (offer.relevance is None or offer.relevance >= RELEVANCE_THRESHOLD) and offer.spec_match != "mismatch"


def dominant_unit(offers: list) -> str | None:
    """Unidad compartida por la mayoria (>=60%) de las ofertas comparables con precio por unidad."""
    units = [offer.unit for offer in offers if offer.unit]
    if not units:
        return None
    unit = max(set(units), key=units.count)
    return unit if units.count(unit) / len(offers) >= 0.6 else None
