"""Verify the retired route without importing API, broker or startup modules."""
import ast
import asyncio
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "main_api.py"


def handler_ast():
    module = ast.parse(SOURCE.read_text())
    matches = [n for n in module.body if isinstance(n, ast.AsyncFunctionDef)
               and n.name == "get_quant_live_dashboard"]
    assert len(matches) == 1
    return matches[0]


def test_retired_dashboard_returns_410_without_importing_application():
    class StubHTTPException(Exception):
        def __init__(self, status_code, detail):
            self.status_code, self.detail = status_code, detail

    node = handler_ast()
    route = node.decorator_list[0]
    assert isinstance(route, ast.Call)
    assert route.func.attr == "get"
    assert route.args[0].value == "/charts/quant_live_dashboard.html"
    node.decorator_list = []
    isolated = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {"HTTPException": StubHTTPException}
    exec(compile(isolated, "<retired-route-only>", "exec"), namespace)
    try:
        asyncio.run(namespace[node.name]())
    except StubHTTPException as error:
        assert error.status_code == 410
        assert "look-ahead" in error.detail
        assert "not valid evidence of trading returns" in error.detail
    else:
        raise AssertionError("The obsolete performance route must be retired")


def test_retired_handler_cannot_generate_or_serve_old_returns():
    node = handler_ast()
    node.decorator_list = []
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(node))
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
    assert len(calls) == 1
    assert isinstance(calls[0].func, ast.Name)
    assert calls[0].func.id == "HTTPException"
    assert not any(isinstance(n, ast.Return) for n in ast.walk(node))


def test_retired_html_is_absent_from_public_static_directories():
    root = SOURCE.parents[1]
    for directory in (root / "backend/data/charts", root / "frontend/public", root / "frontend/dist"):
        assert not (directory / "quant_live_dashboard.html").exists()
    # Historical source is retained; the obsolete artifact must not be served.
    assert (root / "scripts/generate_interactive_quant_dashboard.py").is_file()
