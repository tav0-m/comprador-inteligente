from __future__ import annotations

import itertools
import time
from collections.abc import Callable

from app.schemas import (
    BasketOptimizationRequest,
    BasketOptimizationResponse,
    BasketSelection,
    ProductOffer,
)
from app.services.product_guardrails import validate_country, validate_query


def optimize_candidates(
    request: BasketOptimizationRequest,
    candidates_by_line: list[list[ProductOffer]],
) -> BasketOptimizationResponse:
    started = time.perf_counter()
    if len(candidates_by_line) != len(request.lines):
        raise ValueError("La cantidad de grupos de ofertas no coincide con las lineas de materiales.")

    filtered = []
    for line, candidates in zip(request.lines, candidates_by_line):
        valid = [
            offer for offer in candidates
            if offer.extracted_price and offer.extracted_price > 0 and offer.anomaly_flag in (None, "ok")
        ]
        if not valid:
            raise ValueError(f"No hay ofertas comparables para '{line.query}'.")
        cheapest_by_store = {}
        for offer in valid:
            store = offer.store or "Tienda no identificada"
            current = cheapest_by_store.get(store)
            if current is None or offer.extracted_price < current.extracted_price:
                cheapest_by_store[store] = offer
        filtered.append(cheapest_by_store)

    all_stores = sorted({store for candidates in filtered for store in candidates})
    best = None
    max_size = min(request.max_stores, len(all_stores))
    for size in range(1, max_size + 1):
        for subset in itertools.combinations(all_stores, size):
            selections = []
            feasible = True
            for line, offers in zip(request.lines, filtered):
                available = [offer for store, offer in offers.items() if store in subset]
                if not available:
                    feasible = False
                    break
                offer = min(available, key=lambda item: item.extracted_price)
                selections.append((line, offer))
            if not feasible:
                continue
            used_stores = {offer.store or "Tienda no identificada" for _, offer in selections}
            merchandise = sum(line.quantity * offer.extracted_price for line, offer in selections)
            shipping = sum(request.shipping_costs.get(store, 0.0) for store in used_stores)
            total = merchandise + shipping
            if best is None or total < best[0]:
                best = (total, merchandise, shipping, selections, sorted(used_stores))

    if best is None:
        raise ValueError("No existe una combinacion factible con el maximo de tiendas indicado.")

    single_store_totals = []
    for store in all_stores:
        if all(store in offers for offers in filtered):
            merchandise = sum(
                line.quantity * offers[store].extracted_price
                for line, offers in zip(request.lines, filtered)
            )
            single_store_totals.append(merchandise + request.shipping_costs.get(store, 0.0))
    baseline = min(single_store_totals) if single_store_totals else None
    total, merchandise, shipping, raw_selections, stores = best
    assumptions = [
        "Cada linea debe describir una especificacion comparable (marca, medida, formato y unidad).",
        "La optimizacion usa precios publicados; confirma stock y precio final antes de comprar.",
    ]
    if not request.shipping_costs:
        assumptions.append("No se informaron costos de despacho; el total los considera iguales a cero.")

    return BasketOptimizationResponse(
        selections=[
            BasketSelection(
                query=line.query,
                quantity=line.quantity,
                unit=line.unit,
                offer=offer,
                line_total=round(line.quantity * offer.extracted_price, 0),
            )
            for line, offer in raw_selections
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
