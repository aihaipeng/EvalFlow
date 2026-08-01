"""Create the application schema and absorb supported pre-Alembic databases."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from execution.database_schema import metadata


revision = "20260802_0001"
down_revision = None
branch_labels = None
depends_on = None

LEGACY_WORKFLOW_TABLES = (
    "workflow_node_runs", "workflow_node_runs_v2", "node_runs", "artifacts",
    "attempts", "step_runs", "case_runs", "workflow_runs", "workflow_runs_v2",
    "runs", "testset_workflow_bindings", "testset_execution_configs",
    "workflow_drafts", "workflow_definitions_v2", "workflows", "schema_migrations",
)


def _columns(table_name: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table_name in LEGACY_WORKFLOW_TABLES:
        if table_name in existing:
            op.drop_table(table_name)

    # Create every missing table/index from the frozen v1 application schema.
    metadata.create_all(bind=op.get_bind(), checkfirst=True)

    columns = _columns("model_providers")
    additions = (
        ("proxy_mode", sa.Column("proxy_mode", sa.Text(), nullable=False, server_default="SYSTEM")),
        ("proxy_url", sa.Column("proxy_url", sa.Text())),
        ("proxy_username", sa.Column("proxy_username", sa.Text())),
        ("proxy_password", sa.Column("proxy_password", sa.Text())),
        ("verify_ssl", sa.Column("verify_ssl", sa.Integer(), nullable=False, server_default="1")),
        ("model_configs_json", sa.Column("model_configs_json", sa.Text(), nullable=False, server_default="{}")),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("model_providers", column)
            if name == "verify_ssl" and "skip_ssl_verify" in columns:
                op.execute(
                    "UPDATE model_providers SET verify_ssl = "
                    "CASE WHEN skip_ssl_verify = 1 THEN 0 ELSE 1 END"
                )

    if "version" in _columns("test_sets"):
        op.execute("ALTER TABLE test_sets DROP COLUMN version")


def downgrade() -> None:
    raise RuntimeError("The baseline migration is intentionally irreversible")
