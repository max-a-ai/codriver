"""Turning rate readings into the lights on the status tab.

Two things decide a sensor's colour: is anything publishing it, and is it
publishing at the rate it is supposed to. Nothing else. A camera at 12 Hz is as
red as a camera that is off, because a recording made with it is equally
unusable.

Criticality does not change a sensor's own colour, only whether it drags its
block down with it. The front-centre fisheye and the two bumper lidars are
listed because they exist, not because a demo waits on them.

The GNSS is the reason a rate check is worth building. It comes up at 1 Hz after
the computer is restarted and stays there until somebody sets it; once set it
holds for the rest of the session. So there is exactly one moment where it is
wrong, right at the start, which is the moment nobody is looking.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal

from .config import Config, SensorSpec
from .ros import RateBackend, RateReading

#: unknown  not probed yet
#: ok       publishing at the expected rate
#: bad      absent, silent, or off-rate
SensorState = Literal["unknown", "ok", "bad"]


@dataclass(frozen=True)
class SensorStatus:
    name: str
    kind: str
    topic: str
    expected_hz: float
    critical: bool
    state: SensorState
    hz: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class BlockStatus:
    """One box in the status tab: the cameras, the lidars, or the GNSS."""

    kind: str
    label: str
    sensors: list[SensorStatus]
    #: Green only when every sensor that matters is green.
    state: SensorState
    #: How many of the sensors that matter are good, out of how many.
    ok_count: int
    required_count: int


#: Order matters: this is the order the boxes are stacked down the status tab.
#: GNSS goes first because it is the one that comes up wrong after a computer
#: restart and is otherwise easy to miss.
_BLOCK_LABELS = {"gnss": "GNSS", "camera": "Cameras", "lidar": "Lidar"}


def _verdict(
    spec: SensorSpec, reading: RateReading | None
) -> tuple[SensorState, float | None, str]:
    if reading is None:
        return "unknown", None, "not checked yet"
    if not reading.present:
        return "bad", None, reading.error or "no publisher"
    if reading.hz is None:
        return "bad", None, reading.error or "publishing nothing"
    if spec.rate_ok(reading.hz):
        return "ok", reading.hz, ""
    return "bad", reading.hz, f"{reading.hz:.1f} Hz, expected {spec.expected_hz:.0f} Hz"


def evaluate(spec: SensorSpec, reading: RateReading | None) -> SensorStatus:
    state, hz, detail = _verdict(spec, reading)
    return SensorStatus(
        name=spec.name,
        kind=spec.kind,
        topic=spec.topic,
        expected_hz=spec.expected_hz,
        critical=spec.critical,
        state=state,
        hz=hz,
        detail=detail,
    )


def group_into_blocks(statuses: list[SensorStatus]) -> list[BlockStatus]:
    blocks: list[BlockStatus] = []
    for kind, label in _BLOCK_LABELS.items():
        members = [s for s in statuses if s.kind == kind]
        if not members:
            continue
        required = [s for s in members if s.critical]
        ok = [s for s in required if s.state == "ok"]
        if any(s.state == "unknown" for s in required):
            state: SensorState = "unknown"
        elif len(ok) == len(required):
            state = "ok"
        else:
            state = "bad"
        blocks.append(
            BlockStatus(
                kind=kind,
                label=label,
                sensors=members,
                state=state,
                ok_count=len(ok),
                required_count=len(required),
            )
        )
    return blocks


class SensorMonitor:
    """Runs sweeps in the background and hands out the most recent result.

    A sweep measures every topic at once and takes `probe_seconds`, so the UI
    must never wait on one. It asks for a refresh, keeps rendering the previous
    numbers with a "checking" marker, and picks up the new ones when they land.
    """

    def __init__(self, config: Config, backend: RateBackend) -> None:
        self.config = config
        self.backend = backend
        self._lock = threading.Lock()
        self._readings: dict[str, RateReading] = {}
        self._last_checked: float | None = None
        self._sweeping = False
        self._error: str | None = None
        self._stop = threading.Event()
        self._timer: threading.Thread | None = None

    # --- sweeps ---

    def refresh_async(self) -> bool:
        """Kick off a sweep. False if one was already running."""
        with self._lock:
            if self._sweeping:
                return False
            self._sweeping = True
        threading.Thread(target=self._sweep, name="sensor-sweep", daemon=True).start()
        return True

    def _sweep(self) -> None:
        topics = [s.topic for s in self.config.sensors]
        error: str | None = None
        readings: dict[str, RateReading] = {}
        try:
            readings = self.backend.measure(topics, self.config.probe_seconds)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            if readings:
                self._readings = readings
            self._error = error
            self._last_checked = time.time()
            self._sweeping = False

    def start_auto_refresh(self) -> None:
        """Sweep on a timer, if the config asked for it."""
        if self.config.auto_refresh_seconds <= 0 or self._timer is not None:
            return

        def loop() -> None:
            while not self._stop.wait(self.config.auto_refresh_seconds):
                self.refresh_async()

        self._timer = threading.Thread(target=loop, name="sensor-auto", daemon=True)
        self._timer.start()

    def shutdown(self) -> None:
        self._stop.set()

    # --- reading ---

    def snapshot(self) -> tuple[list[BlockStatus], dict[str, object]]:
        with self._lock:
            readings = dict(self._readings)
            meta: dict[str, object] = {
                "backend": self.backend.name,
                "sweeping": self._sweeping,
                "last_checked": self._last_checked,
                "probe_seconds": self.config.probe_seconds,
                "error": self._error,
            }
        statuses = [evaluate(spec, readings.get(spec.topic)) for spec in self.config.sensors]
        return group_into_blocks(statuses), meta
