"""Controles de abuso: doble opt-in de alertas, feedback deduplicado, IP real y rate limit."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def new_alert(client, email: str, query: str = "cemento 25 kg", price: float = 6000):
    return client.post("/alerts", json={"query": query, "target_price": price, "email": email})


def link_params(link: str) -> dict:
    params = parse_qs(urlparse(link).query)
    return {"id": params["id"][0], "token": params["token"][0]}


def db_session():
    from app.database import SessionLocal

    return SessionLocal()


class TestAlertDoubleOptIn:
    def test_alerta_nace_pendiente(self, client):
        response = new_alert(client, "pendiente@constructora.cl")
        assert response.status_code == 200
        assert response.json()["status"] == "pending_confirmation"

    def test_sin_confirmar_no_se_notifica(self, client):
        from app.models import PriceAlert, PriceHistory
        from app.services.alerts import check_alerts

        alert_id = new_alert(client, "sinconfirmar@constructora.cl", query="fierro 12 mm").json()["alert_id"]
        db = db_session()
        try:
            db.add(PriceHistory(query="fierro 12 mm", title="Fierro 12 mm", store="X", source="t", price=100))
            db.commit()
            assert all(match["alert_id"] != alert_id for match in check_alerts(db))
            assert db.get(PriceAlert, alert_id).confirmed is False
        finally:
            db.close()

    def test_confirmar_con_enlace_firmado(self, client):
        from app.models import PriceAlert
        from app.services.alerts import confirmation_link

        alert_id = new_alert(client, "confirma@constructora.cl").json()["alert_id"]
        db = db_session()
        try:
            link = confirmation_link(db.get(PriceAlert, alert_id))
        finally:
            db.close()
        response = client.get("/alerts/confirm", params=link_params(link))
        assert response.status_code == 200
        assert "Alerta confirmada" in response.text
        db = db_session()
        try:
            assert db.get(PriceAlert, alert_id).confirmed is True
        finally:
            db.close()

    def test_token_de_otra_alerta_es_rechazado(self, client):
        from app.models import PriceAlert
        from app.services.alerts import confirmation_link

        first = new_alert(client, "a@constructora.cl").json()["alert_id"]
        second = new_alert(client, "b@constructora.cl").json()["alert_id"]
        db = db_session()
        try:
            token = link_params(confirmation_link(db.get(PriceAlert, first)))["token"]
        finally:
            db.close()
        response = client.get("/alerts/confirm", params={"id": second, "token": token})
        assert response.status_code == 400

    def test_token_vencido(self, monkeypatch):
        from app.core import signing

        token = signing.make_token("alert-confirm", 1, ttl_seconds=60)
        monkeypatch.setattr(signing.time, "time", lambda: 10**11)
        assert signing.verify_token("alert-confirm", 1, token) is False

    def test_baja_con_enlace(self, client):
        from app.models import PriceAlert
        from app.services.alerts import unsubscribe_link

        alert_id = new_alert(client, "baja@constructora.cl").json()["alert_id"]
        db = db_session()
        try:
            link = unsubscribe_link(db.get(PriceAlert, alert_id))
        finally:
            db.close()
        assert client.get("/alerts/unsubscribe", params=link_params(link)).status_code == 200
        db = db_session()
        try:
            assert db.get(PriceAlert, alert_id).active is False
        finally:
            db.close()

    def test_limite_diario_por_email(self, client):
        email = "limite@constructora.cl"
        statuses = [new_alert(client, email, price=5000 + i).status_code for i in range(4)]
        assert statuses == [200, 200, 200, 429]


class TestFeedback:
    def _offer_id(self, created_at=None) -> int:
        from app.models import OfferLog

        db = db_session()
        try:
            row = OfferLog(title="Cemento 25 kg", store="Sodimac", source="sodimac", extracted_price=5090)
            if created_at:
                row.created_at = created_at
            db.add(row)
            db.commit()
            return row.id
        finally:
            db.close()

    def test_un_voto_por_cliente(self, client):
        from app.models import UserFeedback

        offer_id = self._offer_id()
        assert client.post("/feedback", json={"offer_log_id": offer_id, "useful": True}).status_code == 200
        assert client.post("/feedback", json={"offer_log_id": offer_id, "useful": False}).status_code == 200
        db = db_session()
        try:
            votes = db.query(UserFeedback).filter(UserFeedback.offer_log_id == offer_id).all()
            assert len(votes) == 1 and votes[0].useful is False
            assert votes[0].client_hash and "testclient" not in votes[0].client_hash
        finally:
            db.close()

    def test_oferta_antigua_rechazada(self, client):
        offer_id = self._offer_id(created_at=datetime.now(timezone.utc) - timedelta(days=30))
        assert client.post("/feedback", json={"offer_log_id": offer_id, "useful": True}).status_code == 404

    @pytest.mark.parametrize("votes, label", [([], 1), ([True], 2), ([False], 0), ([True, False], 1),
                                              ([True, True, False], 2)])
    def test_voto_mayoritario(self, votes, label):
        from app.services.model_training import label_from_votes

        assert label_from_votes(votes) == label


def fake_request(peer: str, forwarded: str | None = None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


class TestClientIp:
    def test_ignora_x_forwarded_for_de_cliente_directo(self):
        from app.core.client_ip import get_client_ip

        assert get_client_ip(fake_request("203.0.113.9", "1.2.3.4")) == "203.0.113.9"

    def test_usa_x_forwarded_for_desde_proxy_confiable(self):
        from app.core.client_ip import get_client_ip

        assert get_client_ip(fake_request("127.0.0.1", "198.51.100.7")) == "198.51.100.7"

    def test_ip_falsificada_a_la_izquierda_se_ignora(self):
        from app.core.client_ip import get_client_ip

        # El atacante envia "X-Forwarded-For: 1.1.1.1"; el proxy agrega su IP real.
        assert get_client_ip(fake_request("127.0.0.1", "1.1.1.1, 198.51.100.7")) == "198.51.100.7"


class TestRateLimit:
    def _app(self):
        from app.core.rate_limit import RateLimitMiddleware, RateRule

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, rules={("POST", "/x"): RateRule("x", 2, 60)})

        @app.post("/x")
        def limited():
            return {"ok": True}

        @app.get("/x")
        def unlimited():
            return {"ok": True}

        return TestClient(app)

    def test_limita_por_ruta_y_metodo(self):
        client = self._app()
        assert [client.post("/x").status_code for _ in range(3)] == [200, 200, 429]
        assert client.get("/x").status_code == 200

    def test_clientes_distintos_tras_proxy_no_comparten_cupo(self, monkeypatch):
        """Antes todos los usuarios detras del frontend compartian un solo cupo."""
        from app.core import rate_limit

        # Simula conexiones desde el proxy confiable: la IP real viene en X-Forwarded-For.
        monkeypatch.setattr(rate_limit, "get_client_ip", lambda request: request.headers["x-forwarded-for"])
        client = self._app()
        first = [client.post("/x", headers={"X-Forwarded-For": "198.51.100.1"}).status_code for _ in range(3)]
        second = client.post("/x", headers={"X-Forwarded-For": "198.51.100.2"}).status_code
        assert first == [200, 200, 429]
        assert second == 200


class TestHardening:
    def test_encabezados_de_seguridad(self, client):
        response = client.get("/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_resultado_de_tarea_no_filtra_excepciones(self, client, monkeypatch):
        import celery.result

        def boom(*args, **kwargs):
            raise RuntimeError("redis://usuario:clave@host secreto")

        monkeypatch.setattr(celery.result, "AsyncResult", boom)
        response = client.get("/search/result/abc")
        assert response.status_code == 503
        assert "secreto" not in response.text
