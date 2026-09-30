"""SSE: avance por tienda, escritura en el catalogo y respuesta desde el catalogo."""
import json

import pytest

from app.schemas import ProductOffer
from app.services import streaming


class FakeAdapter:
    def __init__(self, store: str, offers: list[ProductOffer], fail: bool = False):
        self.store, self.offers, self.fail, self.calls = store, offers, fail, 0

    def search(self, query, country="cl", max_results=20):
        self.calls += 1
        if self.fail:
            raise RuntimeError("tienda caida")
        return [offer.model_copy() for offer in self.offers]


def adapter_class(name: str):
    # source_name() usa el nombre de la clase: SodimacAdapter -> "sodimac".
    return type(f"{name}Adapter", (FakeAdapter,), {})


def offer(title, price, store):
    return ProductOffer(title=title, store=store, source=store.lower(), extracted_price=price,
                        link=f"https://tienda.cl/{store.lower()}/{title.lower().replace(' ', '-')}")


def events(generator) -> list[dict]:
    return [json.loads(chunk.removeprefix("data: ").strip()) for chunk in generator]


@pytest.fixture
def session_factory():
    from app.database import SessionLocal

    return SessionLocal


def test_stream_en_vivo_escribe_catalogo_y_luego_sirve_desde_el(monkeypatch, session_factory):
    from app.models import IngestionRun, WatchQuery

    sodimac = adapter_class("Sodimac")("Sodimac", [offer("Cemento Omega 25 kg", 5090, "Sodimac")])
    easy = adapter_class("Easy")("Easy", [offer("Cemento Omega Especial 25 kg", 4790, "Easy")])
    caida = adapter_class("Paris")("Paris", [], fail=True)
    monkeypatch.setattr(streaming, "get_adapters", lambda: [sodimac, easy, caida])

    first = events(streaming.search_stream("cemento omega 25 kg", session_factory=session_factory))
    assert first[0]["type"] == "start" and first[0]["data_source"] == "live"
    assert {e["store"] for e in first if e["type"] == "store_result"} == {"Sodimac", "Easy", "Paris"}
    done = first[-1]
    assert done["type"] == "done" and done["data_source"] == "live" and done["best_price"] == 4790

    db = session_factory()
    try:
        watch = db.query(WatchQuery).filter(WatchQuery.query_key == "cemento omega 25 kg").one()
        assert watch.last_ingested_at is not None and watch.requests == 1
        runs = {run.source: run for run in db.query(IngestionRun).filter(IngestionRun.query_key == watch.query_key)}
        assert runs["sodimac"].offers == 1 and runs["paris"].error == "tienda caida"
    finally:
        db.close()

    second = events(streaming.search_stream("cemento omega 25 kg", session_factory=session_factory))
    assert [e["type"] for e in second] == ["start", "done"]
    assert second[-1]["data_source"] == "catalog" and second[-1]["best_price"] == 4790
    assert sodimac.calls == 1 and easy.calls == 1  # no se volvio a consultar a las tiendas


def test_stream_sin_fuentes(monkeypatch, session_factory):
    monkeypatch.setattr(streaming, "get_adapters", lambda: [])
    result = events(streaming.search_stream("consulta sin fuentes", session_factory=session_factory))
    assert result[-1] == {"type": "done", "total": 0, "best_price": None, "avg_price": None, "offers": []}
