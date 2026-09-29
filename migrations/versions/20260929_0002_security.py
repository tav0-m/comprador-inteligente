"""Doble opt-in de alertas y feedback deduplicado por cliente."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260929_0002"
down_revision = "20260720_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("price_alerts") as batch:
        batch.add_column(sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_price_alerts_confirmed", ["confirmed"])

    with op.batch_alter_table("user_feedback") as batch:
        batch.add_column(sa.Column("client_hash", sa.String(length=64), nullable=True))
        batch.create_unique_constraint("uq_feedback_offer_client", ["offer_log_id", "client_hash"])


def downgrade() -> None:
    with op.batch_alter_table("user_feedback") as batch:
        batch.drop_constraint("uq_feedback_offer_client", type_="unique")
        batch.drop_column("client_hash")

    with op.batch_alter_table("price_alerts") as batch:
        batch.drop_index("ix_price_alerts_confirmed")
        batch.drop_column("confirmed_at")
        batch.drop_column("confirmed")
