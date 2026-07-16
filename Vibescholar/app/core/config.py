import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _positive_int(name: str, default: int) -> int:
    """Read a strictly positive integer from the environment."""
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(name: str, default: float) -> float:
    """Read a strictly positive floating-point value from the environment."""
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def _unit_interval(name: str, default: float) -> float:
    """Read a floating-point configuration constrained to zero through one."""
    value = float(os.getenv(name, str(default)))
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    """Read a floating-point value constrained to an inclusive range."""
    value = float(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _optional_int(name: str) -> int | None:
    """Read an optional integer, treating an absent or blank value as disabled."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return int(raw)


def _boolean(name: str, default: bool = False) -> bool:
    """Read an explicit boolean environment setting."""
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _provider_order() -> tuple[str, ...]:
    """Read a non-empty, unique provider precedence list."""
    raw = os.getenv("SEARCH_PROVIDER_ORDER", "openalex,semantic_scholar")
    providers = tuple(item.strip().casefold() for item in raw.split(",") if item.strip())
    if not providers:
        raise ValueError("SEARCH_PROVIDER_ORDER must contain at least one provider")
    if len(set(providers)) != len(providers):
        raise ValueError("SEARCH_PROVIDER_ORDER must not contain duplicates")
    return providers


def _csv_values(name: str, default: str = "") -> tuple[str, ...]:
    """Read a stable, unique CSV list while preserving configured spelling."""
    values: list[str] = []
    seen: set[str] = set()
    for raw_value in os.getenv(name, default).split(","):
        value = raw_value.strip()
        normalized = value.casefold()
        if value and normalized not in seen:
            seen.add(normalized)
            values.append(value)
    return tuple(values)


class Settings:
    PROJECT_NAME: str = "VibeScholar"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "2134763u46827163484wudyg3468r4")
    # Resolves DB path relative to project root so it works for any user
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(_project_root, 'vibescholar.db')}"
    )
    USE_MOCK: bool = os.getenv("USE_MOCK", "False").lower() == "true"

    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", "")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
    OPENROUTER_BASE_URL: str
    OPENROUTER_API_KEY: str
    OPENROUTER_MODEL: str
    OPENROUTER_ALLOWED_MODELS: tuple[str, ...]
    OPENROUTER_ALLOW_PAID_MODELS: bool
    EVIDENCE_EVALUATOR_BACKEND: str
    EVIDENCE_EVALUATOR_MAX_OUTPUT_TOKENS: int
    LLM_TIMEOUT_SECONDS: int = _positive_int("LLM_TIMEOUT_SECONDS", 50000) #para testes com qwen
    LLM_TEMPERATURE: float
    LLM_TOP_P: float
    LLM_FREQUENCY_PENALTY: float
    LLM_PRESENCE_PENALTY: float
    LLM_SEED: int | None
    LLM_DIAGNOSTIC_LOGGING: bool
    MAX_SEARCH_ROUNDS: int = _positive_int("MAX_SEARCH_ROUNDS", 3)
    MAX_TOOL_CALLS_PER_ROUND: int = _positive_int("MAX_TOOL_CALLS_PER_ROUND", 1)
    RESULTS_PER_PROVIDER: int = _positive_int("RESULTS_PER_PROVIDER", 10)
    EVIDENCE_BATCH_SIZE: int = _positive_int("EVIDENCE_BATCH_SIZE", 5)
    TARGET_STRONG_EVIDENCE: int = _positive_int("TARGET_STRONG_EVIDENCE", 5)
    MAX_PARTIAL_EVIDENCE: int = _positive_int("MAX_PARTIAL_EVIDENCE", 3)
    EVIDENCE_CONFIDENCE_THRESHOLD: float = _unit_interval("EVIDENCE_CONFIDENCE_THRESHOLD", 0.75)
    INVALID_SENTENCE_CONFIDENCE: float = _unit_interval("INVALID_SENTENCE_CONFIDENCE", 0.75)
    SEARCH_SESSION_TTL_SECONDS: int = _positive_int("SEARCH_SESSION_TTL_SECONDS", 1800)
    MAX_IN_MEMORY_SEARCH_SESSIONS: int = _positive_int("MAX_IN_MEMORY_SEARCH_SESSIONS", 500)
    SEARCH_PROVIDER_ORDER: tuple[str, ...] = _provider_order()
    OPENALEX_BASE_URL: str = os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org")
    OPENALEX_API_KEY: str = os.getenv("OPENALEX_API_KEY", "")
    SEMANTIC_SCHOLAR_BASE_URL: str = os.getenv(
        "SEMANTIC_SCHOLAR_BASE_URL",
        "https://api.semanticscholar.org/graph/v1",
    )
    SEMANTIC_SCHOLAR_API_KEY: str = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    ACADEMIC_PROVIDER_TIMEOUT_SECONDS: float = _positive_float(
        "ACADEMIC_PROVIDER_TIMEOUT_SECONDS", 15.0
    )
    QUALIS_DATABASE_PATH: str

    def __init__(self) -> None:
        """Read inference controls when a settings instance is created."""
        self.LLM_TEMPERATURE = _bounded_float("LLM_TEMPERATURE", 0.1, 0.0, 2.0)
        self.LLM_TOP_P = _bounded_float("LLM_TOP_P", 0.9, 0.0, 1.0)
        self.LLM_FREQUENCY_PENALTY = _bounded_float(
            "LLM_FREQUENCY_PENALTY", 0.0, -2.0, 2.0
        )
        self.LLM_PRESENCE_PENALTY = _bounded_float(
            "LLM_PRESENCE_PENALTY", 0.0, -2.0, 2.0
        )
        self.LLM_SEED = _optional_int("LLM_SEED")
        self.LLM_DIAGNOSTIC_LOGGING = _boolean(
            "LLM_DIAGNOSTIC_LOGGING",
            False,
        )
        self.EVIDENCE_EVALUATOR_BACKEND = os.getenv(
            "EVIDENCE_EVALUATOR_BACKEND",
            "ollama",
        ).strip().casefold()
        self.OPENROUTER_BASE_URL = os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1",
        )
        self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
        self.OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")
        self.OPENROUTER_ALLOWED_MODELS = _csv_values("OPENROUTER_ALLOWED_MODELS")
        self.OPENROUTER_ALLOW_PAID_MODELS = (
            _boolean("OPENROUTER_ALLOW_PAID_MODELS", False)
            if self.EVIDENCE_EVALUATOR_BACKEND == "openrouter"
            else False
        )
        self.EVIDENCE_EVALUATOR_MAX_OUTPUT_TOKENS = _positive_int(
            "EVIDENCE_EVALUATOR_MAX_OUTPUT_TOKENS",
            2000,
        )
        self.QUALIS_DATABASE_PATH = os.getenv(
            "QUALIS_DATABASE_PATH",
            "data/qualis/qualis.sqlite3",
        ).strip()
        if not self.QUALIS_DATABASE_PATH:
            raise ValueError("QUALIS_DATABASE_PATH must not be empty")

    def __repr__(self) -> str:
        """Return a diagnostic representation that never includes secret values."""
        return (
            "Settings("
            f"PROJECT_NAME={self.PROJECT_NAME!r}, "
            f"OLLAMA_MODEL={self.OLLAMA_MODEL!r}, "
            f"OPENROUTER_MODEL={self.OPENROUTER_MODEL!r}, "
            "OLLAMA_API_KEY=<redacted>, OPENROUTER_API_KEY=<redacted>, "
            "OPENALEX_API_KEY=<redacted>, SEMANTIC_SCHOLAR_API_KEY=<redacted>)"
        )

settings = Settings()
