from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class ProductOffer(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    store: str | None = Field(default=None, max_length=150)
    seller: str | None = Field(default=None, max_length=150)  # vendedor real en marketplaces
    source: str = Field(min_length=1, max_length=100)
    price_text: str | None = Field(default=None, max_length=100)
    extracted_price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="CLP", min_length=3, max_length=3)
    delivery: str | None = Field(default=None, max_length=500)
    availability: str | None = Field(default=None, max_length=250)
    rating: float | None = Field(default=None, ge=0, le=5)
    reviews: int | None = Field(default=None, ge=0)
    link: str | None = None
    thumbnail: str | None = None
    score: float | None = None
    recommendation: str | None = None
    ml_score: float | None = None
    price_percentile: float | None = None
    anomaly_flag: Literal["ok", "precio_muy_alto", "precio_muy_bajo", "sin_precio"] | None = None
    semantic_group: int | None = None
    price_vs_avg_pct: float | None = None
    free_shipping: bool | None = None
    offer_log_id: int | None = None
    # Relevancia por especificacion y precio por unidad (app.services.specs)
    relevance: float | None = Field(default=None, ge=0, le=1)
    spec_match: Literal["ok", "unknown", "mismatch"] | None = None
    pack_quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=10)
    unit_price: float | None = Field(default=None, ge=0)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class SearchResponse(BaseModel):
    query: str
    country: str = "cl"
    city: str | None = None
    total_results: int
    offers: list[ProductOffer]
    best_price: float | None = None
    avg_price: float | None = None
    price_spread_pct: float | None = None
    anomaly_count: int = 0
    comparable_count: int = 0  # ofertas que cumplen producto y especificacion buscados
    unit: str | None = None  # unidad comun de las comparables (kg, l, m2, u)
    best_unit_price: float | None = None
    search_id: int | None = None
    elapsed_ms: int | None = None


class PriceHistoryPoint(BaseModel):
    date: datetime
    store: str
    price: float
    source: str
    link: str | None = None


class FeedbackRequest(BaseModel):
    offer_log_id: int = Field(gt=0)
    useful: bool
    comment: str | None = Field(default=None, max_length=1_000)


class AlertCreateRequest(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    target_price: float = Field(gt=0, le=30_000_000)
    email: EmailStr
    store_filter: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class StatsResponse(BaseModel):
    total_searches: int
    total_offers_logged: int
    top_queries: list[dict]
    avg_score: float | None = None
    stores_seen: list[str]


class BasketLineRequest(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    quantity: float = Field(default=1, gt=0, le=100_000)
    unit: str = Field(default="unidad", min_length=1, max_length=40)


class BasketOptimizationRequest(BaseModel):
    lines: list[BasketLineRequest] = Field(min_length=1, max_length=12)
    country: str = Field(default="cl", pattern="^[a-zA-Z]{2}$")
    city: str | None = Field(default=None, max_length=100)
    max_stores: int = Field(default=3, ge=1, le=6)
    max_results_per_line: int = Field(default=12, ge=3, le=30)
    shipping_costs: dict[str, float] = Field(default_factory=dict)

    @field_validator("shipping_costs")
    @classmethod
    def non_negative_shipping(cls, value: dict[str, float]) -> dict[str, float]:
        if any(cost < 0 or cost > 10_000_000 for cost in value.values()):
            raise ValueError("Los costos de despacho deben estar entre 0 y 10.000.000 CLP")
        return value


class BasketSelection(BaseModel):
    query: str
    quantity: float
    unit: str
    offer: ProductOffer
    packs: float | None = None  # envases a comprar cuando la linea se expresa en kg, l, m2 o u
    line_total: float


class BasketOptimizationResponse(BaseModel):
    selections: list[BasketSelection]
    stores: list[str]
    merchandise_total: float
    shipping_total: float
    total_cost: float
    single_store_baseline: float | None = None
    estimated_savings: float | None = None
    assumptions: list[str]
    elapsed_ms: int
