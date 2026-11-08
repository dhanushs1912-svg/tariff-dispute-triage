"""Per-stage job locks so a re-queued or duplicated job never processes the same run stage twice."""
from .cache import get_redis

TTL = 300


def key(stage: str, run_id: str, attempt: int) -> str:
    return f"lock:{stage}:{run_id}:{attempt}"


def acquire(stage: str, run_id: str, attempt: int) -> bool:
    return bool(get_redis().set(key(stage, run_id, attempt), "1", nx=True, ex=TTL))


def release_all(run_id: str) -> None:
    r = get_redis()
    for k in r.scan_iter(f"lock:*:{run_id}:*"):
        r.delete(k)
