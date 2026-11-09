"""In-process publish/subscribe bus for live project activity.

The orchestrator publishes structured events as work progresses; the API
streams them to the frontend over Server-Sent Events. Subscribers are
per-project so a client only receives the activity it is watching.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncIterator


class EventBus:
    """Fan-out bus with bounded per-subscriber queues."""

    def __init__(self, max_queue: int = 500) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._max_queue = max_queue
        self._lock = asyncio.Lock()

    async def publish(self, project_id: str, event: dict[str, Any]) -> None:
        event.setdefault("at", datetime.now(timezone.utc).isoformat())
        async with self._lock:
            queues = list(self._subscribers.get(project_id, ()))
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the oldest so the newest state always arrives.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:  # noqa: BLE001 - best effort
                    pass

    async def subscribe(self, project_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._subscribers[project_id].add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event
                except asyncio.TimeoutError:
                    # Heartbeat keeps proxies and clients from timing out.
                    yield {"kind": "heartbeat", "at": datetime.now(timezone.utc).isoformat()}
        finally:
            async with self._lock:
                self._subscribers[project_id].discard(queue)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
