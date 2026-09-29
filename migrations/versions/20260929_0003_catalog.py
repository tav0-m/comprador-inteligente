"""Catalogo propio: productos, observaciones diarias, consultas vigiladas e ingesta."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260929_0003"
down_revision = "20260929_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("url_key", sa.String(length=64), nullable=False),
        sa.Column("store", sa.String(length=150), nullable=True),
        sa.Column("seller", sa.String(length=150), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("thumbnail", sa.String(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("last_price", sa.Float(), nullable=True),
        sa.Column("last_price_text", sa.String(length=100), nullable=True),
        sa.Column("delivery", sa.String(length=500), nullable=True),
        sa.Column("availability", sa.String(length=250), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("reviews", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source", "url_key", name="uq_catalog_source_url"),
    )
    op.create_index("ix_catalog_products_source", "catalog_products", ["source"])
    op.create_index("ix_catalog_products_store", "catalog_products", ["store"])
    op.create_index("ix_catalog_products_last_seen_at", "catalog_products", ["last_seen_at"])

    op.create_table(
        "price_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(),
                  sa.ForeignKey("catalog_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("min_price", sa.Float(), nullable=False),
        sa.Column("price_text", sa.String(length=100), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("product_id", "observed_on", name="uq_observation_product_day"),
    )
    op.create_index("ix_price_observations_product_id", "price_observations", ["product_id"])
    op.create_index("ix_price_observations_observed_on", "price_observations", ["observed_on"])

    op.create_table(
        "catalog_query_hits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query_key", sa.String(length=200), nullable=False),
        sa.Column("product_id", sa.Integer(),
                  sa.ForeignKey("catalog_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("query_key", "product_id", name="uq_hit_query_product"),
    )
    op.create_index("ix_catalog_query_hits_query_key", "catalog_query_hits", ["query_key"])
    op.create_index("ix_catalog_query_hits_product_id", "catalog_query_hits", ["product_id"])
    op.create_index("ix_catalog_query_hits_last_seen_at", "catalog_query_hits", ["last_seen_at"])

    op.create_table(
        "watch_queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("query", sa.String(length=200), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_watch_queries_active", "watch_queries", ["active"])
    op.create_index("ix_watch_queries_last_ingested_at", "watch_queries", ["last_ingested_at"])

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query_key", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("offers", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ingestion_runs_query_key", "ingestion_runs", ["query_key"])
    op.create_index("ix_ingestion_runs_source", "ingestion_runs", ["source"])
    op.create_index("ix_ingestion_runs_created_at", "ingestion_runs", ["created_at"])


def downgrade() -> None:
    for table in ("ingestion_runs", "watch_queries", "catalog_query_hits", "price_observations", "catalog_products"):
        op.drop_table(table)
