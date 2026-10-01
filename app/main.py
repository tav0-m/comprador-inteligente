"""Comprador Inteligente API v5 - nucleo de abastecimiento para construccion."""
from __future__ import annotations

import html
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.client_ip import client_fingerprint
from app.core.rate_limit import RateLimitMiddleware, default_rules
from app.core.security import require_admin
from app.database import SessionLocal, init_db
from app.models import OfferLog, UserFeedback
from app.schemas import (
    AlertCreateRequest,
    BasketOptimizationRequest,
    BasketOptimizationResponse,
    BomImportResponse,
    FeedbackRequest,
    SearchResponse,
)
from app.services.buyer_service import get_price_history, get_stats, search_products
from app.services.cache import cache_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env in {"local", "test"}:
        init_db()
    try:
        from app.services.ml_ranker import get_ranker

        logger.info("Ranking iniciado en modo %s.", get_ranker().mode)
    except Exception as exc:
        logger.warning("Ranking no disponible: %s", exc)
    yield


app = FastAPI(
    title="Comprador Inteligente API",
    version="5.0.0",
    description="Compara y optimiza compras de materiales de construccion en Chile.",
    lifespan=lifespan,
    # En produccion no se publica el esquema completo de la API.
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(RateLimitMiddleware, rules=default_rules(settings))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
    if settings.app_env == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", tags=["Salud"])
@app.get("/health", tags=["Salud"])
def healthcheck(db: Session = Depends(get_db)):
    from app.adapters.playwright_scraper import playwright_available
    from app.services.ml_ranker import get_ranker

    database_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_ok = False
    cache = cache_stats()
    return {
        "status": "ok" if database_ok else "degraded",
        "version": "5.0.0",
        "database": database_ok,
        "redis": cache["available"],
        "cache_keys": cache["keys"],
        "playwright": playwright_available(),
        "ranking_mode": get_ranker().mode,
    }


@app.get("/search", response_model=SearchResponse, tags=["Busqueda"])
def search(
    q: str = Query(..., min_length=2, max_length=120),
    country: str = Query("cl", min_length=2, max_length=2),
    city: str | None = Query(None, max_length=100),
    max_results: int = Query(20, ge=1, le=50),
    cache: bool = Query(True),
    db: Session = Depends(get_db),
):
    try:
        return search_products(db, q, country, city, max_results, cache)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error en /search")
        raise HTTPException(status_code=500, detail="No fue posible completar la busqueda.") from exc


@app.get("/search/stream", tags=["Busqueda"])
def search_stream(
    q: str = Query(..., min_length=2, max_length=120),
    country: str = Query("cl", min_length=2, max_length=2),
    max_results: int = Query(20, ge=1, le=50),
):
    from app.services.product_guardrails import validate_country, validate_query
    from app.services.streaming import search_stream as stream

    try:
        query = validate_query(q)
        market = validate_country(country)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        stream(query=query, country=market, max_results=max_results),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _isolated_search(**kwargs):
    """search_products con sesion propia: permite buscar lineas de la canasta en paralelo."""
    db = SessionLocal()
    try:
        return search_products(db=db, **kwargs)
    finally:
        db.close()


@app.post("/basket/optimize", response_model=BasketOptimizationResponse, tags=["Abastecimiento"])
def optimize_basket(request: BasketOptimizationRequest):
    from app.services.basket_optimizer import search_and_optimize

    try:
        return search_and_optimize(request, _isolated_search, max_workers=settings.basket_search_workers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error optimizando canasta")
        raise HTTPException(status_code=500, detail="No fue posible optimizar la canasta.") from exc


@app.post("/basket/import", response_model=BomImportResponse, tags=["Abastecimiento"])
async def import_basket(request: Request, filename: str = Query("", max_length=200)):
    """Lee una lista de materiales (.xlsx o .csv) enviada como cuerpo binario.

    Devuelve las lineas detectadas y advertencias para revisarlas antes de optimizar.
    """
    from app.services.bom_import import MAX_FILE_BYTES, BomImportError, parse_bom

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera 2 MB.")
    content = await request.body()
    try:
        return parse_bom(filename, content)
    except BomImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Importacion de lista fallida: %s", exc)
        raise HTTPException(status_code=400, detail="No fue posible leer el archivo.") from exc


@app.post("/basket/export", tags=["Abastecimiento"])
def export_basket(request: BasketOptimizationRequest):
    """Optimiza la canasta y devuelve la orden de compra por proveedor en CSV (Excel)."""
    from app.services.basket_optimizer import purchase_order_csv, search_and_optimize

    try:
        result = search_and_optimize(request, _isolated_search, max_workers=settings.basket_search_workers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=purchase_order_csv(result).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="orden_de_compra.csv"'},
    )


@app.get("/price-history", tags=["Analisis"])
def price_history(
    q: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    try:
        rows = get_price_history(db, q, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "query": q,
        "count": len(rows),
        "history": [
            {"date": row.recorded_at, "store": row.store, "price": row.price, "source": row.source, "link": row.link}
            for row in rows
        ],
    }


@app.get("/stats", tags=["Analisis"])
def stats(db: Session = Depends(get_db)):
    result = get_stats(db)
    result["cache"] = cache_stats()
    return result


@app.get("/history", tags=["Analisis"])
def history(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.query(OfferLog).order_by(OfferLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "title": row.title,
            "store": row.store,
            "price": row.extracted_price,
            "ml_score": row.ml_score,
            "anomaly_flag": row.anomaly_flag,
            "source": row.source,
            "recommendation": row.recommendation,
            "link": row.link,
        }
        for row in rows
    ]


@app.post("/alerts", tags=["Alertas"])
def create_alert(request: AlertCreateRequest, db: Session = Depends(get_db)):
    from app.services.alerts import AlertLimitExceeded, create_alert as create
    from app.services.product_guardrails import validate_query

    try:
        query = validate_query(request.query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        alert, sent = create(
            db,
            query=query,
            target_price=request.target_price,
            email=str(request.email),
            store_filter=request.store_filter,
            note=request.note,
        )
    except AlertLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if sent:
        message = "Te enviamos un email para confirmar la alerta; no se activara sin confirmacion."
    else:
        message = "Alerta registrada, pero no fue posible enviar el email de confirmacion. Intenta mas tarde."
    return {"status": "pending_confirmation", "alert_id": alert.id, "message": message}


def _alert_page(title: str, message: str, status_code: int = 200) -> HTMLResponse:
    body = (
        "<!doctype html><html lang='es'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        "<body style='font-family:Arial,sans-serif;max-width:560px;margin:48px auto;padding:0 16px'>"
        f"<h2>{html.escape(title)}</h2><p>{html.escape(message)}</p></body></html>"
    )
    return HTMLResponse(body, status_code=status_code)


@app.get("/alerts/confirm", tags=["Alertas"], response_class=HTMLResponse)
def confirm_alert(
    id: int = Query(..., gt=0),
    token: str = Query(..., max_length=200),
    db: Session = Depends(get_db),
):
    from app.services.alerts import confirm_alert as confirm

    alert = confirm(db, id, token)
    if not alert:
        return _alert_page("Enlace no valido", "El enlace es invalido, vencio o la alerta fue cancelada.", 400)
    return _alert_page(
        "Alerta confirmada",
        f"Te avisaremos cuando '{alert.query}' baje de CLP {alert.target_price:,.0f}.",
    )


@app.get("/alerts/unsubscribe", tags=["Alertas"], response_class=HTMLResponse)
def unsubscribe_alert(
    id: int = Query(..., gt=0),
    token: str = Query(..., max_length=200),
    db: Session = Depends(get_db),
):
    from app.services.alerts import unsubscribe_alert as unsubscribe

    if not unsubscribe(db, id, token):
        return _alert_page("Enlace no valido", "No fue posible cancelar la alerta con este enlace.", 400)
    return _alert_page("Alerta cancelada", "No recibiras mas notificaciones de esta alerta.")


@app.get("/alerts", tags=["Administracion"], dependencies=[Depends(require_admin)])
def list_alerts(email: str | None = Query(None), db: Session = Depends(get_db)):
    from app.services.alerts import list_alerts as list_all

    return [
        {
            "id": alert.id,
            "query": alert.query,
            "target_price": alert.target_price,
            "email": alert.email,
            "store_filter": alert.store_filter,
            "confirmed": alert.confirmed,
            "created_at": alert.created_at,
            "note": alert.note,
        }
        for alert in list_all(db, email=email)
    ]


@app.delete("/alerts/{alert_id}", tags=["Administracion"], dependencies=[Depends(require_admin)])
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    from app.services.alerts import delete_alert as deactivate

    if not deactivate(db, alert_id):
        raise HTTPException(status_code=404, detail="Alerta no encontrada.")
    return {"status": "ok"}


@app.post("/alerts/check", tags=["Administracion"], dependencies=[Depends(require_admin)])
def check_alerts(db: Session = Depends(get_db)):
    from app.services.alerts import check_alerts as check

    matches = check(db)
    return {"matched": len(matches), "notified": sum(bool(item["notified"]) for item in matches), "details": matches}


@app.post("/alerts/test-email", tags=["Administracion"], dependencies=[Depends(require_admin)])
def test_email(email: str = Body(..., embed=True)):
    from app.services.alerts import send_test_email

    success, message = send_test_email(email)
    if not success:
        raise HTTPException(status_code=503, detail=message)
    return {"status": "ok", "message": message}


@app.post("/feedback", tags=["Ranking"])
def feedback(request: FeedbackRequest, http_request: Request, db: Session = Depends(get_db)):
    """Un voto por cliente y oferta (el ultimo reemplaza al anterior), solo sobre ofertas recientes."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.feedback_max_offer_age_days)
    offer = (
        db.query(OfferLog)
        .filter(OfferLog.id == request.offer_log_id, OfferLog.created_at >= cutoff)
        .first()
    )
    if not offer:
        raise HTTPException(status_code=404, detail="Oferta no encontrada o demasiado antigua para evaluar.")
    client_hash = client_fingerprint(http_request)
    existing = (
        db.query(UserFeedback)
        .filter(UserFeedback.offer_log_id == offer.id, UserFeedback.client_hash == client_hash)
        .first()
    )
    if existing:
        existing.useful = request.useful
        existing.comment = request.comment
        existing.created_at = datetime.now(timezone.utc)
    else:
        db.add(UserFeedback(
            offer_log_id=offer.id, client_hash=client_hash, useful=request.useful, comment=request.comment,
        ))
    db.commit()
    return {"status": "ok", "message": "Feedback registrado."}


@app.post("/retrain", tags=["Administracion"], dependencies=[Depends(require_admin)])
def retrain(db: Session = Depends(get_db)):
    from app.services.model_training import train_from_database

    try:
        return {"status": "ok", "model": train_from_database(db)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/ranking/status", tags=["Ranking"])
def ranking_status():
    from app.services.ml_ranker import get_ranker

    ranker = get_ranker()
    return {"status": ranker.status(), "feature_importance": ranker.feature_importance()}


@app.get("/feature-importance", tags=["Ranking"])
def feature_importance():
    from app.services.ml_ranker import get_ranker

    return {"feature_importance": get_ranker().feature_importance()}


@app.post("/search/async", tags=["Busqueda Async"])
def search_async(
    q: str = Query(..., min_length=2, max_length=120),
    country: str = Query("cl", min_length=2, max_length=2),
    city: str | None = Query(None, max_length=100),
    max_results: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        from app.tasks import search_async_task

        task = search_async_task.apply_async(kwargs={
            "query": q,
            "country": country,
            "city": city,
            "max_results": max_results,
        })
        return {"task_id": task.id, "status": "PENDING"}
    except Exception as exc:
        logger.warning("Celery no disponible (%s); usando modo sincrono.", exc)
        result = search_products(db, q, country, city, max_results, True)
        return {"task_id": "sync", "status": "SUCCESS", "result": result.model_dump()}


@app.get("/search/result/{task_id}", tags=["Busqueda Async"])
def search_result(task_id: str):
    if task_id == "sync":
        return {"state": "SUCCESS", "meta": {"pct": 100}}
    try:
        from celery.result import AsyncResult
        from app.worker import celery_app

        result = AsyncResult(task_id, app=celery_app)
        if result.state == "SUCCESS":
            return {"state": "SUCCESS", "meta": {"pct": 100}, "result": result.result}
        if result.state == "FAILURE":
            logger.warning("Tarea %s fallo: %s", task_id, result.result)
            return {"state": "FAILURE", "meta": {"pct": 0}, "error": "La busqueda no pudo completarse."}
        return {"state": result.state, "meta": result.info if isinstance(result.info, dict) else {}}
    except Exception as exc:
        logger.warning("Worker no disponible: %s", exc)
        raise HTTPException(status_code=503, detail="Worker no disponible.") from exc


@app.get("/worker/status", tags=["Administracion"], dependencies=[Depends(require_admin)])
def worker_status():
    try:
        from app.worker import celery_app

        ping = celery_app.control.inspect(timeout=3).ping() or {}
        return {"workers_online": list(ping)}
    except Exception as exc:
        return {"workers_online": [], "error": str(exc)}


@app.post("/tasks/warmup", tags=["Administracion"], dependencies=[Depends(require_admin)])
def warmup_cache(top_n: int = Query(5, ge=1, le=20)):
    from app.tasks import warmup_cache_task

    task = warmup_cache_task.apply_async(kwargs={"top_n": top_n})
    return {"task_id": task.id, "status": "PENDING"}


@app.get("/catalog/price-index", tags=["Catalogo"])
def catalog_price_index(
    q: str = Query(..., min_length=2, max_length=120),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Serie diaria (min y mediana, por envase y por unidad) de las ofertas comparables."""
    from app.services.catalog import price_index
    from app.services.product_guardrails import validate_query

    try:
        query = validate_query(q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return price_index(db, query, days)


@app.get("/catalog/status", tags=["Administracion"], dependencies=[Depends(require_admin)])
def catalog_status_endpoint(hours: int = Query(24, ge=1, le=720), db: Session = Depends(get_db)):
    from app.services.catalog import catalog_status

    return catalog_status(db, hours)


@app.get("/catalog/watch", tags=["Administracion"], dependencies=[Depends(require_admin)])
def list_watch_queries(db: Session = Depends(get_db)):
    from app.models import WatchQuery

    rows = db.query(WatchQuery).order_by(WatchQuery.requests.desc(), WatchQuery.id.asc()).all()
    return [
        {
            "id": row.id, "query": row.query, "origin": row.origin, "active": row.active,
            "requests": row.requests, "last_requested_at": row.last_requested_at,
            "last_ingested_at": row.last_ingested_at,
        }
        for row in rows
    ]


@app.post("/catalog/watch", tags=["Administracion"], dependencies=[Depends(require_admin)])
def add_watch_query(query: str = Body(..., embed=True, min_length=2, max_length=120), db: Session = Depends(get_db)):
    from app.services.catalog import ensure_watch
    from app.services.product_guardrails import validate_query

    try:
        clean = validate_query(query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    watch = ensure_watch(db, clean, origin="admin")
    db.commit()
    return {"status": "ok", "id": watch.id, "query": watch.query}


@app.delete("/catalog/watch/{watch_id}", tags=["Administracion"], dependencies=[Depends(require_admin)])
def deactivate_watch_query(watch_id: int, db: Session = Depends(get_db)):
    from app.models import WatchQuery

    watch = db.get(WatchQuery, watch_id)
    if not watch:
        raise HTTPException(status_code=404, detail="Consulta vigilada no encontrada.")
    watch.active = False
    db.commit()
    return {"status": "ok"}


@app.post("/tasks/ingest", tags=["Administracion"], dependencies=[Depends(require_admin)])
def ingest_catalog(
    query: str | None = Query(None, min_length=2, max_length=120),
    limit: int | None = Query(None, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Con `query`: ingesta inmediata de una consulta. Sin ella: encola la lista vigilada."""
    if query:
        from app.services.catalog import ingest_query
        from app.services.product_guardrails import validate_query

        try:
            clean = validate_query(query)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "result": ingest_query(db, clean, trigger="admin")}
    try:
        from app.tasks import ingest_catalog_task

        task = ingest_catalog_task.apply_async(kwargs={"limit": limit})
    except Exception as exc:
        logger.warning("No se pudo encolar la ingesta: %s", exc)
        raise HTTPException(status_code=503, detail="Worker no disponible para la ingesta.") from exc
    return {"task_id": task.id, "status": "PENDING"}


@app.post("/tasks/retrain-async", tags=["Administracion"], dependencies=[Depends(require_admin)])
def retrain_async():
    from app.tasks import retrain_model_task

    task = retrain_model_task.apply_async()
    return {"task_id": task.id, "status": "PENDING"}
