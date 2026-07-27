import ast
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from execution.init_db import database_initialize_lock_for
from execution.model_providers import ModelProviderRepository
from execution.node_structural_models import NodeStructuralRepository
from execution.workflow_structural_models import WorkflowStructuralRepository


@pytest.mark.parametrize(
    ("repository_cls", "database_name"),
    [
        (ModelProviderRepository, "model-providers.sqlite3"),
        (NodeStructuralRepository, "nodes.sqlite3"),
        (WorkflowStructuralRepository, "workflows.sqlite3"),
    ],
)
def test_repositories_initialize_sqlite_for_concurrent_read_write(
    tmp_path, repository_cls, database_name
):
    database = tmp_path / database_name
    repository = repository_cls(database)

    repository.initialize()

    with sqlite3.connect(database) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    with repository._connect() as connection:
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]

    assert journal_mode == "wal"
    assert synchronous == 1


def test_shared_repositories_use_one_initialize_lock_for_same_database(tmp_path):
    database = tmp_path / "agent-bench.sqlite3"

    model_provider_repository = ModelProviderRepository(database)
    node_repository = NodeStructuralRepository(database)

    assert model_provider_repository._initialize_lock is database_initialize_lock_for(database)
    assert node_repository._initialize_lock is model_provider_repository._initialize_lock


def test_all_repositories_initialize_same_database_concurrently(tmp_path):
    database = tmp_path / "agent-bench.sqlite3"
    repositories = [
        ModelProviderRepository(database),
        NodeStructuralRepository(database),
        WorkflowStructuralRepository(database),
    ]
    assert len({id(repository._initialize_lock) for repository in repositories}) == 1
    ready = threading.Barrier(len(repositories))

    def initialize(repository):
        ready.wait(timeout=5)
        repository.initialize()

    with ThreadPoolExecutor(max_workers=len(repositories)) as executor:
        futures = [executor.submit(initialize, repository) for repository in repositories]
        for future in futures:
            future.result(timeout=10)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    assert {
        "model_providers",
        "node_structural_models",
        "workflow_structural_models",
        "workflow_node_bindings",
        "workflow_edges",
    } <= tables
    assert repositories[0].list() == []
    assert repositories[1].list() == []
    assert repositories[2].list() == []


def test_model_providers_do_not_import_targets_module():
    source = Path("execution/model_providers.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "execution.targets" not in imported_modules


def test_target_business_module_is_removed():
    assert not Path("execution/targets.py").exists()
    assert not Path("web/routes_targets.py").exists()


def test_sqlite_initialization_dependency_direction_is_centralized():
    repository_paths = [
        Path("execution/model_providers.py"),
        Path("execution/node_structural_models.py"),
        Path("execution/workflow_structural_models.py"),
    ]

    for repository_path in repository_paths:
        source = repository_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "execution.init_db" in imported_modules
        assert "_INITIALIZE_LOCKS" not in source

    init_tree = ast.parse(Path("execution/init_db.py").read_text(encoding="utf-8"))
    init_imports = {
        node.module
        for node in ast.walk(init_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not init_imports.intersection(
        {
            "execution.targets",
            "execution.model_providers",
            "execution.node_structural_models",
            "execution.workflow_structural_models",
        }
    )
