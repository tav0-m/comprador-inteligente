from __future__ import annotations

import logging

from sqlalchemy import func

from app.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.search_async_task", bind=True, max_retries=2, soft_time_limit=90)
def search_async_task(self, query: str, country: str = "cl", city: str | None = None, max_results: int = 20):
    from app.database import SessionLocal
    from app.services.buyer_service import search_products

    db = SessionLocal()
    try:
        self.update_state(state="PROGRESS", meta={"step": "buscando en tiendas", "pct": 20})
        response = search_products(db, query, country, city, max_results, use_cache=True)
        return response.model_dump()
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()


@celery_app.task(name="app.tasks.check_alerts_task", bind=True, max_retries=1, soft_time_limit=60)
def check_alerts_task(self):
    from app.database import SessionLocal
    from app.services.alerts import check_alerts

    db = SessionLocal()
    try:
        results = check_alerts(db)
        return {"matched": len(results), "notified": sum(bool(item["notified"]) for item in results)}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
    finally:
        db.close()


@celery_app.task(name="app.tasks.retrain_model_task", soft_time_limit=300)
def retrain_model_task():
    from app.database import SessionLocal
    from app.services.model_training import train_from_database

    db = SessionLocal()
    try:
        return train_from_database(db)
    finally:
        db.close()


@celery_app.task(name="app.tasks.warmup_cache_task", soft_time_limit=180)
def warmup_cache_task(top_n: int = 5):
    from app.database import SessionLocal
    from app.models import SearchLog
    from app.services.buyer_service import search_products

    db = SessionLocal()
    try:
        queries = (
            db.query(SearchLog.query, func.count(SearchLog.id).label("count"))
            .group_by(SearchLog.query)
            .order_by(func.count(SearchLog.id).desc())
            .limit(top_n)
            .all()
        )
        warmed = []
        for query, _ in queries:
            try:
                search_products(db, query, use_cache=False)
                warmed.append(query)
            except Exception as exc:
                logger.warning("[Warmup] %s: %s", query, exc)
        return {"warmed": warmed}
    finally:
        db.close()


@celery_app.task(name="app.tasks.monitor_prices_task", soft_time_limit=300)
def monitor_prices_task(top_n: int = 5):
    return warmup_cache_task.run(top_n=top_n)
