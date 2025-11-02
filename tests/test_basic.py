import os
import sys

# Ensure project root is on path for 'controller' imports
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient
from controller.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "status" in resp.json()


def test_bad_model_format():
    # Missing provider prefix
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert resp.status_code in (400, 500)


def test_policy_routing_mock():
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "",
            "messages": [{"role": "user", "content": "Write Python code"}],
            "extra_body": {"routing_policy": "task_router"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
