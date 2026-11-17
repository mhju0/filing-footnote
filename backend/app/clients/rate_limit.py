"""Request spacing for SEC EDGAR, which asks automated clients to stay at or under 10 requests
per second; this project holds to 5 per second (M1 audit)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

SEC_REQUESTS_PER_SECOND = 5


class RequestLimiter:
    """Spaces requests at least ``1 / per_second`` apart.

    Evenly spaced starts cap the average at ``per_second`` and any one-second window at
    ``per_second + 1`` requests, below SEC's ceiling of 10. ``clock`` and ``sleep`` are
    injectable so tests run on a fake clock.
    """

    def __init__(
        self,
        per_second: float = SEC_REQUESTS_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if per_second <= 0:
            raise ValueError("per_second must be positive")
        self._interval = 1.0 / per_second
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Return when the caller may send its request."""
        async with self._lock:
            now = self._clock()
            if self._next_allowed is not None and now < self._next_allowed:
                await self._sleep(self._next_allowed - now)
                now = max(self._clock(), self._next_allowed)
            self._next_allowed = now + self._interval

    async def on_request(self, request: httpx.Request) -> None:
        """httpx request hook: runs before every request, redirect hops included."""
        await self.wait()


def rate_limited_client(
    limiter: RequestLimiter,
    timeout: httpx.Timeout | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """An httpx client that waits on ``limiter`` before each request it sends."""
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout or httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
        event_hooks={"request": [limiter.on_request]},
    )
