"""Redis helpers: shared client, per-client rate limiting, whole-run cache."""
from __future__ import annotations

import hashlib
import json
import time

import redis

from .config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings().redis_url, decode_responses=True, socket_timeout=5,
                                       socket_connect_timeout=5, health_check_interval=30)
    return _client


def rate_limited(client_id: str, bucket: str, limit_per_min: int) -> tuple[bool, int]:
    """Fixed one-minute window per client and bucket. Returns (limited, seconds_until_reset)."""
    window = int(time.time() // 60)
    key = f"rl:{bucket}:{client_id}:{window}"
    r = get_redis()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 70)
    count, _ = pipe.execute()
    return count > limit_per_min, 60 - int(time.time() % 60)


def request_hash(payload: dict, prompt_versions: dict, index_version: str) -> str:
    body = json.dumps({"r": payload, "p": prompt_versions, "i": index_version}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def run_cache_get(key: str) -> dict | None:
    raw = get_redis().get(f"runcache:{key}")
    return json.loads(raw) if raw else None


def run_cache_put(key: str, result: dict) -> None:
    get_redis().set(f"runcache:{key}", json.dumps(result, default=str), ex=settings().run_cache_ttl)


def index_version() -> str:
    return get_redis().get("index:version") or "none"
