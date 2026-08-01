"""SQLAlchemy Core table definitions for Agent Bench's local database."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)


metadata = MetaData()

model_providers = Table(
    "model_providers", metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text), Column("website_url", Text),
    Column("api_key", Text, nullable=False), Column("base_url", Text, nullable=False),
    Column("protocol", Text, nullable=False),
    Column("proxy_mode", Text, nullable=False, server_default="SYSTEM"),
    Column("proxy_url", Text), Column("proxy_username", Text), Column("proxy_password", Text),
    Column("verify_ssl", Integer, nullable=False, server_default="1"),
    Column("model_endpoint", Text), Column("models_json", Text, nullable=False),
    Column("model_configs_json", Text, nullable=False, server_default="{}"),
    Column("created_at", Text, nullable=False), Column("updated_at", Text, nullable=False),
)

node_structural_models = Table(
    "node_structural_models", metadata,
    Column("id", Text, primary_key=True), Column("type", Text, nullable=False),
    Column("name", Text, nullable=False), Column("description", Text, nullable=False, server_default=""),
    Column("definition_json", Text, nullable=False),
    Column("created_at", Text, nullable=False), Column("updated_at", Text, nullable=False),
    CheckConstraint("type IN ('START','SCRIPT','LLM','HTTP','END')", name="node_type"),
    CheckConstraint("length(trim(name)) > 0", name="node_name_nonblank"),
    CheckConstraint("json_valid(definition_json)", name="node_definition_json_valid"),
    CheckConstraint("json_type(definition_json) = 'object'", name="node_definition_json_object"),
)
Index(
    "node_structural_models_by_type_updated",
    node_structural_models.c.type,
    node_structural_models.c.updated_at.desc(), node_structural_models.c.id.desc(),
)

test_sets = Table(
    "test_sets", metadata,
    Column("id", Text, primary_key=True),
    Column("name", String(collation="NOCASE"), nullable=False, unique=True),
    Column("description", Text, nullable=False, server_default=""),
    Column("created_at", Text, nullable=False), Column("updated_at", Text, nullable=False),
)
Index("idx_test_sets_updated", test_sets.c.updated_at.desc(), test_sets.c.id.desc())

test_set_columns = Table(
    "test_set_columns", metadata,
    Column("test_set_id", Text, ForeignKey("test_sets.id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, primary_key=True), Column("column_key", Text, nullable=False),
    UniqueConstraint("test_set_id", "column_key"),
)
test_cases = Table(
    "test_cases", metadata,
    Column("id", Text, primary_key=True),
    Column("test_set_id", Text, ForeignKey("test_sets.id", ondelete="CASCADE"), nullable=False),
    Column("position", Integer, nullable=False), Column("values_json", Text, nullable=False),
    UniqueConstraint("test_set_id", "position"),
)
Index("idx_test_cases_set_position", test_cases.c.test_set_id, test_cases.c.position)

workflow_structural_models = Table(
    "workflow_structural_models", metadata,
    Column("id", Text, primary_key=True), Column("name", Text, nullable=False, unique=True),
    Column("description", Text, nullable=False, server_default=""),
    Column("created_at", Text, nullable=False), Column("updated_at", Text, nullable=False),
    CheckConstraint("length(trim(name)) > 0", name="workflow_name_nonblank"),
)
Index(
    "workflow_structural_models_by_updated",
    workflow_structural_models.c.updated_at.desc(), workflow_structural_models.c.id.desc(),
)
workflow_node_bindings = Table(
    "workflow_node_bindings", metadata,
    Column("workflow_id", Text, ForeignKey("workflow_structural_models.id", ondelete="CASCADE"), primary_key=True),
    Column("node_id", Text, ForeignKey("node_structural_models.id", ondelete="CASCADE"), primary_key=True, unique=True),
    Column("position_x", Float, nullable=False), Column("position_y", Float, nullable=False),
)
workflow_edges = Table(
    "workflow_edges", metadata,
    Column("id", Text, primary_key=True), Column("workflow_id", Text, nullable=False),
    Column("source_node_id", Text, nullable=False), Column("target_node_id", Text, nullable=False),
    UniqueConstraint("workflow_id", "source_node_id", "target_node_id"),
    ForeignKeyConstraint(
        ["workflow_id", "source_node_id"],
        ["workflow_node_bindings.workflow_id", "workflow_node_bindings.node_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["workflow_id", "target_node_id"],
        ["workflow_node_bindings.workflow_id", "workflow_node_bindings.node_id"],
        ondelete="CASCADE",
    ),
)
Index("workflow_edges_by_workflow", workflow_edges.c.workflow_id, workflow_edges.c.source_node_id, workflow_edges.c.target_node_id)

batch_schedules = Table(
    "batch_schedules", metadata,
    Column("batch_id", Text, primary_key=True), Column("enabled", Integer, nullable=False),
    Column("cadence", Text, nullable=False), Column("run_at", Text, nullable=False),
    Column("run_time", Text, nullable=False), Column("weekdays_json", Text, nullable=False),
    Column("month_day", Integer, nullable=False), Column("timezone", Text, nullable=False),
    Column("overlap_policy", Text, nullable=False), Column("next_run_at", Text),
    Column("last_run_at", Text), Column("last_error", Text),
    Column("created_at", Text, nullable=False), Column("updated_at", Text, nullable=False),
    CheckConstraint("enabled IN (0, 1)", name="batch_schedule_enabled"),
)
Index("batch_schedules_due", batch_schedules.c.enabled, batch_schedules.c.next_run_at)

batch_execution_history = Table(
    "batch_execution_history", metadata,
    Column("id", Text, primary_key=True), Column("batch_id", Text, nullable=False),
    Column("execution_round_id", Text),
    Column("workflow_id", Text, ForeignKey("workflow_structural_models.id", ondelete="CASCADE"), nullable=False),
    Column("test_set_name", Text, nullable=False), Column("workflow_name", Text, nullable=False),
    Column("total_cases", Integer, nullable=False), Column("executed_cases", Integer, nullable=False),
    Column("passed_cases", Integer, nullable=False), Column("started_at", Text, nullable=False),
    Column("finished_at", Text, nullable=False), Column("created_at", Text, nullable=False),
    CheckConstraint("total_cases >= 0", name="history_total_nonnegative"),
    CheckConstraint("executed_cases >= 0", name="history_executed_nonnegative"),
    CheckConstraint("passed_cases >= 0", name="history_passed_nonnegative"),
)
Index("batch_execution_history_by_batch", batch_execution_history.c.batch_id, batch_execution_history.c.finished_at.desc(), batch_execution_history.c.created_at.desc(), batch_execution_history.c.id.desc())
Index("batch_execution_history_by_workflow", batch_execution_history.c.workflow_id)
