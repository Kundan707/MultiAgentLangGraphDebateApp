import json

from fastapi.testclient import TestClient

from forum.app import create_app
from forum.claude import AgentError
from forum.config import Settings


class FakeRunner:
    async def run(self, resolution, emit):
        emit({"type": "case", "role": "Affirmative", "case": ["Claim", resolution, "Claim", "Reason"], "sources": []})
        emit({"type": "complete", "model": "test-model"})


def make_client(key="test-secret", runner=None):
    return TestClient(create_app(Settings(api_key=key), runner or FakeRunner()), base_url="http://localhost:8000")


def headers(origin="http://localhost:8000"):
    return {"origin": origin, "content-type": "application/json"}


def test_stream_contract_config_and_static_assets():
    with make_client() as client:
        response = client.post("/api/debate", headers=headers(), json={"resolution": "Schools should ban phones."})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["type"] == "case"
        assert events[-1]["type"] == "complete"
        assert client.get("/api/config").json()["backend"] == "python"
        assert "test-secret" not in client.get("/api/config").text
        assert "The Forum" in client.get("/").text
        assert client.get("/kokoro-worker.js").status_code == 200
        assert client.get("/kokoro-lib.js").status_code == 200
        assert client.get("/.env.local").status_code == 404
        assert client.get("/forum/config.py").status_code == 404
        assert client.get("/healthz").json()["status"] == "ok"


def test_request_validation_origin_and_key():
    with make_client() as client:
        assert client.post("/api/debate", headers=headers("https://evil.example"), json={"resolution": "A complete resolution"}).status_code == 403
        for payload in [{"resolution": 42}, {"resolution": "short"}, None, []]:
            assert client.post("/api/debate", headers=headers(), content=json.dumps(payload)).status_code == 400
        assert client.post("/api/debate", headers=headers(), content="not JSON").status_code == 400
        assert client.post("/api/debate", headers=headers(), content='{"resolution":"'+'a'*6000+'"}').status_code == 413
    with make_client(key="") as client:
        assert client.post("/api/debate", headers=headers(), json={"resolution": "A complete resolution"}).status_code == 503


def test_stream_errors_are_redacted_and_sessions_are_released():
    class FailedRunner:
        async def run(self, resolution, emit):
            raise RuntimeError("private provider internals")
    with make_client(runner=FailedRunner()) as client:
        for _ in range(2):
            response = client.post("/api/debate", headers=headers(), json={"resolution": "A complete resolution"})
            assert response.status_code == 200
            assert json.loads(response.text)["type"] == "error"
            assert "private provider internals" not in response.text


def test_untrusted_host_is_rejected():
    with make_client() as client:
        assert client.get("/api/config", headers={"host": "evil.example"}).status_code == 400


async def test_concurrent_duplicate_and_timeout_release():
    import asyncio
    import httpx
    import pytest
    started, release = asyncio.Event(), asyncio.Event()
    class WaitingRunner:
        async def run(self, resolution, emit):
            started.set()
            await release.wait()
            emit({"type": "complete", "model": "test"})
    app = create_app(Settings(api_key="test", debate_timeout=1), WaitingRunner())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000") as client:
        first = asyncio.create_task(client.post("/api/debate", headers=headers(), json={"resolution": "A complete resolution"}))
        await started.wait()
        duplicate = await client.post("/api/debate", headers=headers(), json={"resolution": "Another complete resolution"})
        assert duplicate.status_code == 429
        release.set()
        assert (await first).status_code == 200
    class TimedOutRunner:
        async def run(self, resolution, emit):
            await asyncio.sleep(60)
    app = create_app(Settings(api_key="test", debate_timeout=0.01), TimedOutRunner())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000") as client:
        for _ in range(2):
            response = await client.post("/api/debate", headers=headers(), json={"resolution": "A complete resolution"})
            assert response.status_code == 200
            assert "timed out" in response.text
