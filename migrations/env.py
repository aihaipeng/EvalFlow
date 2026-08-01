from __future__ import annotations

from logging.config import fileConfig

from alembic import context


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("Alembic migrations require an application-managed connection")
    context.configure(connection=connection, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
