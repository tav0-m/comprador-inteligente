"""Catalogo propio: persistencia, lectura fresca, serie diaria e ingesta programada."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.schemas import ProductOffer
from app.services import buyer_service, catalog, sources
from app.services.sources import SourceRun


def offer(title: str, price: float, store: str = "Sodimac", link: str | None = None) -> ProductOffer:
    slug = title.lower().replace(" ", "-")
    return ProductOffer(
        title=title, store=store, source=store.lower(), extracted_price=price,
        link=link or f"https://tienda.cl/{store.lower()}/{slug}?utm=x",
    )


def fake_fetch(offers_factory, calls: list):
    def fetch(query, country, limit):
        calls.append(query)
        items = offers_factory()
        runs = [SourceRun(source=name, offers=sum(o.source == name for o in items), duration_ms=5)
                for name in {o.source for o in items}]
        return items, runs
    return fetch


@pytest.fixture
def db():
    from app.database import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


class TestIdentity:
    def test_url_key_ignora_parametros_de_seguimiento(self):
        assert catalog.url_key("easy", "https://Easy.cl/cemento/p?utm=1#x", "t") == \
            catalog.url_key("easy", "https://easy.cl/cemento/p/", "otro titulo")

    def test_query_key_normaliza(self):
        assert catalog.query_key("  Plancha  Yeso-Cartón ") == "plancha yeso-carton"


class TestRecordOffers:
    def test_upsert_y_observacion_diaria(self, db):
        from app.models import CatalogProduct, IngestionRun, PriceObservation

        items = [offer("Cemento especial 25 kg", 5090), offer("Cemento especial 25 kg", 5090)]  # duplicado
        runs = [SourceRun("sodimac", 2, 10)]
        assert catalog.record_offers(db, "cemento upsert", items, runs, trigger="live") == 1
        catalog.record_offers(db, "cemento upsert", [offer("Cemento especial 25 kg", 4790)], [], trigger="live")

        product = db.query(CatalogProduct).filter(CatalogProduct.title == "Cemento especial 25 kg").one()
        assert product.last_price == 4790
        observations = db.query(PriceObservation).filter(PriceObservation.product_id == product.id).all()
        assert len(observations) == 1
        assert observations[0].price == 4790 and observations[0].min_price == 4790
        assert db.query(IngestionRun).filter(IngestionRun.query_key == "cemento upsert").count() == 1


class TestSearchFromCatalog:
    def test_segunda_busqueda_sale_del_catalogo(self, db, monkeypatch):
        calls = []
        monkeypatch.setattr(buyer_service, "fetch_live_offers", fake_fetch(lambda: [
            offer("Cemento Zeta Melon 25 kg", 5090), offer("Cemento Zeta Polpaico 25 kg", 4990, store="Easy"),
            offer("Cemento Zeta Bio Bio 25 kg", 5190, store="Falabella"),
        ], calls))
        first = buyer_service.search_products(db, "cemento zeta 25 kg", use_cache=True)
        second = buyer_service.search_products(db, "cemento zeta 25 kg", use_cache=True)
        assert first.data_source == "live" and second.data_source == "catalog"
        assert calls == ["cemento zeta 25 kg"]  # las tiendas se consultaron una sola vez
        assert {o.title for o in second.offers} == {o.title for o in first.offers}
        assert second.best_price == first.best_price == 4990
        assert all(o.offer_log_id for o in second.offers)  # feedback sigue funcionando

    def test_catalogo_vencido_consulta_en_vivo(self, db, monkeypatch):
        from app.models import WatchQuery

        calls = []
        monkeypatch.setattr(buyer_service, "fetch_live_offers",
                            fake_fetch(lambda: [offer("Fierro 12 mm", 8990)], calls))
        buyer_service.search_products(db, "fierro vencido 12 mm")
        watch = db.query(WatchQuery).filter(WatchQuery.query_key == "fierro vencido 12 mm").one()
        watch.last_ingested_at = catalog.utcnow() - timedelta(hours=48)
        db.commit()
        assert buyer_service.search_products(db, "fierro vencido 12 mm").data_source == "live"
        assert len(calls) == 2

    def test_sin_cache_siempre_en_vivo(self, db, monkeypatch):
        calls = []
        monkeypatch.setattr(buyer_service, "fetch_live_offers",
                            fake_fetch(lambda: [offer("Malla acma", 25990)], calls))
        buyer_service.search_products(db, "malla nocache")
        assert buyer_service.search_products(db, "malla nocache", use_cache=False).data_source == "live"
        assert len(calls) == 2

    def test_busquedas_registran_demanda(self, db, monkeypatch):
        from app.models import WatchQuery

        monkeypatch.setattr(buyer_service, "fetch_live_offers", fake_fetch(lambda: [offer("Carretilla", 39990)], []))
        for _ in range(3):
            buyer_service.search_products(db, "carretilla demanda")
        assert db.query(WatchQuery).filter(WatchQuery.query_key == "carretilla demanda").one().requests == 3


class TestPriceIndex:
    def test_serie_diaria_por_unidad(self, db):
        from app.models import PriceObservation

        items = [offer("Cemento Indice A 25 kg", 5000), offer("Cemento Indice B 25 kg", 5500, store="Easy"),
                 offer("Arena 25 kg", 900, store="Paris")]
        catalog.record_offers(db, "cemento indice 25 kg", items, [], trigger="scheduled")
        # Simula el dia anterior para tener dos puntos en la serie.
        for row in db.query(PriceObservation).all():
            db.add(PriceObservation(product_id=row.product_id, observed_on=row.observed_on - timedelta(days=1),
                                    price=row.price * 1.1, min_price=row.min_price * 1.1))
        db.commit()
        result = catalog.price_index(db, "cemento indice 25 kg", days=7)
        assert result["unit"] == "kg"
        assert [point["offers"] for point in result["series"]] == [2, 2]  # la arena no es comparable
        today = result["series"][-1]
        assert today["min_price"] == 5000 and today["min_unit_price"] == 200


class TestIngestion:
    def test_ingesta_de_lista_vigilada(self, db, monkeypatch, request):
        from pathlib import Path

        from app.models import WatchQuery

        seed = Path(__file__).parent / "_watchlist_test.tmp"
        request.addfinalizer(lambda: seed.unlink(missing_ok=True))
        seed.write_text("# comentario\ncemento seed 25 kg\nosb seed 9 mm\n", encoding="utf-8")
        monkeypatch.setattr(catalog, "WATCHLIST_SEED", seed)
        monkeypatch.setattr(catalog.settings, "catalog_ingest_batch", 1000)
        calls = []
        monkeypatch.setattr(sources, "fetch_live_offers", fake_fetch(lambda: [offer("Producto seed", 1000)], calls))
        added = catalog.seed_watchlist(db)
        assert added == 2
        result = catalog.ingest_watchlist(db, pause_range=(0, 0))
        assert "cemento seed 25 kg" in calls and "osb seed 9 mm" in calls
        assert result["ok"] == result["queries"] and not result["failed"]
        watch = db.query(WatchQuery).filter(WatchQuery.query_key == "osb seed 9 mm").one()
        assert watch.origin == "seed" and watch.last_ingested_at is not None

    def test_estado_por_fuente(self, db):
        catalog.record_offers(db, "estado fuentes", [], [SourceRun("easy", 0, 50, "timeout"),
                                                         SourceRun("sodimac", 30, 900)], trigger="scheduled")
        status = catalog.catalog_status(db, hours=1)
        assert status["sources"]["sodimac"]["success_rate"] > 0
        assert status["sources"]["easy"]["last_error"] == "timeout"


class TestCatalogApi:
    @pytest.fixture(scope="class")
    def client(self):
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client

    def test_indice_publico(self, client):
        response = client.get("/catalog/price-index", params={"q": "cemento indice 25 kg"})
        assert response.status_code == 200 and "series" in response.json()

    def test_estado_requiere_admin(self, client):
        assert client.get("/catalog/status").status_code == 401
        assert client.get("/catalog/status", headers={"X-Admin-Key": "test-admin-key"}).status_code == 200

    def test_administrar_lista_vigilada(self, client):
        headers = {"X-Admin-Key": "test-admin-key"}
        created = client.post("/catalog/watch", json={"query": "zinc acanalado admin"}, headers=headers)
        assert created.status_code == 200
        assert client.delete(f"/catalog/watch/{created.json()['id']}", headers=headers).status_code == 200


class TestTextSearch:
    def _ingest(self, db):
        items = [offer("Cemento Kappa Melón 25 kg", 5090), offer("Cemento Kappa Melón 25 kg", 5190, store="Easy"),
                 offer("Cemento Kappa Melón especial 25 kg", 4990, store="Falabella"),
                 offer("Cemento Kappa Polpaico 25 kg", 4890, store="Paris")]
        catalog.record_offers(db, "cemento kappa 25 kg", items, [], trigger="scheduled")

    def test_consulta_no_vigilada_sale_del_catalogo(self, db, monkeypatch):
        self._ingest(db)
        calls = []
        monkeypatch.setattr(buyer_service, "fetch_live_offers", fake_fetch(lambda: [], calls))
        result = buyer_service.search_products(db, "cemento kappa melon 25 kg")  # sin tilde en la consulta
        assert result.data_source == "catalog" and calls == []
        assert {o.store for o in result.offers} == {"Sodimac", "Easy", "Falabella"}  # Polpaico no calza

    def test_cobertura_insuficiente_va_en_vivo(self, db, monkeypatch):
        self._ingest(db)
        calls = []
        monkeypatch.setattr(buyer_service, "fetch_live_offers", fake_fetch(lambda: [], calls))
        buyer_service.search_products(db, "cemento kappa polpaico 25 kg")  # 1 tienda: no alcanza
        assert calls == ["cemento kappa polpaico 25 kg"]

    def test_productos_viejos_no_se_usan(self, db):
        from app.models import CatalogProduct

        self._ingest(db)
        for product in db.query(CatalogProduct).filter(CatalogProduct.search_text.like("%kappa%")):
            product.last_seen_at = catalog.utcnow() - timedelta(days=3)
        db.commit()
        assert catalog.text_search_offers(db, "cemento kappa melon 25 kg", 12) is None


class TestOpportunities:
    def _product_with_history(self, db, title: str, history: list[float], today_price: float):
        from app.models import CatalogProduct, PriceObservation

        catalog.record_offers(db, "oportunidad " + title, [offer(title, today_price)], [], trigger="scheduled")
        product = db.query(CatalogProduct).filter(CatalogProduct.title == title).one()
        today = catalog.utcnow().date()
        for days_ago, price in enumerate(history, start=1):
            db.add(PriceObservation(product_id=product.id, observed_on=today - timedelta(days=days_ago),
                                    price=price, min_price=price))
        db.commit()

    def test_detecta_caida_bajo_mediana(self, db):
        self._product_with_history(db, "Taladro Sigma 750W", [50_000, 49_000, 51_000, 50_000, 50_500], 42_000)
        self._product_with_history(db, "Taladro Sigma estable", [50_000] * 5, 49_500)        # -1%: no
        self._product_with_history(db, "Taladro Sigma error", [50_000] * 5, 4_000)            # -92%: inverosimil
        self._product_with_history(db, "Taladro Sigma nuevo", [50_000], 30_000)               # poca historia
        result = catalog.price_opportunities(db, min_drop_pct=10)
        titles = [item["title"] for item in result["opportunities"]]
        assert "Taladro Sigma 750W" in titles
        assert not {"Taladro Sigma estable", "Taladro Sigma error", "Taladro Sigma nuevo"} & set(titles)
        item = next(i for i in result["opportunities"] if i["title"] == "Taladro Sigma 750W")
        assert item["median_price"] == 50_000 and item["drop_pct"] == 16.0 and item["is_window_low"] is True

    def test_filtra_por_consulta_y_api(self, db):
        from fastapi.testclient import TestClient
        from app.main import app

        self._product_with_history(db, "Esmeril Omega 4", [30_000] * 6, 24_000)
        filtered = catalog.price_opportunities(db, query="oportunidad Esmeril Omega 4")
        assert [item["title"] for item in filtered["opportunities"]] == ["Esmeril Omega 4"]
        with TestClient(app) as client:
            response = client.get("/catalog/opportunities", params={"min_drop": 15})
        assert response.status_code == 200
        assert any(item["title"] == "Esmeril Omega 4" for item in response.json()["opportunities"])
