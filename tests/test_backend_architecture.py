import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, [alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, []


def test_execution_domain_does_not_import_web_layer():
    violations = []
    for path in (ROOT / "execution").glob("*.py"):
        for module, _names in _imports(path):
            if module == "web" or module.startswith("web."):
                violations.append((path.name, module))
    assert violations == []


def test_route_modules_do_not_import_other_route_modules():
    violations = []
    for path in (ROOT / "web").glob("routes_*.py"):
        for module, _names in _imports(path):
            if module.startswith("web.routes_"):
                violations.append((path.name, module))
    assert violations == []


def test_backend_modules_do_not_import_private_cross_module_helpers():
    violations = []
    for directory in ("execution", "web", "storage"):
        for path in (ROOT / directory).glob("*.py"):
            for module, names in _imports(path):
                if module.startswith(("execution.", "web.", "storage.")):
                    private = [name for name in names if name.startswith("_")]
                    if private:
                        violations.append((str(path.relative_to(ROOT)), module, private))
    assert violations == []


def test_node_executor_remains_a_small_dispatch_coordinator():
    path = ROOT / "execution" / "workflow_node_executor.py"
    source = path.read_text(encoding="utf-8")

    assert len(source.splitlines()) <= 200
    assert "def _execute_script" not in source
    assert "def _execute_llm" not in source
    assert "def _execute_http" not in source


def test_model_provider_routes_have_no_repository_singleton_state():
    source = (ROOT / "web" / "routes_model_providers.py").read_text(encoding="utf-8")

    assert "_repository_instance" not in source
    assert "_repository_path" not in source
    assert "DATABASE_PATH" not in source
