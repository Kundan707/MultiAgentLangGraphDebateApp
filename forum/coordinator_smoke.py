"""One bounded live coordinator run with real local memory and retrieval checks."""
import asyncio
import json

from .claude import ClaudeClient
from .config import ROOT, Settings
from .coordinator import Coordinator
from .debate import DebateRunner
from .memory import DebateMemory, Journal


async def main():
    settings = Settings.from_env()
    client = ClaudeClient(settings)
    memory = DebateMemory()
    journal = Journal(ROOT / "data")
    events = []
    def report(event):
        events.append(event)
        print(json.dumps({key: event[key] for key in ("type", "role", "action", "winner", "scores", "reason", "question") if key in event}), flush=True)
    try:
        async with asyncio.timeout(settings.debate_timeout):
            await Coordinator(DebateRunner(client), memory, journal).run(
                "Schools should ban smartphones during the school day.", report, force_new=True)
        if events[-1]["type"] != "complete":
            raise SystemExit("Coordinator paused for a human; inspect the checkpoint before continuing.")
        session_id = next(event["session_id"] for event in events if event["type"] == "session")
        matches = await asyncio.to_thread(memory.search, "Schools should ban smartphones during the school day.")
        assert any(match["id"] == session_id for match in matches)
        saved = await asyncio.to_thread(memory.get, session_id)
        assert saved["complete"] and saved["data"]["questionFeedback"]
        assert journal.get(session_id)["status"] == "complete"
        print("COORDINATOR_LIVE_AND_VECTOR_RETRIEVAL_PASSED", flush=True)
    finally:
        memory.close()
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
