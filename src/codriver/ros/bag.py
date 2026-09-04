"""Rate measurement by recording a throwaway bag and counting what landed in it.

This is the method that is already trusted on this car: record for a minute or
two, then look at the topics of interest. It is the slowest of the backends and
it writes to disk, but it measures the thing that actually matters, which is
what a recording would contain, and it cannot be fooled by a QoS mismatch in the
measuring tool.

Kept as the arbiter. When the live probe and this one disagree, this one is the
ground truth for the question "will the recording have the frames".
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from .backend import RateReading

#: `ros2 bag record` needs a moment to open its storage and match publishers
#: before any message lands. Recorded time is measured from the bag's own
#: duration, so this only affects how long the sweep takes.
_RECORD_STARTUP = 3.0

_DURATION = re.compile(r"Duration:\s*([0-9]+\.?[0-9]*)")
_TOPIC_ROW = re.compile(r"Topic:\s*(\S+)\s*\|\s*Type:\s*\S+\s*\|\s*Count:\s*(\d+)")


class BagBackend:
    name = "bag"

    def __init__(self, recordings_dir: str = "~/recordings") -> None:
        # Only used to pick a scratch location on the same filesystem as real
        # recordings, so a bag that fits here would fit there too.
        self.recordings_dir = Path(recordings_dir).expanduser()

    def available(self) -> bool:
        return shutil.which("ros2") is not None

    def measure(self, topics: Sequence[str], duration: float) -> dict[str, RateReading]:
        if not topics:
            return {}
        parent = self.recordings_dir if self.recordings_dir.is_dir() else None
        scratch = Path(tempfile.mkdtemp(prefix="codriver-probe-", dir=parent))
        bag_dir = scratch / "bag"
        try:
            error = self._record(bag_dir, topics, duration)
            if error:
                return {t: RateReading.missing(t, error=error) for t in topics}
            return self._read_info(bag_dir, topics)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def _record(self, bag_dir: Path, topics: Sequence[str], duration: float) -> str | None:
        argv = ["ros2", "bag", "record", "-o", str(bag_dir), *topics]
        try:
            # Own process group, so the interrupt reaches the recorder the same
            # way Ctrl-C would in its own terminal. Anything else risks a bag
            # that was never closed cleanly.
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            return f"cannot run ros2 bag record: {exc}"

        time.sleep(duration + _RECORD_STARTUP)
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        try:
            _, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            return "ros2 bag record did not stop"
        if not bag_dir.exists():
            detail = (stderr or b"").decode("utf-8", "replace").strip().splitlines()
            return detail[-1] if detail else "ros2 bag record produced no bag"
        return None

    def _read_info(self, bag_dir: Path, topics: Sequence[str]) -> dict[str, RateReading]:
        try:
            out = subprocess.run(
                ["ros2", "bag", "info", str(bag_dir)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {t: RateReading.missing(t, error=f"ros2 bag info failed: {exc}") for t in topics}

        counts = {name: int(count) for name, count in _TOPIC_ROW.findall(out.stdout)}
        span = _DURATION.search(out.stdout)
        seconds = float(span.group(1)) if span else 0.0

        results: dict[str, RateReading] = {}
        for topic in topics:
            count = counts.get(topic, 0)
            if count == 0:
                results[topic] = RateReading.missing(topic, error="nothing recorded")
            elif seconds <= 0:
                results[topic] = RateReading(topic, present=True, hz=None, samples=count)
            else:
                results[topic] = RateReading(topic, present=True, hz=count / seconds, samples=count)
        return results
