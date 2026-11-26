import os
from pathlib import Path


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres@localhost:5432/algojudge")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    JUDGE0_URL = os.getenv("JUDGE0_URL", "http://localhost:2358").rstrip("/")
    JUDGE0_AUTH_TOKEN = os.getenv("JUDGE0_AUTH_TOKEN", "")
    JUDGE0_PYTHON_ID = int(os.getenv("JUDGE0_PYTHON_ID", "71"))

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

    JWT_HOURS = 8
    SUBMIT_COOLDOWN_SECONDS = 10
    MAX_CODE_BYTES = 64 * 1024
    LEADERBOARD_SIZE = int(os.getenv("LEADERBOARD_SIZE", "10"))

    STORAGE_DIR = os.getenv("STORAGE_DIR", str(Path(__file__).parent.parent / "storage"))
    MAX_FILE_BYTES = 20 * 1024 * 1024
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024
    PUB_LIMIT = 20
    PRI_LIMIT = 5
    BOARD_SIZE = 50
