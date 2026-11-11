"""FastAPI server for the local Python version and existing browser frontend."""
import asyncio
import json
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .claude import AgentError, ClaudeClient
from .config import ROOT, Settings
from .debate import DebateRunner
from .coordinator import Coordinator
from .memory import DebateMemory, Journal
from .models import HUMAN_TURN, HumanDebater
from pydantic import ValidationError
from .tools import memory_search_tool
from langsmith import tracing_context


def create_app(settings: Settings | None = None, runner=None, memory=None, journal=None, enable_coordinator=None) -> FastAPI:
    settings = settings or Settings.from_env()
    coordinated = (runner is None) if enable_coordinator is None else enable_coordinator
    client = None if runner else ClaudeClient(settings)
    runner = runner or DebateRunner(client)
    if coordinated:
        memory = memory or DebateMemory()
        journal = journal or Journal(ROOT / "data")
    coordinator = Coordinator(runner, memory, journal) if coordinated else None
    active: set[str] = set()
    active_sessions: set[str] = set()
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        if client:
            await client.close()
        if coordinated:
            await asyncio.to_thread(memory.close)

    app = FastAPI(title="The Forum — Python agents", lifespan=lifespan)
    hosts = {"localhost", "127.0.0.1", "[::1]"}
    hosts.update(urlsplit(origin).hostname for origin in settings.allowed_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(filter(None, hosts)), www_redirect=False)

    @app.get("/api/config")
    async def config():
        return JSONResponse({"ready": bool(settings.api_key), "model": settings.model,
                             "backend": "python", "memory": coordinated, "coordinator": coordinated}, headers={"Cache-Control": "no-store"})

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "backend": "python"}

    def valid_origin(request):
        allowed = settings.allowed_origins or (str(request.base_url).rstrip("/"),)
        return request.headers.get("origin", "") in allowed

    async def matches_for(resolution):
        if not coordinated:
            return []
        with tracing_context(enabled=False):
            return await memory_search_tool(memory).ainvoke({"resolution": resolution})

    @app.post("/api/debates/check")
    async def check_memory(request: Request):
        if not valid_origin(request):
            return JSONResponse({"error": "Use the debate room."}, status_code=403)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2000:
                return JSONResponse({"error": "Resolution is too long"}, status_code=413)
        try:
            body = json.loads(raw)
            resolution = body.get("resolution", "").strip()
            if not isinstance(resolution, str) or not 12 <= len(resolution) <= 300:
                raise ValueError()
        except (ValueError, AttributeError, TypeError):
            return JSONResponse({"error": "Enter a complete resolution."}, status_code=400)
        try:
            return {"matches": await matches_for(resolution)}
        except Exception:
            return {"matches": [], "requires_human": True,
                    "error": "Debate memory is unavailable. Retry, or explicitly choose a new debate without memory lookup."}

    @app.get("/api/debates/{debate_id}")
    async def get_debate(debate_id: str):
        try:
            UUID(debate_id)
            record = await asyncio.to_thread(memory.get, debate_id) if coordinated else None
        except (ValueError, TypeError):
            record = None
        if not record:
            return JSONResponse({"error": "Saved debate not found."}, status_code=404)
        return JSONResponse(record, headers={"Cache-Control": "no-store"})

    @app.get("/api/sessions")
    async def pending_sessions():
        states = await asyncio.to_thread(journal.list_pending) if coordinated else []
        return {"sessions": [{key: state.get(key) for key in ("id", "resolution", "status", "updated_at")} for state in states]}

    @app.post("/api/debate")
    async def debate(request: Request):
        origin = request.headers.get("origin", "")
        allowed = settings.allowed_origins or (str(request.base_url).rstrip("/"),)
        if origin not in allowed:
            return JSONResponse({"error": "Use the debate room to start a session."}, status_code=403)
        if not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"error": "Expected JSON"}, status_code=415)
        if not settings.api_key:
            return JSONResponse({"error": "Set ANTHROPIC_API_KEY in .env.local to enable live agents."}, status_code=503)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return JSONResponse({"error": "Debate submission is too long."}, status_code=413)
        try:
            payload = json.loads(body)
            resolution = payload.get("resolution") if isinstance(payload, dict) else None
            resolution = resolution.strip() if isinstance(resolution, str) else ""
        except (ValueError, UnicodeError):
            return JSONResponse({"error": "Invalid request"}, status_code=400)
        if len(body) > 5000 and (not isinstance(payload, dict) or "submission" not in payload):
            return JSONResponse({"error": "Debate submission is too long."}, status_code=413)
        if not 12 <= len(resolution) <= 300:
            return JSONResponse({"error": "Enter a resolution between 12 and 300 characters."}, status_code=400)
        session_id = payload.get("session_id")
        human_input = payload.get("human_input", "")
        if not isinstance(human_input, str) or len(human_input) > 2000:
            return JSONResponse({"error": "Keep clarification under 2000 characters."}, status_code=400)
        debater = submission = None
        try:
            if "debater" in payload:
                if session_id or not coordinated:
                    raise ValueError()
                debater = HumanDebater.model_validate(payload["debater"]).model_dump()
            if "submission" in payload:
                if not session_id:
                    raise ValueError()
                submission = HUMAN_TURN.validate_python(payload["submission"])
        except (ValidationError, ValueError):
            return JSONResponse({"error": "Check your name, side, and debate responses before continuing."}, status_code=400)
        if session_id:
            if not coordinated:
                return JSONResponse({"error": "Coordinator checkpoints are unavailable."}, status_code=400)
            state = await asyncio.to_thread(journal.get, session_id) if isinstance(session_id, str) else None
            if not state or state["resolution"] != resolution:
                return JSONResponse({"error": "Checkpoint not found for this resolution."}, status_code=404)
            if submission and not state.get("debater"):
                return JSONResponse({"error": "This debate has no human debater."}, status_code=400)
            if state["status"] == "complete":
                return JSONResponse({"error": "This debate is already complete. Open its saved result."}, status_code=409)
        else:
            try:
                matches = await matches_for(resolution)
            except Exception:
                if payload.get("force_new") is not True:
                    return JSONResponse({"requires_human": True, "matches": [], "error": "Memory lookup failed. Choose a new debate explicitly to continue."}, status_code=409)
                matches = []
            if matches and payload.get("force_new") is not True:
                return JSONResponse({"matches": matches}, status_code=409)
        visitor = request.client.host if request.client else "local"
        async with lock:
            if visitor in active or (session_id and session_id in active_sessions) or len(active) >= settings.max_concurrent:
                return JSONResponse({"error": "A debate is already running. Please wait a moment."}, status_code=429)
            active.add(visitor)
            if session_id:
                active_sessions.add(session_id)

        running_session_id = session_id

        async def events():
            nonlocal running_session_id
            queue: asyncio.Queue[dict | None] = asyncio.Queue()
            def deliver(event):
                nonlocal running_session_id
                if event.get("type") == "session":
                    running_session_id = event["session_id"]
                    active_sessions.add(running_session_id)
                queue.put_nowait(event)

            async def produce():
                try:
                    async with asyncio.timeout(settings.debate_timeout):
                        if coordinated:
                            await coordinator.run(resolution, deliver, session_id=session_id, human_input=human_input, force_new=payload.get("force_new") is True,
                                                  debater=debater, submission=submission)
                        else:
                            await runner.run(resolution, queue.put_nowait)
                except TimeoutError:
                    queue.put_nowait({"type": "error", "error": "The debate timed out. Please try again."})
                except AgentError as error:
                    queue.put_nowait({"type": "error", "error": str(error)})
                except Exception:
                    queue.put_nowait({"type": "error", "error": "The debate could not finish. Please try again."})
                finally:
                    queue.put_nowait(None)
            task = asyncio.create_task(produce())
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=12)
                    except TimeoutError:
                        event = {"type": "heartbeat"}
                    if event is None:
                        break
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                async with lock:
                    active.discard(visitor)
                    if running_session_id:
                        active_sessions.discard(running_session_id)

        return StreamingResponse(events(), media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                     "X-Accel-Buffering": "no"})

    # Explicit allowlist: environment files, model credentials and Python code
    # can never be served through this route.
    assets = {"/": ROOT / "public/index.html"}
    assets.update({"/" + name: ROOT / "public" / name for name in (
        "app.js", "style.css", "voice.js", "kokoro-audio.js", "kokoro-worker.js")})
    assets["/kokoro-lib.js"] = ROOT / "node_modules/kokoro-js/dist/kokoro.web.js"
    assets["/kokoro-LICENSE.txt"] = ROOT / "node_modules/kokoro-js/LICENSE"

    @app.get("/{path:path}", include_in_schema=False)
    async def asset(path: str):
        target = assets.get("/" + path)
        if target is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if not target.is_file():
            return JSONResponse({"error": "Install browser voice assets with npm ci, then reload."}, status_code=503)
        media = "text/javascript" if target.suffix == ".js" else None
        return FileResponse(target, media_type=media,
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

    return app
