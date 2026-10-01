"""Optimizacion exacta (MILP): umbrales de despacho, costos fijos y verificacion por fuerza bruta."""
import itertools
import random

import pytest

from app.schemas import BasketLineRequest, BasketOptimizationRequest, ProductOffer, StoreTerms
from app.services.basket_optimizer import optimize_candidates, purchase_order_csv


def offer(store: str, price: float, title: str = "Material") -> ProductOffer:
    return ProductOffer(title=title, store=store, source="test", extracted_price=price, anomaly_flag="ok")


def request(n_lines: int, max_stores: int = 3, terms: dict | None = None) -> BasketOptimizationRequest:
    return BasketOptimizationRequest(
        lines=[BasketLineRequest(query=f"material {i}", quantity=1, unit="unidad") for i in range(n_lines)],
        max_stores=max_stores,
        store_terms=terms or {},
    )


def brute_force_total(req: BasketOptimizationRequest, candidates: list[list[ProductOffer]]) -> float:
    """Oraculo: prueba todas las asignaciones linea -> tienda."""
    per_line = [{o.store: o.extracted_price for o in line} for line in candidates]
    stores = sorted({store for line in per_line for store in line})
    best = float("inf")
    for assignment in itertools.product(stores, repeat=len(per_line)):
        if any(store not in per_line[i] for i, store in enumerate(assignment)):
            continue
        used = set(assignment)
        if len(used) > req.max_stores:
            continue
        total = 0.0
        for store in used:
            merchandise = sum(per_line[i][s] for i, s in enumerate(assignment) if s == store)
            terms = req.terms_for(store)
            free = terms.free_shipping_threshold is not None and merchandise >= terms.free_shipping_threshold
            total += merchandise + terms.fixed_cost + (0 if free else terms.shipping_cost)
        best = min(best, total)
    return best


def test_umbral_de_despacho_gratis_cambia_la_decision():
    # A es mas barato por linea pero cobra 10.000 de despacho bajo 50.000;
    # B cobra un poco mas, no alcanza nada gratis y despacha a 3.000.
    terms = {"A": StoreTerms(shipping_cost=10_000, free_shipping_threshold=50_000),
             "B": StoreTerms(shipping_cost=3_000)}
    candidates = [[offer("A", 20_000), offer("B", 21_000)], [offer("A", 20_000), offer("B", 21_000)]]
    result = optimize_candidates(request(2, terms=terms), candidates)
    assert result.stores == ["B"] and result.total_cost == 45_000

    # Con una tercera linea, A supera el umbral y conviene aunque sea "caro" despachar.
    candidates.append([offer("A", 15_000), offer("B", 16_000)])
    result = optimize_candidates(request(3, terms=terms), candidates)
    assert result.stores == ["A"] and result.total_cost == 55_000
    assert result.store_breakdown[0].free_shipping is True and result.shipping_total == 0


def test_costo_fijo_consolida_proveedores():
    candidates = [[offer("A", 10_000), offer("B", 10_500)], [offer("A", 10_500), offer("B", 10_000)]]
    split = optimize_candidates(request(2), candidates)
    assert split.stores == ["A", "B"] and split.total_cost == 20_000
    terms = {"A": StoreTerms(fixed_cost=2_000), "B": StoreTerms(fixed_cost=2_000)}
    consolidated = optimize_candidates(request(2, terms=terms), candidates)
    assert len(consolidated.stores) == 1 and consolidated.total_cost == 22_500
    assert consolidated.fixed_cost_total == 2_000


def test_respeta_maximo_de_tiendas():
    candidates = [[offer("A", 1), offer("B", 9)], [offer("B", 1), offer("A", 9)], [offer("C", 1), offer("A", 9)]]
    assert len(optimize_candidates(request(3, max_stores=1), candidates).stores) == 1
    assert len(optimize_candidates(request(3, max_stores=3), candidates).stores) == 3


def test_condiciones_sin_distinguir_mayusculas():
    candidates = [[offer("Sodimac", 10_000)]]
    result = optimize_candidates(request(1, terms={"sodimac": StoreTerms(shipping_cost=5_000)}), candidates)
    assert result.shipping_total == 5_000


@pytest.mark.parametrize("seed", range(25))
def test_coincide_con_fuerza_bruta(seed):
    rng = random.Random(seed)
    stores = ["A", "B", "C", "D"]
    terms = {
        store: StoreTerms(
            shipping_cost=rng.choice([0, 3_000, 8_000]),
            free_shipping_threshold=rng.choice([None, 20_000, 60_000]),
            fixed_cost=rng.choice([0, 0, 2_500]),
        )
        for store in stores
    }
    n_lines = rng.randint(2, 5)
    candidates = [
        [offer(store, rng.randint(2, 40) * 1_000) for store in rng.sample(stores, rng.randint(1, 4))]
        for _ in range(n_lines)
    ]
    req = request(n_lines, max_stores=rng.randint(1, 3), terms=terms)
    expected = brute_force_total(req, candidates)
    if expected == float("inf"):
        with pytest.raises(ValueError):
            optimize_candidates(req, candidates)
        return
    result = optimize_candidates(req, candidates)
    assert result.total_cost == pytest.approx(expected)
    assert result.solver == "milp-highs"


def test_orden_de_compra_csv():
    terms = {"A": StoreTerms(shipping_cost=4_000)}
    result = optimize_candidates(request(2, terms=terms),
                                 [[offer("A", 5_090, "Cemento 25 kg")], [offer("B", 12_990, "OSB 15 mm")]])
    csv_text = purchase_order_csv(result)
    assert csv_text.startswith("﻿Proveedor;Material solicitado")
    assert "A;material 0;Cemento 25 kg;1;unidad;;5090;;5090;" in csv_text
    assert "TOTAL;2;18080;4000;0;22080" in csv_text


class TestSearchAndOptimize:
    def _search_fn(self, calls, delay=0.0):
        import threading
        import time
        from types import SimpleNamespace

        lock = threading.Lock()

        def search_fn(query, **kwargs):
            with lock:
                calls.append(query)
            time.sleep(delay)
            price = 1_000 + 100 * int(query.split()[-1])
            return SimpleNamespace(offers=[offer("A", price, query), offer("B", price + 50, query)])
        return search_fn

    def test_paralelo_mantiene_orden_y_es_mas_rapido(self):
        import time

        from app.services.basket_optimizer import search_and_optimize

        calls = []
        req = request(6)
        started = time.perf_counter()
        result = search_and_optimize(req, self._search_fn(calls, delay=0.2), max_workers=3)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.8  # secuencial tomaria >= 1.2 s
        assert [s.query for s in result.selections] == [f"material {i}" for i in range(6)]
        assert [s.line_total for s in result.selections] == [1_000 + 100 * i for i in range(6)]

    def test_materiales_repetidos_se_buscan_una_vez(self):
        from app.services.basket_optimizer import search_and_optimize

        calls = []
        req = BasketOptimizationRequest(lines=[
            BasketLineRequest(query="material 1", quantity=1, unit="unidad"),
            BasketLineRequest(query="material 1", quantity=3, unit="unidad"),
        ])
        result = search_and_optimize(req, self._search_fn(calls), max_workers=3)
        assert calls == ["material 1"]
        assert [s.line_total for s in result.selections] == [1_100, 3_300]
