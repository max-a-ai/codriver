"""The rate probe to trust: subscribe, count, divide.

`ros2 topic hz` under-reports on exactly the topics this panel cares about, for
two reasons. It subscribes with a default reliable QoS, which never matches a
sensor driver publishing best-effort, so it either sees nothing or sees a
filtered subset. And it deserialises every message in Python, which cannot keep
up with 20 Hz of camera frames or an OS2 sweep, so it counts what it managed to
process rather than what arrived.

This module avoids both. It reads each publisher's advertised QoS and matches
it, and it subscribes with `raw=True`, so messages are counted as opaque byte
buffers and never deserialised. The rate comes from the interval between the
first and last message actually seen, not from the nominal window, so a probe
that starts mid-frame is not biased low.

It runs as a short-lived child process (`python -m codriver.ros.live`), for two
reasons: an rclpy context living inside the web server is a lifecycle problem
nobody needs, and a broken ROS environment should fail one sweep rather than
take the panel down with it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .backend import RateReading

#: Seconds spent letting DDS discovery settle before subscribing. Without it the
#: graph is still empty and every topic looks absent.
DISCOVERY_SECONDS = 1.0

#: Headroom on top of the measurement window before the child is killed.
_SUBPROCESS_GRACE = 20.0


def rclpy_importable() -> bool:
    try:
        return importlib.util.find_spec("rclpy") is not None
    except (ImportError, ValueError):  # pragma: no cover - odd interpreter states
        return False


class RclpyBackend:
    """Runs the probe below in a child process and parses its JSON."""

    name = "rclpy"

    def __init__(self, probe_seconds: float = 2.0) -> None:
        self.probe_seconds = probe_seconds

    def available(self) -> bool:
        return rclpy_importable()

    def measure(self, topics: Sequence[str], duration: float) -> dict[str, RateReading]:
        if not topics:
            return {}
        argv = [
            sys.executable,
            "-m",
            "codriver.ros.live",
            "--duration",
            str(duration),
            *topics,
        ]
        # Keep the package importable in the child whether the app was installed
        # or is running straight from the source tree.
        src_root = str(Path(__file__).resolve().parents[2])
        env = {**_child_env(), "PYTHONPATH": _prepend_path(src_root)}
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=duration + DISCOVERY_SECONDS + _SUBPROCESS_GRACE,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _all_failed(topics, "rclpy probe timed out")
        except OSError as exc:
            return _all_failed(topics, f"cannot start rclpy probe: {exc}")

        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            return _all_failed(topics, detail[-1] if detail else "rclpy probe failed")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return _all_failed(topics, "rclpy probe returned invalid JSON")
        return _readings_from(payload, topics)


def _child_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def _prepend_path(entry: str) -> str:
    import os

    existing = os.environ.get("PYTHONPATH", "")
    return f"{entry}{os.pathsep}{existing}" if existing else entry


def _all_failed(topics: Sequence[str], error: str) -> dict[str, RateReading]:
    return {topic: RateReading.missing(topic, error=error) for topic in topics}


def _readings_from(payload: Any, topics: Sequence[str]) -> dict[str, RateReading]:
    if not isinstance(payload, dict):
        return _all_failed(topics, "rclpy probe returned an unexpected payload")
    results: dict[str, RateReading] = {}
    for topic in topics:
        item = payload.get(topic)
        if not isinstance(item, dict):
            results[topic] = RateReading.missing(topic, error="topic missing from probe result")
            continue
        hz = item.get("hz")
        results[topic] = RateReading(
            topic=topic,
            present=bool(item.get("present", False)),
            hz=float(hz) if isinstance(hz, (int, float)) else None,
            samples=int(item.get("samples", 0)),
            error=item.get("error"),
        )
    return results


# --- child process ----------------------------------------------------------


class _Counter:
    """First and last arrival plus a count. That is the whole measurement."""

    __slots__ = ("count", "first", "last")

    def __init__(self) -> None:
        self.count = 0
        self.first = 0.0
        self.last = 0.0

    def tick(self) -> None:
        now = time.monotonic()
        if self.count == 0:
            self.first = now
        self.last = now
        self.count += 1

    def hz(self) -> float | None:
        # n messages span n-1 intervals. Dividing by the requested window instead
        # would report low whenever the window opens just after a frame.
        if self.count < 2:
            return None
        span = self.last - self.first
        return (self.count - 1) / span if span > 0 else None


def _probe(topics: Sequence[str], duration: float) -> dict[str, dict[str, Any]]:
    """Subscribe to every topic at once and count what arrives. Needs rclpy."""
    import rclpy
    from rclpy.qos import HistoryPolicy, QoSProfile
    from rosidl_runtime_py.utilities import get_message

    rclpy.init(args=None)
    try:
        node = rclpy.create_node("codriver_rate_probe")
        try:
            deadline = time.monotonic() + DISCOVERY_SECONDS
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.05)

            results: dict[str, dict[str, Any]] = {}
            counters: dict[str, _Counter] = {}
            keep_alive: list[Any] = []

            for topic in topics:
                publishers = node.get_publishers_info_by_topic(topic)
                if not publishers:
                    results[topic] = {
                        "present": False,
                        "hz": None,
                        "samples": 0,
                        "error": "no publisher",
                    }
                    continue
                info = publishers[0]
                try:
                    msg_type = get_message(info.topic_type)
                except (ImportError, AttributeError, ValueError) as exc:
                    results[topic] = {
                        "present": True,
                        "hz": None,
                        "samples": 0,
                        "error": f"unknown message type {info.topic_type}: {exc}",
                    }
                    continue

                # Match the publisher's reliability and durability. A mismatch
                # here is the single most common reason a topic looks dead.
                qos = QoSProfile(depth=10, history=HistoryPolicy.KEEP_LAST)
                qos.reliability = info.qos_profile.reliability
                qos.durability = info.qos_profile.durability

                counter = _Counter()
                counters[topic] = counter
                keep_alive.append(
                    node.create_subscription(
                        msg_type,
                        topic,
                        lambda _msg, c=counter: c.tick(),
                        qos,
                        raw=True,  # count bytes, never deserialise
                    )
                )
                results[topic] = {"present": True, "hz": None, "samples": 0, "error": None}

            end = time.monotonic() + duration
            while time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=0.02)

            for topic, counter in counters.items():
                results[topic]["samples"] = counter.count
                results[topic]["hz"] = counter.hz()
                if counter.count == 0:
                    results[topic]["error"] = "publisher advertised but silent"
                elif counter.count == 1:
                    results[topic]["error"] = "only one message in the window"
            return results
        finally:
            node.destroy_node()
    finally:
        rclpy.shutdown()


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Measure ROS 2 topic rates.")
    parser.add_argument("topics", nargs="+")
    parser.add_argument("--duration", type=float, default=2.0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        results = _probe(args.topics, args.duration)
    except Exception as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 1
    json.dump(results, sys.stdout)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
