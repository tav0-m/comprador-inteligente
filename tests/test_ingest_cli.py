"""Ingesta por linea de comandos (sin Celery): argumentos, candado y codigos de salida."""
import os
import time

import pytest

from app import ingest
from app.services import catalog


@pytest.fixture(autouse=True)
def isolated_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "LOCK_PATH", tmp_path / "ingest.lock")
    cwd = os.getcwd()
    yield tmp_path / "ingest.lock"
    os.chdir(cwd)


def fake_watchlist(calls: list, result: dict):
    def ingest_watchlist(db, limit=None, **_):
        calls.append(limit)
        return result
    return ingest_watchlist


class TestMain:
    def test_refresca_todas_las_activas_por_defecto(self, monkeypatch):
        from app.database import SessionLocal
        from app.models import WatchQuery

        db = SessionLocal()
        catalog.ensure_watch(db, "cli ingesta uno", origin="admin")
        catalog.ensure_watch(db, "cli ingesta dos", origin="admin")
        db.commit()
        active = db.query(WatchQuery).filter(WatchQuery.active.is_(True)).count()
        db.close()

        calls: list = []
        monkeypatch.setattr(catalog, "ingest_watchlist", fake_watchlist(
            calls, {"queries": active, "ok": active, "failed": [], "products": 12}))
        assert ingest.main([]) == 0
        assert calls == [active]

    def test_limit_acota_el_lote(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(catalog, "ingest_watchlist", fake_watchlist(
            calls, {"queries": 1, "ok": 1, "failed": [], "products": 3}))
        assert ingest.main(["--limit", "1"]) == 0
        assert calls == [1]

    def test_query_ingiere_una_sola_consulta(self, monkeypatch):
        seen: list = []

        def ingest_query(db, query, trigger="scheduled"):
            seen.append((query, trigger))
            return {"query": query, "products": 4, "sources": {}, "elapsed_ms": 1}

        monkeypatch.setattr(catalog, "ingest_query", ingest_query)
        assert ingest.main(["--query", "cemento 25 kg"]) == 0
        assert seen == [("cemento 25 kg", "scheduled")]

    def test_sale_con_error_si_todo_falla(self, monkeypatch):
        monkeypatch.setattr(catalog, "ingest_watchlist", fake_watchlist(
            [], {"queries": 2, "ok": 0, "failed": ["a", "b"], "products": 0}))
        assert ingest.main([]) == 1

    def test_sale_con_error_si_ninguna_fuente_trae_productos(self, monkeypatch):
        monkeypatch.setattr(catalog, "ingest_watchlist", fake_watchlist(
            [], {"queries": 2, "ok": 2, "failed": [], "products": 0}))
        assert ingest.main([]) == 1

    def test_excepcion_no_se_propaga(self, monkeypatch):
        def boom(db, limit=None, **_):
            raise RuntimeError("sin red")

        monkeypatch.setattr(catalog, "ingest_watchlist", boom)
        assert ingest.main([]) == 1

    def test_limit_invalido(self):
        with pytest.raises(SystemExit):
            ingest.main(["--limit", "0"])


class TestLock:
    def test_segunda_corrida_se_omite(self, isolated_lock, monkeypatch):
        monkeypatch.setattr(catalog, "ingest_watchlist", fake_watchlist(
            [], {"queries": 1, "ok": 1, "failed": [], "products": 1}))
        with ingest.IngestLock(isolated_lock):
            assert ingest.main([]) == 2
        assert not isolated_lock.exists()

    def test_candado_antiguo_se_descarta(self, isolated_lock):
        isolated_lock.write_text("999999")
        old = time.time() - ingest.LOCK_STALE_SECONDS - 60
        os.utime(isolated_lock, (old, old))
        with ingest.IngestLock(isolated_lock):
            assert isolated_lock.exists()
        assert not isolated_lock.exists()

    def test_se_libera_aunque_falle(self, isolated_lock):
        with pytest.raises(ValueError):
            with ingest.IngestLock(isolated_lock):
                raise ValueError("x")
        assert not isolated_lock.exists()
