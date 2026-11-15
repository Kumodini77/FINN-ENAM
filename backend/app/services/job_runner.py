"""Reusable bounded-retry + timeout execution helper — Phase 12A's generic job-
execution mechanism, intended for any future background job (document discovery,
announcement monitoring, ingestion, alert evaluation), not just market data.

Pairs with app.repositories.job_runs.JobRunRepository, which handles the durable
state half (run IDs, status, duplicate-run prevention, crash recovery). This module
is the pure-execution half: retrying one unit of work with exponential backoff, and
enforcing a wall-clock timeout per attempt via a worker thread (yfinance/HTTP calls
are synchronous, so a thread-based timeout is the only way to actually bound one
without blocking the whole process on a hung call).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Callable, TypeVar

logger = logging.getLogger("finn.services.job_runner")

T = TypeVar("T")


class RetryExhaustedError(Exception):
    """Raised when a unit of work still fails after exhausting its retry budget.
    Wraps the last underlying exception so the caller can report a real cause."""

    def __init__(self, attempts: int, last_error: Exception):
        super().__init__(f"Failed after {attempts} attempt(s): {last_error}")
        self.attempts = attempts
        self.last_error = last_error


@dataclass
class RetryOutcome:
    value: object | None
    attempts: int
    succeeded: bool
    last_error: Exception | None = None


def run_with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 2,
    timeout_seconds: int = 15,
    backoff_base_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> RetryOutcome:
    """Runs fn() with up to `max_retries` retries (so max_retries=2 means up to 3
    total attempts), bounded exponential backoff between attempts
    (backoff_base_seconds * 2**attempt), and a hard per-attempt timeout enforced via
    a worker thread. Never raises — returns a RetryOutcome so callers can record a
    per-unit failure without the whole batch job's loop being interrupted (a
    one-company failure must not stop the other 19)."""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(fn)
                try:
                    value = future.result(timeout=timeout_seconds)
                    return RetryOutcome(value=value, attempts=attempt + 1, succeeded=True)
                except FutureTimeoutError as exc:
                    last_error = TimeoutError(f"Timed out after {timeout_seconds}s")
                    logger.warning("job_runner: attempt %d timed out after %ds", attempt + 1, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - genuinely any failure is retryable here
            last_error = exc
            logger.warning("job_runner: attempt %d failed: %s", attempt + 1, exc)

        if attempt < max_retries:
            delay = backoff_base_seconds * (2**attempt)
            sleep(delay)

    return RetryOutcome(value=None, attempts=max_retries + 1, succeeded=False, last_error=last_error)


__all__ = ["run_with_retry", "RetryOutcome", "RetryExhaustedError"]
