"""The activity log behind the panel's terminal.

Every action the panel takes lands here, whether somebody clicked it or
the language layer asked for it. One stream rather than two, because the
whole point of putting the model behind the panel's own actions is that
a person watching the screen can see everything it did. Two logs would
give the model somewhere to hide.

Events are grouped by `area`, which is a tab id, so the terminal can be
read the same way the panel is laid out.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from collections import deque
from typing import Any, Literal

#: How many events are kept. The terminal is a "what just happened"
#: view, not an audit trail; the per-process logs are where a long
#: history lives.
DEFAULT_LIMIT = 200

Level = Literal["info", "bad"]

#: Who asked for the action. Every event carries it, so a reader can
#: always tell a click from something the model did.
Source = Literal["click", "model", "panel"]


@dataclasses.dataclass(frozen=True)
class Event:
    """One thing that happened, phrased as verb + subject."""

    at: float
    area: str
    verb: str
    subject: str
    level: Level = "info"
    source: Source = "click"


class EventLog:
    """A bounded, thread-safe ring of events.

    Written from request threads and from the sweep, read by every poll,
    so every access takes the lock.
    """

    def __init__(self, limit: int = DEFAULT_LIMIT) -> None:
        self._events: deque[Event] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def add(
        self,
        area: str,
        verb: str,
        subject: str,
        level: Level = "info",
        source: Source = "click",
    ) -> None:
        event = Event(time.time(), area, verb, subject, level, source)
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> list[dict[str, Any]]:
        """Newest first, which is the order the terminal renders."""
        with self._lock:
            return [dataclasses.asdict(e) for e in reversed(self._events)]
