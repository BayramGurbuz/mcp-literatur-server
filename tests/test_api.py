from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_endpoint_returns_answer_and_trace():
    fake_trace = [{"tool": "search_papers", "args": {"query": "SSVEP"}, "result": "PMID 1: ..."}]
    with patch("api.ask_with_trace", new_callable=AsyncMock, return_value=("sahte cevap", fake_trace)):
        response = client.post("/ask", json={"question": "SSVEP nedir?"})
    assert response.status_code == 200
    assert response.json() == {"answer": "sahte cevap", "trace": fake_trace}


def test_ask_endpoint_returns_readable_error_when_agent_fails():
    with patch("api.ask_with_trace", new_callable=AsyncMock, side_effect=RuntimeError("429 RESOURCE_EXHAUSTED")):
        response = client.post("/ask", json={"question": "SSVEP nedir?"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "tekrar deneyin" in detail
    assert "RESOURCE_EXHAUSTED" not in detail


def test_ask_endpoint_handles_empty_answer():
    with patch("api.ask_with_trace", new_callable=AsyncMock, return_value=(None, [])):
        response = client.post("/ask", json={"question": "SSVEP nedir?"})
    assert response.status_code == 200
    assert "cevap metni üretmedi" in response.json()["answer"]


def test_ask_endpoint_rejects_missing_question():
    response = client.post("/ask", json={})
    assert response.status_code == 422


def test_home_page_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
