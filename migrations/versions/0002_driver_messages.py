"""Store private messages written by authenticated drivers."""
from alembic import op
import sqlalchemy as sa

revision = "0002_driver_messages"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "driver_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_driver_messages_driver_id", "driver_messages", ["driver_id"])


def downgrade():
    op.drop_index("ix_driver_messages_driver_id", table_name="driver_messages")
    op.drop_table("driver_messages")
