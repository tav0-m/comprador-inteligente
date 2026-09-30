"""Optimizacion exacta de la lista de materiales entre proveedores (MILP).

Modelo (resuelto con HiGHS via scipy.optimize.milp):

    x[i,s] = 1 si la linea i se compra en la tienda s
    y[s]   = 1 si se usa la tienda s
    z[s]   = 1 si la tienda s alcanza su umbral de despacho gratis

    min  sum c[i,s] x[i,s] + sum (fijo[s] + despacho[s]) y[s] - sum despacho[s] z[s]
    s.a. sum_s x[i,s] = 1                          (cada linea en una tienda)
         x[i,s] <= y[s]                            (solo tiendas usadas)
         sum_s y[s] <= max_stores
         z[s] <= y[s]
         sum_i c[i,s] x[i,s] >= umbral[s] z[s]     (despacho gratis solo sobre el umbral)

c[i,s] es el costo de cubrir la linea i en la tienda s con su mejor oferta
comparable, comprando envases enteros. La busqueda exhaustiva anterior crecia
combinatoriamente con las tiendas y no modelaba umbrales ni costos fijos.
"""
from __future__ import annotations

import csv
import io
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from app.schemas import (
    BasketOptimizationRequest,
    BasketOptimizationResponse,
    BasketSelection,
    ProductOffer,
    StoreBreakdown,
)
from app.services.product_guardrails import validate_country, validate_query
from app.services.specs import is_comparable

SOLVER_TIME_LIMIT_SECONDS = 10
UNKNOWN_STORE = "Tienda no identificada"

