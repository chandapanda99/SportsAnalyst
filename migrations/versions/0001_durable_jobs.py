"""Durable jobs and resumable progress events."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_durable_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("jobs"):
        op.create_table(
            "jobs",
            sa.Column("job_id", sa.Text, primary_key=True), sa.Column("kind", sa.Text, nullable=False),
            sa.Column("payload", postgresql.JSONB, nullable=False),
            sa.Column("status", sa.Text, nullable=False, server_default="queued"),
            sa.Column("progress", sa.Float, nullable=False, server_default="0"),
            sa.Column("message", sa.Text, nullable=False, server_default="Queued"),
            sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("lease_owner", sa.Text), sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column("result_id", sa.Text), sa.Column("error", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    else:
        _require_columns(inspector, "jobs", {
            "job_id", "kind", "payload", "status", "progress", "message", "attempts", "max_attempts",
            "available_at", "lease_owner", "lease_expires_at", "result_id", "error", "created_at", "updated_at",
        })
    inspector = sa.inspect(bind)
    if "jobs_claimable_idx" not in {item["name"] for item in inspector.get_indexes("jobs")}:
        op.create_index("jobs_claimable_idx", "jobs", ["status", "available_at", "lease_expires_at"])
    if not inspector.has_table("job_events"):
        op.create_table(
            "job_events", sa.Column("sequence", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column("job_id", sa.Text, sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
            sa.Column("stage", sa.Text, nullable=False), sa.Column("message", sa.Text, nullable=False),
            sa.Column("progress", sa.Float, nullable=False),
            sa.Column("details", postgresql.JSONB, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    else:
        _require_columns(sa.inspect(bind), "job_events", {
            "sequence", "job_id", "stage", "message", "progress", "details", "created_at",
        })
    inspector = sa.inspect(bind)
    if "job_events_stream_idx" not in {item["name"] for item in inspector.get_indexes("job_events")}:
        op.create_index("job_events_stream_idx", "job_events", ["job_id", "sequence"])


def _require_columns(inspector, table, expected):
    missing = expected - {item["name"] for item in inspector.get_columns(table)}
    if missing:
        raise RuntimeError(f"Existing {table} table is incompatible; missing columns: {sorted(missing)}")


def downgrade():
    # This baseline can adopt tables that existed before Alembic. Never destroy
    # those tables (and their job history) during a revision downgrade.
    raise RuntimeError("The durable-job baseline cannot be downgraded automatically")
