"""Pruebas del ranking explicable y del entrenamiento con feedback real."""
import pandas as pd
import pytest

from app.schemas import ProductOffer
from app.services.ml_ranker import FEATURE_COLS, feature_engineering, get_ranker, rank_with_ml


def make_offer(**kwargs) -> ProductOffer:
    values = {
        "title": "Taladro Bosch 550W",
        "store": "Sodimac",
        "source": "sodimac",
        "extracted_price": 45990,
        "currency": "CLP",
        "anomaly_flag": "ok",
    }
    values.update(kwargs)
    return ProductOffer(**values)


class TestFeatureEngineering:
    def test_contract(self):
        frame = feature_engineering([make_offer(), make_offer(store="Easy", source="easy")], "taladro")
        assert isinstance(frame, pd.DataFrame)
        assert list(frame.columns) == FEATURE_COLS
        assert len(frame) == 2

    def test_missing_price_is_safe(self):
        frame = feature_engineering([make_offer(extracted_price=None)], "taladro")
        assert frame["price_log"].iloc[0] == pytest.approx(0)

    def test_relevance_and_free_shipping(self):
        offers = [
            make_offer(title="taladro percutor bosch", delivery="Envio gratis"),
            make_offer(title="brocha de pintura", delivery="Despacho $4.990"),
        ]
        frame = feature_engineering(offers, "taladro percutor")
        assert frame["title_sim"].iloc[0] > frame["title_sim"].iloc[1]
        assert frame["has_free_shipping"].tolist() == [1, 0]


class TestRanker:
    def test_mode_is_explicit(self):
        ranker = get_ranker()
        assert ranker.mode in {"heuristic", "feedback_model"}
        assert ranker.status()["mode"] == ranker.mode

    def test_scores_are_bounded_and_sorted(self):
        offers = [
            make_offer(extracted_price=45990, rating=4.8, reviews=250, delivery="Envio gratis"),
            make_offer(title="Taladro generico", extracted_price=89990),
        ]
        ranked = rank_with_ml("taladro", offers)
        assert ranked[0].ml_score >= ranked[1].ml_score
        assert all(0 <= offer.ml_score <= 100 for offer in ranked)

    def test_feature_importance_is_explainable(self):
        importance = get_ranker().feature_importance()
        assert importance
        assert all(value >= 0 for value in importance.values())

    def test_training_rejects_insufficient_feedback(self):
        frame = feature_engineering([make_offer(), make_offer(store="Easy")], "taladro")
        frame["label"] = [2, 0]
        frame["group_id"] = [1, 1]
        with pytest.raises(ValueError, match="100 ofertas"):
            get_ranker().train_from_feedback(frame)


class TestScaleRankerScores:
    def test_negativos_conservan_orden(self):
        """LambdaRank produce scores negativos; recortar a [0,100] los empataba en 0."""
        from app.services.ml_ranker import scale_ranker_scores
        scaled = scale_ranker_scores([-2.5, -0.3, -1.1])
        assert scaled.tolist() == pytest.approx([0.0, 100.0, 63.6364], rel=1e-3)

    def test_scores_iguales(self):
        from app.services.ml_ranker import scale_ranker_scores
        assert scale_ranker_scores([0.7, 0.7]).tolist() == [50.0, 50.0]


class TestRelevanceRanking:
    def test_comparables_antes_que_producto_distinto(self):
        from app.services.specs import annotate_offers
        offers = annotate_offers("cemento 25 kg", [
            make_offer(title="Arena fina 25 kg", extracted_price=970),
            make_offer(title="Cemento gris 1 kg", extracted_price=890),
            make_offer(title="Cemento especial 25 kg", extracted_price=5090),
        ])
        ranked = rank_with_ml("cemento 25 kg", offers)
        assert ranked[0].title == "Cemento especial 25 kg"

    def test_sin_stock_no_cuenta_como_stock(self):
        frame = feature_engineering([make_offer(availability="Sin stock")], "taladro")
        assert frame["has_stock"].iloc[0] == 0

    def test_heuristica_acotada_sin_saturar(self):
        frame = feature_engineering([make_offer(), make_offer(extracted_price=60000)], "taladro")
        from app.services.ml_ranker import heuristic_scores
        scores = heuristic_scores(frame)
        assert (scores <= 100).all() and scores[0] > scores[1]