# Unidad de la linea -> (unidad de precio por unidad, factor). "unidad" (singular,
# valor por defecto) se mantiene como "un envase"; "unidades" cuenta piezas.
LINE_UNITS = {
    "kg": ("kg", 1.0), "kilo": ("kg", 1.0), "kilos": ("kg", 1.0), "kgs": ("kg", 1.0),
    "g": ("kg", 0.001), "gr": ("kg", 0.001), "gramos": ("kg", 0.001),
    "ton": ("kg", 1000.0), "tonelada": ("kg", 1000.0), "toneladas": ("kg", 1000.0),
    "l": ("l", 1.0), "lt": ("l", 1.0), "litro": ("l", 1.0), "litros": ("l", 1.0),
    "cc": ("l", 0.001),
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


def _cheapest_by_store(request: BasketOptimizationRequest, candidates_by_line: list[list[ProductOffer]]):
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
        cheapest: dict[str, LineCandidate] = {}
        for option in options:
            store = option.offer.store or UNKNOWN_STORE
            if store not in cheapest or option.cost < cheapest[store].cost:
                cheapest[store] = option
        filtered.append(cheapest)
    return filtered, packs_assumed


def _solve(request: BasketOptimizationRequest, filtered: list[dict[str, LineCandidate]], stores: list[str]):
    """Resuelve el MILP y retorna {indice_linea: tienda}."""
    options = [(i, store) for i, by_store in enumerate(filtered) for store in by_store]
    n_x, n_s = len(options), len(stores)
    y0, z0 = n_x, n_x + n_s
    n = n_x + 2 * n_s
    store_index = {store: j for j, store in enumerate(stores)}
    terms = [request.terms_for(store) for store in stores]

    cost = np.zeros(n)
    for k, (i, store) in enumerate(options):
        cost[k] = filtered[i][store].cost
    for j, term in enumerate(terms):
        cost[y0 + j] = term.fixed_cost + term.shipping_cost
        cost[z0 + j] = -term.shipping_cost

    rows, lower, upper = [], [], []

    def add(coefficients: dict[int, float], lb: float, ub: float):
        row = np.zeros(n)
        for index, value in coefficients.items():
            row[index] = value
        rows.append(row)
        lower.append(lb)
        upper.append(ub)

    for i in range(len(filtered)):
        add({k: 1.0 for k, (line, _) in enumerate(options) if line == i}, 1, 1)
    for k, (_, store) in enumerate(options):
        add({k: 1.0, y0 + store_index[store]: -1.0}, -np.inf, 0)
    add({y0 + j: 1.0 for j in range(n_s)}, -np.inf, request.max_stores)
    upper_bounds = np.ones(n)
    for j, term in enumerate(terms):
        add({z0 + j: 1.0, y0 + j: -1.0}, -np.inf, 0)
        if term.free_shipping_threshold is None or term.shipping_cost <= 0:
            upper_bounds[z0 + j] = 0  # sin umbral (o despacho ya gratis) z no aporta
            continue
        coefficients = {k: filtered[i][store].cost for k, (i, store) in enumerate(options) if store == stores[j]}
        coefficients[z0 + j] = -term.free_shipping_threshold
        add(coefficients, 0, np.inf)

    result = milp(
        cost,
        constraints=LinearConstraint(np.array(rows), np.array(lower), np.array(upper)),
        integrality=np.ones(n),
        bounds=Bounds(np.zeros(n), upper_bounds),
        options={"time_limit": SOLVER_TIME_LIMIT_SECONDS},
    )
    if result.x is None or result.status not in (0, 1):  # 1 = limite de tiempo con solucion factible
        raise ValueError("No existe una combinacion factible con el maximo de tiendas indicado.")
    chosen = {}
    for k, (i, store) in enumerate(options):
        if result.x[k] > 0.5:
            chosen[i] = store
    return chosen, result.status == 0


def _store_cost(request: BasketOptimizationRequest, store: str, merchandise: float, lines: int) -> StoreBreakdown:
    term = request.terms_for(store)
    threshold = term.free_shipping_threshold
    free = term.shipping_cost <= 0 or (threshold is not None and merchandise >= threshold)
    shipping = 0.0 if free else term.shipping_cost
    return StoreBreakdown(
        store=store, lines=lines, merchandise=round(merchandise, 0), shipping=round(shipping, 0),
        fixed_cost=round(term.fixed_cost, 0), free_shipping=free and term.shipping_cost > 0,
        total=round(merchandise + shipping + term.fixed_cost, 0),
    )


def optimize_candidates(
    request: BasketOptimizationRequest,
    candidates_by_line: list[list[ProductOffer]],
) -> BasketOptimizationResponse:
    started = time.perf_counter()
    if len(candidates_by_line) != len(request.lines):
        raise ValueError("La cantidad de grupos de ofertas no coincide con las lineas de materiales.")

    filtered, packs_assumed = _cheapest_by_store(request, candidates_by_line)
    stores = sorted({store for by_store in filtered for store in by_store})
    chosen, proven_optimal = _solve(request, filtered, stores)

    by_store: dict[str, list[int]] = {}
    for i, store in chosen.items():
        by_store.setdefault(store, []).append(i)
    breakdown = [
        _store_cost(request, store, sum(filtered[i][store].cost for i in lines), len(lines))
        for store, lines in sorted(by_store.items())
    ]
    merchandise = sum(item.merchandise for item in breakdown)
    shipping = sum(item.shipping for item in breakdown)
    fixed = sum(item.fixed_cost for item in breakdown)
    total = merchandise + shipping + fixed

    single_store_totals = [
        _store_cost(request, store, sum(options[store].cost for options in filtered), len(filtered)).total
        for store in stores
        if all(store in options for options in filtered)
    ]
    baseline = min(single_store_totals) if single_store_totals else None

    assumptions = [
        "Cada linea debe describir una especificacion comparable (marca, medida, formato y unidad).",
        "La optimizacion usa precios publicados; confirma stock y precio final antes de comprar.",
        "Lineas en kg, l, m2 o unidades se cubren con envases enteros segun el contenido del producto.",
        "En cada tienda se considera la oferta comparable de menor costo para cada linea.",
    ]
    if packs_assumed:
        assumptions.append(
            "Sin contenido declarado en las ofertas de: " + ", ".join(packs_assumed)
            + "; la cantidad se interpreto como numero de envases."
        )
    if not request.store_terms and not request.shipping_costs:
        assumptions.append("No se informaron condiciones de despacho; el total las considera iguales a cero.")
    if not proven_optimal:
        assumptions.append("El optimizador alcanzo su limite de tiempo: la solucion es factible pero no probada optima.")

    return BasketOptimizationResponse(
        selections=[
            BasketSelection(
                query=line.query,
                quantity=line.quantity,
                unit=line.unit,
                offer=filtered[i][chosen[i]].offer,
                packs=filtered[i][chosen[i]].packs,
                line_total=round(filtered[i][chosen[i]].cost, 0),
            )
            for i, line in enumerate(request.lines)
        ],
        stores=sorted(by_store),
        store_breakdown=breakdown,
        merchandise_total=round(merchandise, 0),
        shipping_total=round(shipping, 0),
        fixed_cost_total=round(fixed, 0),
        total_cost=round(total, 0),
        single_store_baseline=round(baseline, 0) if baseline is not None else None,
        estimated_savings=round(baseline - total, 0) if baseline is not None else None,
        solver="milp-highs" if proven_optimal else "milp-highs (limite de tiempo)",
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


def purchase_order_csv(result: BasketOptimizationResponse) -> str:
    """Orden de compra agrupada por proveedor (CSV ';' con BOM, abre directo en Excel)."""
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([
        "Proveedor", "Material solicitado", "Producto", "Cantidad pedida", "Unidad",
        "Envases", "Precio envase CLP", "Precio por unidad", "Total linea CLP", "Enlace",
    ])
    selections = sorted(result.selections, key=lambda item: (item.offer.store or "", item.query))
    for selection in selections:
        offer = selection.offer
        unit_price = f"{_number(round(offer.unit_price, 2))} CLP/{offer.unit}" if offer.unit_price and offer.unit else ""
        writer.writerow([
            offer.store or UNKNOWN_STORE, selection.query, offer.title, _number(selection.quantity),
            selection.unit, _number(selection.packs) if selection.packs else "",
            _number(offer.extracted_price), unit_price, _number(selection.line_total), offer.link or "",
        ])
    writer.writerow([])
    writer.writerow(["Proveedor", "Lineas", "Mercaderia CLP", "Despacho CLP", "Costo fijo CLP", "Total CLP"])
    for item in result.store_breakdown:
        writer.writerow([item.store, item.lines, _number(item.merchandise), _number(item.shipping),
                         _number(item.fixed_cost), _number(item.total)])
    writer.writerow(["TOTAL", len(result.selections), _number(result.merchandise_total),
                     _number(result.shipping_total), _number(result.fixed_cost_total), _number(result.total_cost)])
    return buffer.getvalue()


def _number(value: float | None) -> str:
    """Formato numerico chileno para Excel: coma decimal, sin separador de miles."""
    if value is None:
        return ""
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}".replace(".", ",")
