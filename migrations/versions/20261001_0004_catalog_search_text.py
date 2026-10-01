"""Texto normalizado del titulo para busqueda en el catalogo (con indice trigram en Postgres)."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261001_0004"
down_revision = "20260929_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_products") as batch:
        batch.add_column(sa.Column("search_text", sa.String(length=500), nullable=True))

    from app.services.specs import canonical

    bind = op.get_bind()
    products = sa.table(
        "catalog_products",
        sa.column("id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("search_text", sa.String),
    )
    rows = bind.execute(sa.select(products.c.id, products.c.title)).fetchall()
    for product_id, title in rows:
        bind.execute(
            products.update().where(products.c.id == product_id).values(search_text=canonical(title or "")[:500])
        )

    if bind.dialect.name == "postgresql":
        # pg_trgm es una extension "trusted" desde PG13: la puede crear el dueno de la base.
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_catalog_products_search_text_trgm "
            "ON catalog_products USING gin (search_text gin_trgm_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_catalog_products_search_text_trgm")
    with op.batch_alter_table("catalog_products") as batch:
        batch.drop_column("search_text")
