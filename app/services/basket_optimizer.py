from __future__ import annotations

import itertools
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.schemas import (
    BasketOptimizationRequest,
    BasketOptimizationResponse,
    BasketSelection,
    ProductOffer,
)
from app.services.product_guardrails import validate_country, validate_query
from app.services.specs import is_comparable


# Unidad de la linea -> (unidad de precio por unidad, factor). "unidad" (singular,
# valor por defecto) se mantiene como "un envase"; "unidades" cuenta piezas.
LINE_UNITS = {
    "kg": ("kg", 1.0), "kilo": ("kg", 1.0), "kilos": ("kg", 1.0), "kgs": ("kg", 1.0),
    "g": ("kg", 0.001), "gr": ("kg", 0.001), "gramos": ("kg", 0.001),
    "ton": ("kg", 1000.0), "tonelada": ("kg", 1000.0), "toneladas": ("kg", 1000.0),
    "l": ("l", 1.0), "lt": ("l", 1.0), "litro": ("l", 1.0), "litros": ("l", 1.0),
    "ml": ("l", 0.001), "cc": ("l", 0.001),
    "m2": ("m2", 1.0), "mt2": ("m2", 1.0), "m²": ("m2", 1.0),
    "u": ("u", 1.0), "un": ("u", 1.0), "unidades": ("u", 1.0), "piezas": ("u", 1.0),
}


@dataclass(frozen=True)
class LineCandidate:
    offer: ProductOffer
    packs: float | None  # envases a comprar; None si la linea ya se expresa en envases
    cost: float


def line_candidates(line, offers: list[ProductOffer]) -> list[LineCandidate]:
    """Costo de cubrir la linea con cada oferta, comprando envases enteros.

    Si la linea se expresa en kg/l/m2/unidades y la oferta declara su contenido,
    se compran ceil(cantidad / contenido) envases; si ninguna oferta lo declara,
    se asume que la cantidad ya esta en envases.
    """
    target = LINE_UNITS.get(line.unit.strip().casefold())
    measured = []
    if target:
        unit, factor = target
        needed = line.quantity * factor
        for offer in offers:
            if offer.unit == unit and offer.pack_quantity:
                packs = math.ceil(needed / offer.pack_quantity - 1e-9)
                measured.append(LineCandidate(offer, float(packs), packs * offer.extracted_price))
    if measured:
        return measured
    return [LineCandidate(offer, None, line.quantity * offer.extracted_price) for offer in offers]


def optimize_candidates(
    request: BasketOptimizationRequest,
    candidates_by_line: list[list[ProductOffer]],
) -> BasketOptimizationResponse:
    started = time.perf_counter()
    if len(candidates_by_line) != len(request.lines):
        raise ValueError("La cantidad de grupos de ofertas no coincide con las lineas de materiales.")

    filtered: list[dict[str, LineCandidate]] = []
    packs_assumed = []
    for line, candidates in zip(request.lines, candidates_by_line):
        valid = [
            offer for offer in candidates
            if offer.extracted_price and offer.extracted_price > 0
            and offer.anomaly_flag in (None, "ok") and is_comparable(offer)
        ]
        if not valid:
            raise ValueError(f"No hay ofertas comparables para '{line.query}'.")
        options = line_candidates(line, valid)
        if LINE_UNITS.get(line.unit.strip().casefold()) and options[0].packs is None:
            packs_assumed.append(line.query)
        cheapest_by_store: dict[str, LineCandidate] = {}
        for option in options:
            store = option.offer.store or "Tienda no identificada"
            current = cheapest_by_store.get(store)
            if current is None or option.cost < current.cost:
                cheapest_by_store[store] = option
        filtered.append(cheapest_by_store)

    all_stores = sorted({store for candidates in filtered for store in candidates})
    best = None
    max_size = min(request.max_stores, len(all_stores))
    for size in range(1, max_size + 1):
        for subset in itertools.combinations(all_stores, size):
            selections = []
            feasible = True
            for line, options in zip(request.lines, filtered):
                available = [option for store, option in options.items() if store in subset]
                if not available:
                    feasible = False
                    break
                selections.append((line, min(available, key=lambda item: item.cost)))
            if not feasible:
                continue
            used_stores = {option.offer.store or "Tienda no identificada" for _, option in selections}
            merchandise = sum(option.cost for _, option in selections)
            shipping = sum(request.shipping_costs.get(store, 0.0) for store in used_stores)
            total = merchandise + shipping
            if best is None or total < best[0]:
                best = (total, merchandise, shipping, selections, sorted(used_stores))

    if best is None:
        raise ValueError("No existe una combinacion factible con el maximo de tiendas indicado.")

    single_store_totals = []
    for store in all_stores:
        if all(store in options for options in filtered):
            merchandise = sum(options[store].cost for options in filtered)
            single_store_totals.append(merchandise + request.shipping_costs.get(store, 0.0))
    baseline = min(single_store_totals) if single_store_totals else None
    total, merchandise, shipping, raw_selections, stores = best
    assumptions = [
        "Cada linea debe describir una especificacion comparable (marca, medida, formato y unidad).",
        "La optimizacion usa precios publicados; confirma stock y precio final antes de comprar.",
        "Lineas en kg, l, m2 o unidades se cubren con envases enteros segun el contenido del producto.",
    ]
    if packs_assumed:
        assumptions.append(
            "Sin contenido declarado en las ofertas de: " + ", ".join(packs_assumed)
            + "; la cantidad se interpreto como numero de envases."
        )
    if not request.shipping_costs:
        assumptions.append("No se informaron costos de despacho; el total los considera iguales a cero.")

    return BasketOptimizationResponse(
        selections=[
            BasketSelection(
                query=line.query,
                quantity=line.quantity,
                unit=line.unit,
                offer=option.offer,
                packs=option.packs,
                line_total=round(option.cost, 0),
            )
            for line, option in raw_selections
        ],
        stores=stores,
        merchandise_total=round(merchandise, 0),
        shipping_total=round(shipping, 0),
        total_cost=round(total, 0),
        single_store_baseline=round(baseline, 0) if baseline is not None else None,
        estimated_savings=round(baseline - total, 0) if baseline is not None else None,
        assumptions=assumptions,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )


def search_and_optimize(
    request: BasketOptimizationRequest,
    search_fn: Callable[..., object],
) -> BasketOptimizationResponse:
    request.country = validate_country(request.country)
    candidates = []
    for line in request.lines:
        line.query = validate_query(line.query)
        response = search_fn(
            query=line.query,
            country=request.country,
            city=request.city,
            max_results=request.max_results_per_line,
            use_cache=True,
        )
        candidates.append(response.offers)
    return optimize_candidates(request, candidates)
