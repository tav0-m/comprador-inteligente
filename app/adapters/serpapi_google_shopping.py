import requests
from app.adapters.base import SearchAdapter
from app.core.config import settings
from app.schemas import ProductOffer

class SerpApiGoogleShoppingAdapter(SearchAdapter):
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if not settings.serpapi_key:
            return []

        params = {
            "engine": "google_shopping",
            "q": query,
            "api_key": settings.serpapi_key,
            "gl": country,
            "hl": settings.default_language,
            "num": max_results,
        }

        response = requests.get(
            "https://serpapi.com/search.json",
            params=params,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.user_agent},
        )
        response.raise_for_status()
        data = response.json()

        results = data.get("shopping_results", [])
        offers: list[ProductOffer] = []

        for item in results[:max_results]:
            offers.append(
                ProductOffer(
                    title=item.get("title") or "Producto sin título",
                    store=item.get("source"),
                    source="serpapi_google_shopping",
                    price_text=item.get("price"),
                    extracted_price=_to_float(item.get("extracted_price")),
                    currency="CLP",
                    delivery=item.get("delivery"),
                    availability=_join_list(item.get("extensions")),
                    rating=_to_float(item.get("rating")),
                    reviews=_to_int(item.get("reviews")),
                    link=item.get("link") or item.get("product_link"),
                    thumbnail=item.get("thumbnail"),
                )
            )

        return offers

def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None

def _to_int(value):
    try:
        if value is None:
            return None
        return int(str(value).replace(".", "").replace(",", ""))
    except Exception:
        return None

def _join_list(value):
    if isinstance(value, list):
        return " | ".join(str(x) for x in value)
    return value
