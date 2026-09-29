from __future__ import annotations

import re
import unicodedata


BLOCKED_TERMS = {
    "pistola", "arma", "municion", "cuchillo tactico", "navaja",
    "taser", "gas pimienta", "explosivo",
}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(char for char in value if not unicodedata.combining(char)).lower().strip()


def validate_query(query: str) -> str:
    """Valida y retorna la consulta limpia."""
    clean = re.sub(r"\s+", " ", (query or "").strip())
    if len(clean) < 2:
        raise ValueError("La busqueda debe contener al menos 2 caracteres.")
    if len(clean) > 120:
        raise ValueError("La busqueda no puede superar 120 caracteres.")

    normalized = _normalize(clean)
    for term in BLOCKED_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", normalized):
            raise ValueError("La busqueda no corresponde al alcance de materiales y herramientas permitidas.")
    return clean


def validate_country(country: str) -> str:
    normalized = (country or "").strip().lower()
    if normalized != "cl":
        raise ValueError("Por ahora solo se admite el mercado chileno (country=cl).")
    return normalized
