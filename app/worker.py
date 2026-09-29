from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "comprador_inteligente",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_soft_time_limit=90,
    task_time_limit=120,
    result_expires=3600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="America/Santiago",
    enable_utc=True,
    task_default_queue="searches",
    task_routes={
        "app.tasks.search_async_task": {"queue": "searches"},
        "app.tasks.check_alerts_task": {"queue": "maintenance"},
        "app.tasks.monitor_prices_task": {"queue": "maintenance"},
        "app.tasks.retrain_model_task": {"queue": "ml"},
        "app.tasks.warmup_cache_task": {"queue": "maintenance"},
    },
    beat_schedule={
        "check-price-alerts": {
            "task": "app.tasks.check_alerts_task",
            "schedule": 30 * 60,
        },
        "refresh-popular-prices": {
            "task": "app.tasks.monitor_prices_task",
            "schedule": 2 * 60 * 60,
        },
    },
)

celery_app.autodiscover_tasks(["app"])
