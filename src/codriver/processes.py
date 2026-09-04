"""Starting, watching and Ctrl-C'ing the long-running things the panel drives.

The rules this encodes:

*   Stopping means SIGINT to the child's own process group, which is exactly
    what Ctrl-C in its terminal does. `ros2 bag record` closes its bag on
    SIGINT and corrupts it on SIGKILL, so nothing else will do.
*   Recording and RViz belong to one exclusive group: the car can do either,
    never both. Recording and inference are free to run together.
*   A pipeline that is up is not the same as a pipeline that is ready. Pose
    inference spends the best part of a minute loading a checkpoint, and a
    green light during that window would be a lie, so there is a separate
    initializing state.
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal

from .config import CommandSpec, ProcessSpec

#: idle        never started, or stopped cleanly on request
#: initializing  up, but not yet reporting itself ready
#: running     up and ready
#: crashed     exited on its own, or never started
ProcessState = Literal["idle", "initializing", "running", "crashed"]

#: Lines of output kept in memory per process for the log view.
LOG_BUFFER_LINES = 400

#: How long a SIGINT gets to work before escalating. Long enough for a bag to
#: be closed and indexed.
SIGINT_GRACE = 15.0
SIGTERM_GRACE = 5.0


class ProcessConflictError(RuntimeError):
    """Refused because something in the same exclusive group is running."""


@dataclass(frozen=True)
class ProcessStatus:
    name: str
    label: str
    state: ProcessState
    pid: int | None = None
    started_at: float | None = None
    exit_code: int | None = None
    #: Human-readable reason, shown under the light. Empty when there is
    #: nothing to explain.
    detail: str = ""
    log_path: str = ""
    #: Name of the process holding this one's exclusive group, if any.
    blocked_by: str | None = None


@dataclass(frozen=True)
class CommandResult:
    name: str
    exit_code: int
    output: str
    seconds: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _expand(command: list[str]) -> list[str]:
    return [os.path.expanduser(part) for part in command]


class ManagedProcess:
    """One child process, its output buffer, and its readiness."""

    def __init__(self, spec: ProcessSpec, log_dir: Path) -> None:
        self.spec = spec
        self.log_path = log_dir / f"{spec.name}.log"
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._lines: deque[str] = deque(maxlen=LOG_BUFFER_LINES)
        self._ready = False
        self._started_at: float | None = None
        self._stop_requested = False
        self._detail = ""
        self._exit_code: int | None = None
        self._pattern = re.compile(spec.ready_pattern) if spec.ready_pattern else None

    # --- lifecycle ---

    def start(
        self, extra_args: Sequence[str] = (), extra_env: dict[str, str] | None = None
    ) -> None:
        """Start the child, optionally with arguments decided at click time.

        The recording script gets its topic list this way, both as arguments and
        as `CODRIVER_TOPICS`, so a script can consume whichever is more convenient
        without the panel having to know which.
        """
        with self._lock:
            if self._is_alive():
                return
            self._lines.clear()
            self._ready = False
            self._stop_requested = False
            self._detail = ""
            self._exit_code = None
            command = _expand(self.spec.command) + list(extra_args)
            env = {**os.environ, **self.spec.env, **(extra_env or {})}
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._proc = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=os.path.expanduser(self.spec.cwd) if self.spec.cwd else None,
                    env=env,
                    # Its own process group, so a stop reaches the whole tree the
                    # way Ctrl-C would, and so our own SIGINT never reaches it.
                    start_new_session=True,
                )
            except (OSError, ValueError) as exc:
                self._proc = None
                self._started_at = time.monotonic()
                self._exit_code = -1
                self._detail = f"could not start: {exc}"
                self._append(f"[codriver] could not start {' '.join(command)}: {exc}")
                return
            self._started_at = time.monotonic()
            self._append(f"[codriver] started: {' '.join(command)}")
            stream = self._proc.stdout
            if stream is not None:
                threading.Thread(
                    target=self._pump, args=(stream,), name=f"log-{self.spec.name}", daemon=True
                ).start()

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._stop_requested = True
                return
            self._stop_requested = True
            self._append("[codriver] stopping (SIGINT)")
        self._signal_group(proc, signal.SIGINT)
        if self._wait(proc, SIGINT_GRACE):
            return
        self._append("[codriver] still up after SIGINT, sending SIGTERM")
        self._signal_group(proc, signal.SIGTERM)
        if self._wait(proc, SIGTERM_GRACE):
            return
        self._append("[codriver] still up after SIGTERM, sending SIGKILL")
        self._signal_group(proc, signal.SIGKILL)
        self._wait(proc, SIGTERM_GRACE)

    def _signal_group(self, proc: subprocess.Popen[str], sig: signal.Signals) -> None:
        # Already gone between the poll and the signal is fine; there is
        # nothing left to stop.
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), sig)

    def _wait(self, proc: subprocess.Popen[str], seconds: float) -> bool:
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            return False
        return True

    # --- output ---

    def _pump(self, stream: IO[str]) -> None:
        try:
            with self.log_path.open("a", encoding="utf-8") as sink:
                for line in stream:
                    text = line.rstrip("\n")
                    self._append(text, sink)
                    if self._pattern is not None and self._pattern.search(text):
                        self._ready = True
        except (OSError, ValueError):
            # The pipe closed under us; the exit is picked up by status().
            pass

    def _append(self, text: str, sink: IO[str] | None = None) -> None:
        stamped = f"{time.strftime('%H:%M:%S')} {text}"
        self._lines.append(stamped)
        if sink is not None:
            sink.write(stamped + "\n")

    def log_tail(self, lines: int) -> list[str]:
        return list(self._lines)[-lines:]

    # --- state ---

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self, blocked_by: str | None = None) -> ProcessStatus:
        with self._lock:
            state, detail, exit_code = self._derive()
            return ProcessStatus(
                name=self.spec.name,
                label=self.spec.label,
                state=state,
                pid=self._proc.pid if self._is_alive() and self._proc else None,
                started_at=self._started_at,
                exit_code=exit_code,
                detail=detail,
                log_path=str(self.log_path),
                blocked_by=blocked_by,
            )

    def _derive(self) -> tuple[ProcessState, str, int | None]:
        if self._proc is None:
            if self._detail:
                return "crashed", self._detail, self._exit_code
            return "idle", "", None

        code = self._proc.poll()
        if code is None:
            if self._ready:
                return "running", self._detail, None
            elapsed = time.monotonic() - (self._started_at or time.monotonic())
            if elapsed < self.spec.ready_after_seconds:
                return "initializing", self._detail or "starting up", None
            # Past its own deadline and still alive. Treat it as up rather than
            # leaving it orange forever, but say the marker was never seen so a
            # silently wedged pipeline is not mistaken for a healthy one.
            if self._pattern is not None:
                return "running", "up, but never reported ready", None
            return "running", self._detail, None

        if self._stop_requested:
            return "idle", "stopped", code
        # Died on its own. A ready pattern never matching plus an exit is still a
        # crash, whatever the code says.
        return "crashed", f"exited with code {code}", code


class ProcessManager:
    """Owns every managed process and enforces the exclusive groups."""

    def __init__(self, specs: list[ProcessSpec], log_dir: str) -> None:
        root = Path(log_dir).expanduser()
        self._procs = {spec.name: ManagedProcess(spec, root) for spec in specs}
        self._specs = {spec.name: spec for spec in specs}

    def __contains__(self, name: object) -> bool:
        return name in self._procs

    def start(
        self, name: str, extra_args: Sequence[str] = (), extra_env: dict[str, str] | None = None
    ) -> None:
        spec = self._specs[name]
        holder = self._group_holder(spec.exclusive_group, exclude=name)
        if holder is not None:
            raise ProcessConflictError(
                f"{self._specs[holder].label} is running; the car cannot do both"
            )
        self._procs[name].start(extra_args, extra_env)

    def stop(self, name: str) -> None:
        self._procs[name].stop()

    def statuses(self) -> list[ProcessStatus]:
        return [
            self._procs[name].status(
                blocked_by=self._group_holder(spec.exclusive_group, exclude=name)
            )
            for name, spec in self._specs.items()
        ]

    def log_tail(self, name: str, lines: int = LOG_BUFFER_LINES) -> list[str]:
        return self._procs[name].log_tail(lines)

    def _group_holder(self, group: str | None, exclude: str) -> str | None:
        """Name of another process in `group` that is currently up."""
        if group is None:
            return None
        for name, spec in self._specs.items():
            if name == exclude or spec.exclusive_group != group:
                continue
            if self._procs[name].status().state in ("initializing", "running"):
                return name
        return None

    def stop_all(self) -> None:
        """Take every child down with us. Called when the panel exits, so a
        closed browser tab never leaves an orphaned recorder holding a bag
        open."""
        for proc in self._procs.values():
            if proc.status().state in ("initializing", "running"):
                proc.stop()


def run_command(spec: CommandSpec, timeout: float = 60.0) -> CommandResult:
    """Run a short-lived script to completion and hand back what it said."""
    started = time.monotonic()
    command = _expand(spec.command)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(spec.name, 124, f"timed out after {timeout:.0f}s", timeout)
    except OSError as exc:
        return CommandResult(spec.name, 127, f"could not run {command[0]}: {exc}", 0.0)
    output = (completed.stdout or "") + (completed.stderr or "")
    return CommandResult(
        spec.name,
        completed.returncode,
        output.strip() or "(no output)",
        time.monotonic() - started,
    )
