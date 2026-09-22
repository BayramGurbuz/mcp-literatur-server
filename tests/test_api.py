from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_endpoint_returns_answer_field():
    with patch("api.ask", new_callable=AsyncMock, return_value="sahte cevap"):
        response = client.post("/ask", json={"question": "SSVEP nedir?"})
    assert response.status_code == 200
    assert response.json() == {"answer": "sahte cevap"}


def test_ask_endpoint_rejects_missing_question():
    response = client.post("/ask", json={})
    assert response.status_code == 422
