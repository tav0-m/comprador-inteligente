from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.sql import func
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
    id = Column(Integer, primary_key=True, index=True)
    offer_log_id = Column(Integer, ForeignKey("offer_logs.id"), nullable=True)
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    note = Column(Text, nullable=True)
