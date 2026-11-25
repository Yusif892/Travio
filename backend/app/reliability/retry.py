"""Per-task retry counters, exhaustion, and booking-retry protection (TRV-05)."""
import random

from .contracts import RetryConfig
from .errors import RetryExhaustedError


class RetryTracker:
    """Counts attempts per task ID (not globally)."""

    def __init__(self, config: RetryConfig | None = None):
        self.config = config or RetryConfig()
        self._attempts: dict[str, int] = {}

    def attempts(self, task_id: str) -> int:
        return self._attempts.get(task_id, 0)

    def record_attempt(self, task_id: str) -> int:
        self._attempts[task_id] = self.attempts(task_id) + 1
        return self._attempts[task_id]

    def exhausted(self, task_id: str) -> bool:
        return self.attempts(task_id) >= self.config.max_attempts

    def backoff(self, attempt: int) -> float:
        """Exponential backoff with full jitter."""
        cap = min(self.config.backoff_max, self.config.backoff_base * 2 ** (attempt - 1))
        return random.uniform(0, cap)


class IdempotencyStore:
    """A retry with the same key returns the first result instead of booking twice."""

    def __init__(self):
        self._results: dict[str, object] = {}

    def get(self, key: str):
        return self._results.get(key)

    def has(self, key: str) -> bool:
        return key in self._results

    def put(self, key: str, value) -> None:
        self._results[key] = value


def fallback_for(err: RetryExhaustedError) -> dict:
    """Clear fallback when retries run out: partial result + escalation."""
    return {
        "status": "failed",
        "task_id": err.task_id,
        "attempts": err.attempts,
        "message": "We couldn't complete this step. Returning a partial result.",
        "escalate": True,
    }
