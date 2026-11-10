"""Ingesta del catalogo por linea de comandos, sin Redis ni Celery.

Pensado para un programador externo (Programador de tareas de Windows, cron):

    python -m app.ingest                  # refresca todas las consultas vigiladas activas
    python -m app.ingest --limit 10       # solo las 10 menos recientes
    python -m app.ingest --query "cemento 25 kg"

Codigo de salida: 0 si al menos una consulta se ingirio, 1 si todas fallaron
o ninguna fuente devolvio productos, 2 si ya hay otra ingesta en curso.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger("app.ingest")

ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = ROOT / "data" / "ingest.lock"
LOCK_STALE_SECONDS = 3 * 60 * 60  # un candado mas viejo es de una corrida que murio


class IngestAlreadyRunning(RuntimeError):
    pass


class IngestLock:
    """Candado por archivo: evita dos ingestas simultaneas sobre las mismas tiendas."""

    def __init__(self, path: Path | None = None, stale_seconds: int = LOCK_STALE_SECONDS):
        self.path = path or LOCK_PATH
        self.stale_seconds = stale_seconds

    def __enter__(self) -> "IngestLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if time.time() - self.path.stat().st_mtime > self.stale_seconds:
                logger.warning("Candado antiguo en %s; se descarta.", self.path)
                self.path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise IngestAlreadyRunning(str(self.path)) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return self

    def __exit__(self, *_: object) -> None:
        self.path.unlink(missing_ok=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.ingest", description=__doc__.splitlines()[0])
    parser.add_argument("--query", help="Ingiere solo esta consulta (y la agrega a las vigiladas).")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximo de consultas vigiladas a refrescar (por defecto, todas las activas).",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit debe ser mayor o igual a 1")
    return args


def run(query: str | None = None, limit: int | None = None) -> dict:
    """Ejecuta la ingesta y retorna el resumen ({queries, ok, failed, products})."""
    from sqlalchemy import func

    from app.core.config import settings
    from app.database import SessionLocal, init_db
    from app.models import WatchQuery
    from app.services import catalog
    from app.services.product_guardrails import validate_query

    if settings.app_env in {"local", "test"}:
        init_db()
    db = SessionLocal()
    try:
        if query:
            result = catalog.ingest_query(db, validate_query(query), trigger="scheduled")
            return {"queries": 1, "ok": 1, "failed": [], "products": result["products"]}
        if db.query(func.count(WatchQuery.id)).scalar() == 0:
            catalog.seed_watchlist(db)
        active = db.query(func.count(WatchQuery.id)).filter(WatchQuery.active.is_(True)).scalar() or 0
        if active == 0:
            return {"queries": 0, "ok": 0, "failed": [], "products": 0}
        return catalog.ingest_watchlist(db, limit=min(limit, active) if limit else active)
    finally:
        db.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    # Rutas relativas (.env, SQLite, data/) se resuelven desde la raiz del proyecto,
    # sin importar desde que carpeta lo lance el programador de tareas.
    os.chdir(ROOT)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    started = time.perf_counter()
    try:
        with IngestLock():
            summary = run(query=args.query, limit=args.limit)
    except IngestAlreadyRunning:
        logger.warning("Ya hay una ingesta en curso; esta corrida se omite.")
        return 2
    except Exception:
        logger.exception("La ingesta fallo.")
        return 1
    logger.info(
        "Ingesta terminada en %.0f s: %d/%d consultas, %d productos, %d fallidas%s",
        time.perf_counter() - started, summary["ok"], summary["queries"], summary["products"],
        len(summary["failed"]), f" ({', '.join(summary['failed'])})" if summary["failed"] else "",
    )
    return 0 if summary["ok"] > 0 and summary["products"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
