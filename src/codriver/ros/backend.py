"""The interface every rate backend implements, plus backend selection."""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..config import Config


@dataclass(frozen=True)
class RateReading:
    """What one probe learned about one topic."""

    topic: str
    #: A publisher for this topic exists. False means nothing is advertising it,
    #: which reads as "the sensor is off or its driver died" rather than "slow".
    present: bool
    #: Measured publish rate. None when no rate could be established, either
    #: because the topic is absent or because too few messages arrived to divide
    #: by an interval.
    hz: float | None
    #: Messages seen during the window. Useful for telling "one message, no rate"
    #: apart from "silence".
    samples: int = 0
    error: str | None = None

    @classmethod
    def missing(cls, topic: str, error: str | None = None) -> RateReading:
        return cls(topic=topic, present=False, hz=None, samples=0, error=error)


@runtime_checkable
class RateBackend(Protocol):
    """Measures the publish rate of a set of topics."""

    name: str

    def available(self) -> bool:
        """Whether this backend can run here at all."""

    def measure(self, topics: Sequence[str], duration: float) -> dict[str, RateReading]:
        """Observe every topic for `duration` seconds. One reading per topic."""


def ros_environment_present() -> bool:
    """A sourced ROS 2 environment, near enough. ROS_DISTRO is set by every
    `setup.bash`, and `ros2` on PATH rules out a stale variable in a shell that
    never had the install."""
    return bool(os.environ.get("ROS_DISTRO")) and shutil.which("ros2") is not None


def resolve_backend(config: Config) -> RateBackend:
    """Pick the backend named in the config, or the best one that works here.

    `auto` is the deployment-friendly choice: the same config file runs against
    real sensors on the car and against invented ones on a laptop.
    """
    from .bag import BagBackend
    from .cli import Ros2CliBackend
    from .live import RclpyBackend
    from .mock import MockBackend

    choice = config.ros_backend
    if choice == "mock":
        return MockBackend()
    if choice == "rclpy":
        return RclpyBackend(config.probe_seconds)
    if choice == "ros2cli":
        return Ros2CliBackend()
    if choice == "bag":
        return BagBackend(config.recordings_dir)
    # auto
    if ros_environment_present():
        live = RclpyBackend(config.probe_seconds)
        if live.available():
            return live
        return Ros2CliBackend()
    return MockBackend()
