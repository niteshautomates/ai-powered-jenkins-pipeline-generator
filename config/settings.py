# config/settings.py

import os
from dotenv import load_dotenv

load_dotenv()


# The installed Langfuse v2 SDK reads LANGFUSE_HOST; mirror the newer LANGFUSE_BASE_URL into it.
if os.getenv("LANGFUSE_BASE_URL") and not os.getenv("LANGFUSE_HOST"):
    os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]


class Settings:
    """Application settings. Model ids are overridable per task via env."""

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

    # Langfuse (optional - tracing is skipped when keys are missing)
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
    LANGFUSE_HOST = (
        os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    )

    APP_ENV = os.getenv("APP_ENV", "development")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Model routing: cheap model for routine tool-calling, strong model for review
    MODEL_PLANNER = os.getenv("MODEL_PLANNER", "claude-haiku-5-5")
    MODEL_VISION = os.getenv("MODEL_VISION", "claude-sonnet-5-5")
    MODEL_GENERATOR = os.getenv("MODEL_GENERATOR", "claude-sonnet-5-5")
    MODEL_REVIEWER = os.getenv("MODEL_REVIEWER", "claude-opus-5-5")

    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))
    MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "12"))

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)

    def validate(self) -> None:
        if not self.ANTHROPIC_API_KEY or self.ANTHROPIC_API_KEY.startswith("your_"):
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")


settings = Settings()
