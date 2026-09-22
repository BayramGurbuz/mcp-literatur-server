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


def test_ask_endpoint_rejects_missing_question():
    response = client.post("/ask", json={})
    assert response.status_code == 422


def test_home_page_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
