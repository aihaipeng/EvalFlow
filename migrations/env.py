from __future__ import annotations

import logging

from alembic import context


config = context.config
# 只显式配置迁移相关 logger，避免 fileConfig 重置 root/uvicorn 的日志配置。
# uvicorn 的 dictConfig 会禁用未列出的既有 logger，需同时清除 disabled 标志。
alembic_logger = logging.getLogger("alembic")
alembic_logger.setLevel(logging.INFO)
alembic_logger.disabled = False
sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
sqlalchemy_logger.setLevel(logging.WARN)
sqlalchemy_logger.disabled = False


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("Alembic migrations require an application-managed connection")
    context.configure(connection=connection, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
