import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Postgres/Tiger Data in Docker; SQLite fallback for quick local dev.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///arena.db")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# "mock" replays reference solutions so the arena works without an API key.
ALLOWED_MODELS = [DEFAULT_MODEL, "gemini-3.1-flash-lite", "mock"]

# Empty PISTON_URL runs code in a local subprocess (dev only, not sandboxed).
PISTON_URL = os.getenv("PISTON_URL", "").rstrip("/")
PISTON_PYTHON_VERSION = os.getenv("PISTON_PYTHON_VERSION", "3.12.0")

BETTING_SECONDS = int(os.getenv("BETTING_SECONDS", "20"))
CHALLENGES_PER_MATCH = int(os.getenv("CHALLENGES_PER_MATCH", "3"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))
MM_WAIT_SECONDS = int(os.getenv("MM_WAIT_SECONDS", "15"))
MAX_PROMPT_CHARS = 2000
MAX_SKILLS = 5
STARTING_POINTS = 1000
