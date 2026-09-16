"""Add a leased dispatch outbox without changing existing queue records."""
import sqlalchemy as sa
from alembic import op

revision = "0002_cloud_dispatch"
down_revision = "0001_durable_jobs"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("jobs")}
    for column in (
        sa.Column("dispatch_state", sa.Text, nullable=False, server_default="pending"),
        sa.Column("dispatch_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
    ):
        if column.name not in columns:
            op.add_column("jobs", column)


def downgrade():
    for name in ("dispatched_at", "dispatch_lease_expires_at", "dispatch_attempts", "dispatch_state"):
        op.drop_column("jobs", name)
