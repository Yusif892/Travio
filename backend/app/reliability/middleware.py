"""Middleware around every tool call (TRV-07):
allowlist -> before hook -> timeout -> validate output -> retry/backoff -> trace log -> PII redaction.
"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable

from pydantic import BaseModel, ValidationError 
from .errors import (RetryExhaustedError, SchemaValidationError, ToolFailureError,
                     ToolNotAllowedError, ToolTimeoutError)
from .retry import IdempotencyStore, RetryTracker
from typing import Any, Callable, TypeVar

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger("reliability.trace")

# ---- PII redaction ----
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def redact_pii(text: str) -> str:
    return _PHONE.sub("[PHONE]", _EMAIL.sub("[EMAIL]", text))


# ---- Tool allowlists: agent -> allowed tools ----
TOOL_ALLOWLIST: dict[str, set[str]] = {
    "planner": {"search_places", "get_opening_hours"},
    "booking": {"book_hotel", "book_flight"},
}


def check_allowed(agent: str, tool: str) -> None:
    if tool not in TOOL_ALLOWLIST.get(agent, set()):
        raise ToolNotAllowedError(f"Agent '{agent}' may not call '{tool}'")


def _run_with_timeout(fn: Callable, timeout_s: float, **kwargs):
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, **kwargs).result(timeout=timeout_s)
    except FuturesTimeout:
        raise ToolTimeoutError(f"Tool timed out after {timeout_s}s")
    finally:
        pool.shutdown(wait=False)

def call_tool(
    *,
    agent: str,
    tool: str,
    fn: Callable[..., Any],
    args: dict,
    output_model: type[T],
    task_id: str,
    tracker: RetryTracker,
    idempotency_key: str | None = None,
    store: IdempotencyStore | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:

    check_allowed(agent, tool)

    # Booking-retry protection: same key -> return the earlier result
    if idempotency_key and store and store.has(idempotency_key):
        cached_data = store.get(idempotency_key)
    # If it's a dict, validate it against the output model:
        return output_model.model_validate(cached_data)

    last_error: Exception | None = None
    while not tracker.exhausted(task_id):
        attempt = tracker.record_attempt(task_id)
        start = time.monotonic()
        try:
            raw = _run_with_timeout(fn, tracker.config.timeout_s, **args)
            try:
                result = output_model.model_validate(raw)
            except ValidationError as e:
                raise SchemaValidationError(str(e)) from e
            log.info("task=%s tool=%s attempt=%d ok duration=%.3fs",
                     task_id, tool, attempt, time.monotonic() - start)
            if idempotency_key and store:
                store.put(idempotency_key, result)
            return result
        except (ToolTimeoutError, SchemaValidationError) as e:
            last_error = e
        except Exception as e:  # central error handling -> typed error
            last_error = ToolFailureError(str(e))
        log.warning("task=%s tool=%s attempt=%d failed error=%s",
                    task_id, tool, attempt, redact_pii(str(last_error)))
        if not tracker.exhausted(task_id):
            sleep(tracker.backoff(attempt))

    raise RetryExhaustedError(task_id, tracker.attempts(task_id), last_error)
