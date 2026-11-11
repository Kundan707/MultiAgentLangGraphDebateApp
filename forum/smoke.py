"""One live paid debate: python -m forum.smoke. Never prints credentials."""
import asyncio
import json
from .claude import ClaudeClient
from .config import Settings
from .debate import DebateRunner


async def main():
    settings = Settings.from_env()
    if not settings.api_key:
        raise SystemExit("ANTHROPIC_API_KEY is missing.")
    client = ClaudeClient(settings)
    def report(event):
        safe = {key: event[key] for key in ("type", "role", "winner", "scores") if key in event}
        print(json.dumps(safe), flush=True)
    try:
        async with asyncio.timeout(settings.debate_timeout):
            await DebateRunner(client).run("Schools should ban smartphones during the school day.", report)
        print("PYTHON_LIVE_SMOKE_PASSED")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
