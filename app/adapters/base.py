from abc import ABC, abstractmethod
from app.schemas import ProductOffer

class SearchAdapter(ABC):
    @abstractmethod
    def search(self, query: str, country: str = "cl", max_results: int = 20) -> list[ProductOffer]:
        pass
