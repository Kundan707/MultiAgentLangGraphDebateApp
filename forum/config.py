"""Local configuration. Secrets never enter responses or browser assets."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    model: str = "claude-sonnet-5"
    debate_timeout: float = 900.0
    max_concurrent: int = 2
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env.local", override=False)
        return cls(
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
            allowed_origins=tuple(filter(None, os.getenv("FORUM_ALLOWED_ORIGINS", "").split(","))),
        )
