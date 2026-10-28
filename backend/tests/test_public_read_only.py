"""Use a synthetic API only; never import main_api, config or a broker runner."""
import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
import pytest

from app.public_read_only import PublicReadOnlyMiddleware, READ_ONLY_MESSAGE, public_read_only


def fake_api(environment):
    app = FastAPI()
    effects = []

    @app.api_route("/api/live/start", methods=["POST", "PUT", "PATCH", "DELETE"])
    def mutate():
        effects.append("mutation")
        return {"success": True}

    @app.api_route("/api", methods=["POST"])
    def api_root():
        effects.append("root mutation")
        return {"success": True}

    @app.api_route("/api/research", methods=["GET", "HEAD"])
    def research():
        return {"source": "synthetic"}

    @app.post("/outside-api")
    def outside():
        return {"scope": "outside-api"}

    app.add_middleware(PublicReadOnlyMiddleware, environment=environment)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    return TestClient(app), effects


@pytest.mark.parametrize("environment", [
    {"SPACE_ID": "example/public-research"},
    {"SPACE_ID": "example/public-research", "QUANT_PUBLIC_READ_ONLY": "0"},
    {"SPACE_ID": "", "QUANT_PUBLIC_READ_ONLY": "0"},
    {"QUANT_PUBLIC_READ_ONLY": "1"},
])
def test_public_mode_rejects_all_api_mutations_before_handlers_run(environment):
    client, effects = fake_api(environment)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, "/api/live/start", content=b"not even valid JSON")
        assert response.status_code == 403
        assert response.json() == {"detail": READ_ONLY_MESSAGE, "code": "public_read_only"}
    assert client.post("/api").status_code == 403
    assert effects == []


@pytest.mark.parametrize("environment", [{}, {"QUANT_PUBLIC_READ_ONLY": "0"}])
def test_local_execution_controls_remain_available_without_space_environment(environment):
    client, effects = fake_api(environment)
    assert not public_read_only(environment)
    assert client.post("/api/live/start").status_code == 200
    assert effects == ["mutation"]


def test_read_queries_head_and_cors_preflight_remain_available_and_denials_have_cors_headers():
    client, effects = fake_api({"SPACE_ID": "example/public-research"})
    assert client.get("/api/research").json() == {"source": "synthetic"}
    assert client.head("/api/research").status_code == 200
    preflight = client.options("/api/live/start", headers={"Origin": "https://example.org",
                                                          "Access-Control-Request-Method": "POST",
                                                          "Access-Control-Request-Headers": "content-type"})
    assert preflight.status_code == 200
    denied = client.post("/api/live/start", headers={"Origin": "https://example.org"})
    assert denied.status_code == 403
    assert denied.headers["access-control-allow-origin"] in {"*", "https://example.org"}
    assert effects == []
    assert client.post("/outside-api").status_code == 200


def test_actual_api_registers_boundary_inside_cors_without_importing_api():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "main_api.py").read_text())
    registrations = [node.value for node in tree.body if isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                     and node.value.func.attr == "add_middleware" and node.value.args
                     and isinstance(node.value.args[0], ast.Name)]
    names = [node.args[0].id for node in registrations]
    assert names.count("PublicReadOnlyMiddleware") == 1
    assert names.index("PublicReadOnlyMiddleware") < names.index("CORSMiddleware")
