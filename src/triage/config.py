"""Runtime configuration. Everything environment-specific comes from env vars (see .env.example)."""
import os
from dataclasses import dataclass, field


def _req(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable {name} (see .env.example)")
    return value


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    service_name: str = field(default_factory=lambda: _opt("SERVICE_NAME", "triage"))
    log_level: str = field(default_factory=lambda: _opt("LOG_LEVEL", "INFO"))

    redis_url: str = field(default_factory=lambda: _req("REDIS_URL"))
    database_url: str = field(default_factory=lambda: _req("DATABASE_URL"))
    chroma_host: str = field(default_factory=lambda: _req("CHROMA_HOST"))
    chroma_port: int = field(default_factory=lambda: _int("CHROMA_PORT", 8000))
    chroma_collection: str = field(default_factory=lambda: _opt("CHROMA_COLLECTION", "kerc_corpus"))
    gateway_url: str = field(default_factory=lambda: _req("LLM_GATEWAY_URL"))
    otlp_endpoint: str = field(default_factory=lambda: _opt("OTEL_EXPORTER_OTLP_ENDPOINT"))

    embed_model: str = field(default_factory=lambda: _req("EMBED_MODEL"))
    embed_cache_dir: str = field(default_factory=lambda: _opt("EMBED_CACHE_DIR", "/models"))
    corpus_dir: str = field(default_factory=lambda: _opt("CORPUS_DIR", "/app/corpus"))
    prompts_dir: str = field(default_factory=lambda: _opt("PROMPTS_DIR", "/app/prompts"))

    research_prompt_version: str = field(default_factory=lambda: _opt("RESEARCH_PROMPT_VERSION", "v2"))
    intake_prompt_version: str = field(default_factory=lambda: _opt("INTAKE_PROMPT_VERSION", "v1"))
    verifier_prompt_version: str = field(default_factory=lambda: _opt("VERIFIER_PROMPT_VERSION", "v1"))

    max_steps: int = field(default_factory=lambda: _int("AGENT_MAX_STEPS", 12))
    max_tool_calls: int = field(default_factory=lambda: _int("AGENT_MAX_TOOL_CALLS", 10))
    max_wall_seconds: float = field(default_factory=lambda: _float("AGENT_MAX_WALL_SECONDS", 90))
    max_verify_attempts: int = field(default_factory=lambda: _int("MAX_VERIFY_ATTEMPTS", 2))
    run_deadline_seconds: float = field(default_factory=lambda: _float("RUN_DEADLINE_SECONDS", 240))
    tool_timeout_seconds: float = field(default_factory=lambda: _float("TOOL_TIMEOUT_SECONDS", 10))
    gateway_client_timeout: float = field(default_factory=lambda: _float("GATEWAY_CLIENT_TIMEOUT_SECONDS", 75))
    require_modifier_search: bool = field(default_factory=lambda: _bool("REQUIRE_MODIFIER_SEARCH", True))

    run_cache_enabled: bool = field(default_factory=lambda: _bool("RUN_CACHE_ENABLED", True))
    run_cache_ttl: int = field(default_factory=lambda: _int("RUN_CACHE_TTL_SECONDS", 86400))
    retrieval_cache_enabled: bool = field(default_factory=lambda: _bool("RETRIEVAL_CACHE_ENABLED", True))
    retrieval_cache_ttl: int = field(default_factory=lambda: _int("RETRIEVAL_CACHE_TTL_SECONDS", 86400))
    rate_limit_submit_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_SUBMIT_PER_MIN", 20))
    rate_limit_read_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_READ_PER_MIN", 600))
    live_score_sample_rate: float = field(default_factory=lambda: _float("LIVE_SCORE_SAMPLE_RATE", 0.25))


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


class GatewaySettings:
    """Only the llm-gateway reads provider configuration; agents never see keys or model ids."""

    def __init__(self) -> None:
        self.base_url = _req("LLM_BASE_URL")
        self.api_key = _opt("LLM_API_KEY")
        self.model = _req("LLM_MODEL")
        self.fallback_base_url = _opt("LLM_FALLBACK_BASE_URL")
        self.fallback_api_key = _opt("LLM_FALLBACK_API_KEY")
        self.fallback_model = _opt("LLM_FALLBACK_MODEL")
        self.fallback2_base_url = _opt("LLM_FALLBACK2_BASE_URL")
        self.fallback2_api_key = _opt("LLM_FALLBACK2_API_KEY")
        self.fallback2_model = _opt("LLM_FALLBACK2_MODEL")
        self.price_in_per_mtok = _float("LLM_PRICE_INPUT_PER_MTOK", 0.0)
        self.price_out_per_mtok = _float("LLM_PRICE_OUTPUT_PER_MTOK", 0.0)
        self.call_timeout = _float("LLM_CALL_TIMEOUT_SECONDS", 30)
        self.max_retries = _int("LLM_MAX_RETRIES", 3)
        self.backoff_base = _float("LLM_BACKOFF_BASE_SECONDS", 0.5)
        self.backoff_max = _float("LLM_BACKOFF_MAX_SECONDS", 8)
        self.breaker_fail_threshold = _int("BREAKER_FAILURE_THRESHOLD", 5)
        self.breaker_reset_seconds = _float("BREAKER_RESET_SECONDS", 30)
        self.json_mode = _bool("LLM_JSON_MODE", True)
        self.fault_injection = _bool("ENABLE_FAULT_INJECTION", False)
        self.max_tokens_cap = _int("LLM_MAX_TOKENS_CAP", 1200)
        self.reasoning_effort = _opt("LLM_REASONING_EFFORT")
        self.rate_limit_wait = _float("LLM_RATE_LIMIT_WAIT_SECONDS", 90)
