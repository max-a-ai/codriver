"""Invented readings, so the whole panel can be built and demoed off the car.

The default scenario is not "everything is fine". It reproduces the two faults
this panel exists to make obvious, so the UI can be judged in the state that
matters: the GNSS has dropped to 1 Hz and one camera is off.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Sequence

from .backend import RateReading

#: scenario -> topic substring -> behaviour
_SCENARIOS: dict[str, dict[str, str]] = {
    "healthy": {},
    "typical": {
        "gnss": "slow",
        "camera_front_center": "absent",
    },
    "degraded": {
        "gnss": "slow",
        "camera_front_center": "absent",
        "camera_right_back": "absent",
        "lidar_roof_left": "slow",
        "lidar_bumper_back": "absent",
    },
}


def _nominal_hz(topic: str) -> float:
    if "camera" in topic:
        return 20.0
    if "lidar" in topic:
        return 10.0
    return 20.0


class MockBackend:
    """Deterministic fake rates with a little jitter so the UI looks alive."""

    name = "mock"

    def __init__(self, scenario: str | None = None) -> None:
        self.scenario = scenario or os.environ.get("CODRIVER_MOCK_SCENARIO", "typical")
        if self.scenario not in _SCENARIOS:
            known = ", ".join(sorted(_SCENARIOS))
            raise ValueError(f"unknown mock scenario {self.scenario!r} (known: {known})")

    def available(self) -> bool:
        return True

    def measure(self, topics: Sequence[str], duration: float) -> dict[str, RateReading]:
        # Mimic the cost of a real sweep so the UI's pending state is visible,
        # but never make a developer wait the full window.
        time.sleep(min(duration, 0.4))
        faults = _SCENARIOS[self.scenario]
        return {topic: self._reading(topic, faults, duration) for topic in topics}

    def _reading(self, topic: str, faults: dict[str, str], duration: float) -> RateReading:
        fault = next((f for key, f in faults.items() if key in topic), None)
        if fault == "absent":
            return RateReading.missing(topic, error="no publisher (mock)")

        nominal = _nominal_hz(topic)
        # The real GNSS failure is a hard fallback to 1 Hz, not a slow drift.
        hz = 1.0 if fault == "slow" and "gnss" in topic else nominal
        if fault == "slow" and "gnss" not in topic:
            hz = nominal * 0.55
        # A wobble keyed to the topic name and the clock: stable enough to read,
        # moving enough to show that the panel is really polling.
        jitter = math.sin(time.monotonic() / 3.0 + len(topic)) * 0.015 * hz
        hz = max(0.0, hz + jitter)
        return RateReading(topic=topic, present=True, hz=hz, samples=int(hz * duration))
