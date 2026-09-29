from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Boolean, Text, UniqueConstraint
from sqlalchemy.sql import false, func, true
from app.database import Base


class SearchLog(Base):
    __tablename__ = "search_logs"
    id = Column(Integer, primary_key=True, index=True)
    query = Column(String, index=True)
    country = Column(String, default="cl")
    city = Column(String, nullable=True)
    total_results = Column(Integer, default=0)
    best_price = Column(Float, nullable=True)
    avg_price = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OfferLog(Base):
    __tablename__ = "offer_logs"
    id = Column(Integer, primary_key=True, index=True)
    search_id = Column(Integer, ForeignKey("search_logs.id"), nullable=True)
    title = Column(String, index=True)
    store = Column(String, index=True, nullable=True)
    source = Column(String, index=True)
    price_text = Column(String, nullable=True)
    extracted_price = Column(Float, nullable=True, index=True)
    currency = Column(String, default="CLP")
    delivery = Column(String, nullable=True)
    availability = Column(String, nullable=True)
    rating = Column(Float, nullable=True)
    reviews = Column(Integer, nullable=True)
    link = Column(String, nullable=True)
    thumbnail = Column(String, nullable=True)
    score = Column(Float, nullable=True)
    ml_score = Column(Float, nullable=True)
    recommendation = Column(String, nullable=True)
    price_percentile = Column(Float, nullable=True)
    anomaly_flag = Column(String, nullable=True)
    price_vs_avg_pct = Column(Float, nullable=True)
    free_shipping = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PriceHistory(Base):
    __tablename__ = "price_history"
    id = Column(Integer, primary_key=True, index=True)
    query = Column(String, index=True)
    title = Column(String, index=True)
    store = Column(String, index=True)
    source = Column(String)
    price = Column(Float)
    currency = Column(String, default="CLP")
    link = Column(String, nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class UserFeedback(Base):
    __tablename__ = "user_feedback"
    __table_args__ = (UniqueConstraint("offer_log_id", "client_hash", name="uq_feedback_offer_client"),)
    id = Column(Integer, primary_key=True, index=True)
    offer_log_id = Column(Integer, ForeignKey("offer_logs.id"), nullable=True)
    # HMAC de la IP: un voto por cliente y oferta, sin almacenar la IP.
    client_hash = Column(String(64), nullable=True)
    useful = Column(Boolean)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(String(200), nullable=False, index=True)
    target_price = Column(Float, nullable=False)
    email = Column(String(200), nullable=False, index=True)
    store_filter = Column(String(100), nullable=True)
    active = Column(Boolean, default=True, index=True)
    triggered = Column(Boolean, default=False)
    triggered_at = Column(DateTime(timezone=True), nullable=True)
    # Doble opt-in: solo se notifican alertas cuyo email confirmo el dueno.
    confirmed = Column(Boolean, default=False, server_default=false(), nullable=False, index=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    note = Column(Text, nullable=True)


# ── Catalogo propio (Fase 4) ──────────────────────────────────────────────────
class CatalogProduct(Base):
    """Una publicacion de una tienda (URL canonica), con su ultimo estado conocido."""
    __tablename__ = "catalog_products"
    __table_args__ = (UniqueConstraint("source", "url_key", name="uq_catalog_source_url"),)
    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False, index=True)
    url_key = Column(String(64), nullable=False)  # sha256 de la URL normalizada
    store = Column(String(150), nullable=True, index=True)
    seller = Column(String(150), nullable=True)
    title = Column(String(500), nullable=False)
    link = Column(String, nullable=True)
    thumbnail = Column(String, nullable=True)
    currency = Column(String(3), default="CLP")
    last_price = Column(Float, nullable=True)
    last_price_text = Column(String(100), nullable=True)
    delivery = Column(String(500), nullable=True)
    availability = Column(String(250), nullable=True)
    rating = Column(Float, nullable=True)
    reviews = Column(Integer, nullable=True)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class PriceObservation(Base):
    """Serie de tiempo: un precio por producto y dia (el ultimo observado ese dia)."""
    __tablename__ = "price_observations"
    __table_args__ = (UniqueConstraint("product_id", "observed_on", name="uq_observation_product_day"),)
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("catalog_products.id", ondelete="CASCADE"), nullable=False, index=True)
    observed_on = Column(Date, nullable=False, index=True)
    price = Column(Float, nullable=False)
    min_price = Column(Float, nullable=False)  # minimo visto durante el dia
    price_text = Column(String(100), nullable=True)
    observed_at = Column(DateTime(timezone=True), server_default=func.now())


class CatalogQueryHit(Base):
    """Que productos devolvio cada consulta (y cuando fue la ultima vez)."""
    __tablename__ = "catalog_query_hits"
    __table_args__ = (UniqueConstraint("query_key", "product_id", name="uq_hit_query_product"),)
    id = Column(Integer, primary_key=True)
    query_key = Column(String(200), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("catalog_products.id", ondelete="CASCADE"), nullable=False, index=True)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class WatchQuery(Base):
    """Consulta que la ingesta programada refresca (semilla, usuarios o admin)."""
    __tablename__ = "watch_queries"
    id = Column(Integer, primary_key=True)
    query_key = Column(String(200), nullable=False, unique=True)
    query = Column(String(200), nullable=False)
    origin = Column(String(20), nullable=False, default="user")  # seed | user | admin
    active = Column(Boolean, nullable=False, default=True, server_default=true(), index=True)
    requests = Column(Integer, nullable=False, default=0, server_default="0")
    last_requested_at = Column(DateTime(timezone=True), nullable=True)
    last_ingested_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class IngestionRun(Base):
    """Resultado de una fuente para una consulta: base para monitorear adaptadores."""
    __tablename__ = "ingestion_runs"
    id = Column(Integer, primary_key=True)
    query_key = Column(String(200), nullable=False, index=True)
    source = Column(String(50), nullable=False, index=True)
    trigger = Column(String(20), nullable=False, default="live")  # live | scheduled
    offers = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=True)
    error = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
