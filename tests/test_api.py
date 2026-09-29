"""Pruebas contractuales de la API FastAPI."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


class TestHealthEndpoints:
    def test_health_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["version"] == "5.0.0"
        assert payload["database"] is True
        assert payload["ranking_mode"] in {"heuristic", "feedback_model"}

    def test_stats_ok(self, client):
        response = client.get("/stats")
        assert response.status_code == 200
        assert {"total_searches", "total_offers_logged", "cache"} <= response.json().keys()


class TestSearchEndpoint:
    def test_search_without_sources_is_valid(self, client):
        response = client.get("/search", params={"q": "martillo"})
        assert response.status_code == 200
        assert response.json()["offers"] == []

    @pytest.mark.parametrize("query", ["", "a" * 121])
    def test_invalid_query_rejected(self, client, query):
        assert client.get("/search", params={"q": query}).status_code == 422

    def test_max_results_limit(self, client):
        assert client.get("/search", params={"q": "tornillo", "max_results": 100}).status_code == 422

    def test_unsupported_country_rejected(self, client):
        response = client.get("/search", params={"q": "cemento", "country": "xx"})
        assert response.status_code == 400

    def test_response_contract(self, client):
        response = client.get("/search", params={"q": "taladro", "cache": "false"})
        payload = response.json()
        assert response.status_code == 200
        assert payload["query"] == "taladro"
        assert payload["country"] == "cl"
        assert payload["total_results"] == 0
        assert isinstance(payload["elapsed_ms"], int)


class TestAlertsAndSecurity:
    def test_create_valid_alert(self, client):
        response = client.post(
            "/alerts",
            json={"query": "cemento 25kg", "target_price": 8000, "email": "test@constructora.cl"},
        )
        assert response.status_code == 200
        assert response.json()["alert_id"] > 0

    def test_invalid_alert_rejected(self, client):
        response = client.post(
            "/alerts",
            json={"query": "martillo", "target_price": 0, "email": "correo-invalido"},
        )
        assert response.status_code == 422

    def test_admin_route_requires_key(self, client):
        assert client.get("/alerts").status_code == 401

    def test_admin_route_accepts_key(self, client):
        response = client.get("/alerts", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_delete_missing_alert(self, client):
        response = client.delete("/alerts/99999", headers=ADMIN_HEADERS)
        assert response.status_code == 404


class TestHistoryAndRanking:
    def test_price_history(self, client):
        response = client.get("/price-history", params={"q": "tornillo"})
        assert response.status_code == 200
        assert response.json()["history"] == []

    def test_general_history(self, client):
        response = client.get("/history")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_feature_importance(self, client):
        response = client.get("/feature-importance")
        assert response.status_code == 200
        assert response.json()["feature_importance"]

    def test_retrain_requires_admin_and_real_feedback(self, client):
        assert client.post("/retrain").status_code == 401
        response = client.post("/retrain", headers=ADMIN_HEADERS)
        assert response.status_code == 400
        assert "feedback real" in response.json()["detail"].lower()

    def test_feedback_requires_existing_offer(self, client):
        response = client.post("/feedback", json={"offer_log_id": 99999, "useful": True})
        assert response.status_code == 404
