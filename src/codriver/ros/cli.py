"""Rate measurement by shelling out to `ros2 topic hz`.

Kept as a fallback for environments where rclpy cannot be imported from the
interpreter running the panel. Treat its numbers as a lower bound: on image and
point-cloud topics `ros2 topic hz` reports the rate it managed to deserialise,
not the rate the sensor published. Where the two backends disagree, the live
probe in `live.py` is right.

Newer ros2cli builds accept QoS overrides on `hz`, which removes the worst of
the disagreement. Whether this one does is discovered from its own `--help`
rather than assumed from the distro name.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Sequence
from functools import lru_cache

from .backend import RateReading

_AVERAGE_RATE = re.compile(r"average rate:\s*([0-9]+\.?[0-9]*)")

#: Time on top of the measurement window for `ros2 topic hz` to start up.
_STARTUP_GRACE = 4.0


@lru_cache(maxsize=1)
def _hz_supports_qos() -> bool:
    """Whether this `ros2 topic hz` accepts `--qos-reliability`."""
    try:
        out = subprocess.run(
            ["ros2", "topic", "hz", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "--qos-reliability" in (out.stdout + out.stderr)


def _topic_list() -> set[str]:
    try:
        out = subprocess.run(
            ["ros2", "topic", "list"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


class Ros2CliBackend:
    name = "ros2cli"

    def available(self) -> bool:
        return shutil.which("ros2") is not None

    def measure(self, topics: Sequence[str], duration: float) -> dict[str, RateReading]:
        advertised = _topic_list()
        results: dict[str, RateReading] = {}
        for topic in topics:
            if topic not in advertised:
                results[topic] = RateReading.missing(topic, error="not in `ros2 topic list`")
                continue
            results[topic] = self._measure_one(topic, duration)
        return results

    def _measure_one(self, topic: str, duration: float) -> RateReading:
        argv = ["ros2", "topic", "hz", topic]
        if _hz_supports_qos():
            # Sensor drivers publish best-effort; a reliable subscription simply
            # never matches them.
            argv += ["--qos-reliability", "best_effort", "--qos-durability", "volatile"]

        # `ros2 topic hz` never exits on its own, so the timeout is the control
        # flow: it runs for the window, gets killed, and we read what it printed.
        try:
            subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=duration + _STARTUP_GRACE,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            return self._parse(topic, _text(expired.stdout))
        except OSError as exc:
            return RateReading.missing(topic, error=f"cannot run ros2 topic hz: {exc}")
        # Exiting early means it gave up, usually "does not appear to be published yet".
        return RateReading(topic=topic, present=True, hz=None, error="no rate reported")

    def _parse(self, topic: str, stdout: str) -> RateReading:
        rates = _AVERAGE_RATE.findall(stdout)
        if not rates:
            return RateReading(
                topic=topic,
                present=True,
                hz=None,
                error="publisher advertised but no messages received",
            )
        return RateReading(topic=topic, present=True, hz=float(rates[-1]), samples=len(rates))


def _text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
