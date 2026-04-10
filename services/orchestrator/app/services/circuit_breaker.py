"""Circuit breaker implementation for downstream service calls.

States: CLOSED → OPEN (after N consecutive failures)
        → HALF_OPEN (after cb_timeout_sec)
        → CLOSED (on success in HALF_OPEN)
        → OPEN (on failure in HALF_OPEN)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from app.config import settings
from app.utils.logger import logger


class CircuitBreakerOpenError(Exception):
    """Raised when a call is attempted while the circuit is OPEN."""


class CircuitBreaker:
    """Thread-safe async circuit breaker."""

    STATE_CLOSED = "CLOSED"
    STATE_OPEN = "OPEN"
    STATE_HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_sec: Optional[int] = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout_sec = timeout_sec if timeout_sec is not None else settings.cb_timeout_sec
        self.state = self.STATE_CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Wrap an async function call with circuit breaker logic."""
        async with self._lock:
            if self.state == self.STATE_OPEN:
                elapsed = time.monotonic() - (self.last_failure_time or 0)
                if elapsed >= self.timeout_sec:
                    self.state = self.STATE_HALF_OPEN
                    logger.info(
                        "Circuit breaker half-open",
                        layer="service",
                        circuit=self.name,
                    )
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit '{self.name}' is OPEN. Retry after {self.timeout_sec}s."
                    )

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                if self.state == self.STATE_HALF_OPEN:
                    self._reset()
                    logger.info(
                        "Circuit breaker closed (recovered)",
                        layer="service",
                        circuit=self.name,
                    )
            return result

        except CircuitBreakerOpenError:
            raise

        except Exception as exc:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.monotonic()
                if self.state == self.STATE_HALF_OPEN or self.failure_count >= self.failure_threshold:
                    self.state = self.STATE_OPEN
                    logger.warning(
                        "Circuit breaker opened",
                        layer="service",
                        circuit=self.name,
                        failure_count=self.failure_count,
                    )
            raise

    def _reset(self) -> None:
        self.state = self.STATE_CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    @property
    def is_open(self) -> bool:
        return self.state == self.STATE_OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == self.STATE_CLOSED
