from pathlib import Path
import pandas as pd
from rapidfuzz import fuzz
from app.adapters.base import SearchAdapter
from app.schemas import ProductOffer

class LocalCSVAdapter(SearchAdapter):
    def __init__(self, path: str = "data/local_products.csv"):
        self.path = Path(path)

    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        if not self.path.exists():
            return []

        df = pd.read_csv(self.path)
        query_lower = query.lower().strip()

        rows = []
        for _, row in df.iterrows():
            title = str(row.get("title", ""))
            match_score = fuzz.token_set_ratio(query_lower, title.lower())
            if query_lower in title.lower() or match_score >= 55:
                rows.append((match_score, row))

        rows = sorted(rows, key=lambda x: x[0], reverse=True)[:max_results]

        offers = []
        for _, row in rows:
            offers.append(
                ProductOffer(
                    title=str(row["title"]),
                    store=str(row.get("store", "Proveedor Local")),
                    source="local_csv",
                    price_text=str(row.get("price_text", "")),
                    extracted_price=float(row["extracted_price"]),
                    currency=str(row.get("currency", "CLP")),
                    delivery=str(row.get("delivery", "")),
                    availability=str(row.get("availability", "")),
                    link=str(row.get("link", "")),
                    thumbnail=None,
                )
            )
        return offers
