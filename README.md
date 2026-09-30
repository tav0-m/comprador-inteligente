# Comprador Inteligente — abastecimiento de obras en Chile

Compara precios de materiales de construcción entre **Sodimac, Easy, Falabella y Paris**
(Mercado Libre opcional), los normaliza por **especificación y precio por unidad**, y
optimiza la compra de una lista de materiales entre proveedores. Mantiene un **catálogo
propio con una serie diaria de precios** para medir tendencias y alertar oportunidades.

## Arquitectura

```
                ┌────────────── Celery beat (cada 6 h) ──────────────┐
                ▼                                                    │
  Tiendas ──► adaptadores ──► normalización ──► catálogo propio ◄────┘
  (__NEXT_DATA__ / JSON-LD)   (precio vigente,   (productos + 1 precio por día
                               tarjeta, vendedor) + salud por fuente)
                                                        │
  /search, /search/stream ──► ¿consulta fresca (<12 h)? ─┤ sí → responde desde la base (~50 ms)
                                                        └ no → tiendas en vivo y guarda en catálogo
                                   │
                                   ▼
        relevancia por especificación ─► anomalías (IQR + MAD) ─► ranking ─► KPIs comparables
        (producto, medida, precio/unidad)                          (heurístico → LightGBM
                                                                    con feedback real)
```

| Componente | Tecnología |
|---|---|
| API | FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 |
| Tareas | Celery + Redis (ingesta, alertas, reentrenamiento) |
| Base de datos | PostgreSQL (SQLite en desarrollo) |
| Frontend | Next.js 16, React 19, TanStack Query, Recharts |
| ML | scikit-learn, LightGBM (LambdaRank), rapidfuzz |

## Qué resuelve

- **Relevancia por especificación**: "cemento 25 kg" no devuelve arena de 25 kg ni cemento
  de 1 kg; los accesorios ("mandril *para* taladro") no compiten con el producto.
- **Precio por unidad**: CLP/kg, CLP/l, CLP/m², CLP/unidad para comparar formatos distintos.
- **Canasta optimizada de forma exacta** (programación entera mixta): importa el presupuesto
  de la obra, compra envases enteros (500 kg de cemento → 20 sacos de 25 kg), considera
  despacho, umbrales de despacho gratis y costo fijo por proveedor, y exporta la orden de compra.
- **Índice de precios**: mínimo y mediana diarios de las ofertas comparables.
- **Alertas de precio** con doble confirmación del email.

## Puesta en marcha (desarrollo)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Mac/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env            # completa ADMIN_API_KEY y APP_SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend (Node 20+):

```bash
cd frontend
corepack enable
pnpm install
pnpm dev                          # http://localhost:3000 (proxy /api → :8000)
```

Ingesta programada (requiere Redis):

```bash
celery -A app.worker worker --queues=searches,maintenance,ml
celery -A app.worker beat
```

Todo junto con Docker: `docker compose up --build` (define `POSTGRES_PASSWORD`,
`ADMIN_API_KEY` y `APP_SECRET_KEY` en `.env`).

Genera claves con `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## Endpoints principales

| Endpoint | Acceso | Descripción |
|---|---|---|
| `GET /search?q=` | público | Búsqueda rankeada con KPIs comparables, `data_source` y `data_as_of` |
| `GET /search/stream?q=` | público | Igual, con avance por tienda (SSE) |
| `POST /basket/optimize` | público | Canasta de hasta 30 materiales: MILP exacto con despacho, umbral de despacho gratis y costo fijo por proveedor |
| `POST /basket/import?filename=` | público | Lista de materiales `.xlsx`/`.csv` (cuerpo binario) → líneas + advertencias |
| `POST /basket/export` | público | Orden de compra por proveedor en CSV para Excel |
| `GET /catalog/price-index?q=&days=` | público | Serie diaria de precios comparables |
| `POST /alerts` | público | Alerta de precio (se activa al confirmar el email) |
| `POST /feedback` | público | Voto útil/no útil (uno por cliente y oferta) |
| `GET /catalog/status` | admin | Salud del catálogo y tasa de éxito por tienda |
| `GET/POST/DELETE /catalog/watch` | admin | Consultas vigiladas por la ingesta |
| `POST /tasks/ingest` | admin | Ingesta inmediata o encolada |
| `POST /retrain` | admin | Reentrena el ranker con feedback real |

Los endpoints admin requieren el encabezado `X-Admin-Key`. La documentación interactiva
está en `/docs` fuera de producción.

## Configuración relevante (`.env`)

| Variable | Uso |
|---|---|
| `ADMIN_API_KEY`, `APP_SECRET_KEY` | Endpoints admin; firma de enlaces y seudónimos de IP |
| `MERCADOLIBRE_CLIENT_ID/SECRET` | Activa Mercado Libre (OAuth `client_credentials`) |
| `CATALOG_FRESHNESS_HOURS` | Antigüedad máxima para responder desde el catálogo (12) |
| `CATALOG_INGEST_INTERVAL_HOURS` | Frecuencia de la ingesta programada (6) |
| `TRUSTED_PROXY_CIDRS` | Proxies cuyo `X-Forwarded-For` se acepta (rate limit por IP real) |
| `ALERT_EMAIL_*` | SMTP para confirmaciones y avisos |

La lista semilla de materiales vigilados está en `data/watchlist.txt`; las búsquedas de
los usuarios se agregan automáticamente.

## Calidad

```bash
pytest -q                          # sin red, Redis ni SMTP (los tests vacían las credenciales)
```

La CI (`.github/workflows/ci.yml`) corre pytest, las migraciones desde cero y el
typecheck/lint/build del frontend.

## Aviso

Los precios provienen de páginas públicas de las tiendas y pueden cambiar; confirma stock,
especificación, despacho y precio final antes de comprar. Revisa los términos de uso de
cada tienda antes de operar comercialmente; prioriza APIs oficiales o acuerdos con
proveedores cuando existan.
