"""Esquema inicial de Comprador Inteligente v5."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260720_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("total_results", sa.Integer(), nullable=True),
        sa.Column("best_price", sa.Float(), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_search_logs_query", "search_logs", ["query"])

    op.create_table(
        "offer_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_id", sa.Integer(), sa.ForeignKey("search_logs.id"), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("store", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("price_text", sa.String(), nullable=True),
        sa.Column("extracted_price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("delivery", sa.String(), nullable=True),
        sa.Column("availability", sa.String(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("reviews", sa.Integer(), nullable=True),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("thumbnail", sa.String(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("ml_score", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.String(), nullable=True),
        sa.Column("price_percentile", sa.Float(), nullable=True),
        sa.Column("anomaly_flag", sa.String(), nullable=True),
        sa.Column("price_vs_avg_pct", sa.Float(), nullable=True),
        sa.Column("free_shipping", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_offer_logs_search_id", "offer_logs", ["search_id"])
    op.create_index("ix_offer_logs_title", "offer_logs", ["title"])
    op.create_index("ix_offer_logs_store", "offer_logs", ["store"])
    op.create_index("ix_offer_logs_source", "offer_logs", ["source"])
    op.create_index("ix_offer_logs_extracted_price", "offer_logs", ["extracted_price"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("store", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_price_history_query", "price_history", ["query"])
    op.create_index("ix_price_history_title", "price_history", ["title"])
    op.create_index("ix_price_history_store", "price_history", ["store"])
    op.create_index("ix_price_history_recorded_at", "price_history", ["recorded_at"])

    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_log_id", sa.Integer(), sa.ForeignKey("offer_logs.id"), nullable=True),
        sa.Column("useful", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "price_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query", sa.String(200), nullable=False),
        sa.Column("target_price", sa.Float(), nullable=False),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("store_filter", sa.String(100), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("triggered", sa.Boolean(), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_price_alerts_query", "price_alerts", ["query"])
    op.create_index("ix_price_alerts_email", "price_alerts", ["email"])
    op.create_index("ix_price_alerts_active", "price_alerts", ["active"])


def downgrade() -> None:
    op.drop_table("price_alerts")
    op.drop_table("user_feedback")
    op.drop_table("price_history")
    op.drop_table("offer_logs")
    op.drop_table("search_logs")
