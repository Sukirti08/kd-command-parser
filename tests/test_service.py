import os

os.environ["SKIP_MODEL_LOAD"] = "1"
os.environ["MODEL_VERSION"] = "vtest"
os.environ["POD_NAME"] = "pod-a"

import pytest  # noqa: E402
from app import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class FakeGen:
    def generate(self, text):
        return '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.state, "ready", False)
    monkeypatch.setattr(main.state, "generator", None)
    monkeypatch.delenv("FAULT_INJECT", raising=False)
    return TestClient(main.app)


def test_healthz_alive_and_readyz_503_before_load(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503
    assert client.post("/parse", json={"text": "hi"}).status_code == 503


def test_parse_returns_frame_and_headers(client, monkeypatch):
    monkeypatch.setattr(main.state, "generator", FakeGen())
    monkeypatch.setattr(main.state, "ready", True)
    assert client.get("/readyz").status_code == 200
    r = client.post("/parse", json={"text": "what is the weather in london"})
    assert r.status_code == 200
    assert r.json() == {"intent": "weather_query", "date": None, "time": None, "place": "london"}
    assert r.headers["X-Model-Version"] == "vtest"
    assert r.headers["X-Served-By"] == "pod-a"


def test_fault_inject_returns_exact_500(client, monkeypatch):
    monkeypatch.setattr(main.state, "generator", FakeGen())
    monkeypatch.setattr(main.state, "ready", True)
    monkeypatch.setenv("FAULT_INJECT", "1")
    r = client.post("/parse", json={"text": "what is the weather in london"})
    assert r.status_code == 500
    assert r.content == b'{"error":"invalid_model_output"}'
