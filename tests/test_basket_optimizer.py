"""Pruebas de optimizacion exacta de la lista de materiales."""
import pytest

from app.schemas import BasketLineRequest, BasketOptimizationRequest, ProductOffer
from app.services.basket_optimizer import optimize_candidates


def offer(store: str, price: float, title: str) -> ProductOffer:
    return ProductOffer(
        title=title,
        store=store,
        source="test",
        extracted_price=price,
        anomaly_flag="ok",
    )


def request(max_stores=2, shipping_costs=None):
    return BasketOptimizationRequest(
        lines=[
            BasketLineRequest(query="cemento 25 kg", quantity=2, unit="saco"),
            BasketLineRequest(query="plancha OSB 9 mm", quantity=1, unit="plancha"),
        ],
        max_stores=max_stores,
        shipping_costs=shipping_costs or {},
    )


def test_finds_cheapest_cross_store_combination():
    result = optimize_candidates(
        request(),
        [
            [offer("A", 100, "Cemento A"), offer("B", 80, "Cemento B")],
            [offer("A", 100, "OSB A"), offer("B", 150, "OSB B")],
        ],
    )
    assert result.total_cost == 260
    assert result.single_store_baseline == 300
    assert result.estimated_savings == 40
    assert result.stores == ["A", "B"]


def test_shipping_can_change_the_optimum():
    result = optimize_candidates(
        request(shipping_costs={"B": 100}),
        [
            [offer("A", 100, "Cemento A"), offer("B", 80, "Cemento B")],
            [offer("A", 100, "OSB A"), offer("B", 150, "OSB B")],
        ],
    )
    assert result.stores == ["A"]
    assert result.total_cost == 300


def test_fails_when_a_line_has_no_comparable_offer():
    with pytest.raises(ValueError, match="No hay ofertas comparables"):
        optimize_candidates(request(), [[offer("A", 100, "Cemento")], []])


def test_linea_en_kg_compra_envases_enteros():
    """500 kg de cemento: 20 sacos de 25 kg ($5.090) vs 12 de 42,5 kg ($8.990)."""
    from app.services.specs import annotate_offers
    req = BasketOptimizationRequest(lines=[BasketLineRequest(query="cemento", quantity=500, unit="kg")], max_stores=2)
    candidates = annotate_offers("cemento", [
        offer("A", 5090, "Cemento 25 kg"),
        offer("B", 8990, "Cemento 42,5 kg"),
    ])
    result = optimize_candidates(req, [candidates])
    selection = result.selections[0]
    # A: 20 x 5.090 = 101.800 ; B: ceil(500/42,5)=12 x 8.990 = 107.880
    assert selection.offer.store == "A"
    assert selection.packs == 20
    assert result.total_cost == 101_800


def test_excluye_ofertas_de_otra_medida():
    from app.services.specs import annotate_offers
    req = BasketOptimizationRequest(lines=[BasketLineRequest(query="cemento 25 kg", quantity=2, unit="saco")])
    candidates = annotate_offers("cemento 25 kg", [
        offer("A", 890, "Cemento 1 kg"),
        offer("B", 5090, "Cemento 25 kg"),
    ])
    assert optimize_candidates(req, [candidates]).selections[0].offer.store == "B"
