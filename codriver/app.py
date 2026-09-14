"""The panel's application state and the JSON it hands the browser.

One object owns everything the UI can see or change: the sensor monitor, the
managed processes, and the results of the last one-shot command. The HTTP layer
in `server.py` does nothing but route to the methods here, so the whole
behaviour of the panel is testable without a socket.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from pathlib import Path
from typing import Any

from .config import Config, load_config
from .events import EventLog, Source
from .processes import (
    CommandResult,
    ProcessConflictError,
    ProcessManager,
    run_command,
)
from .recording import RecordingSelection
from .ros import resolve_backend
from .sensors import SensorMonitor

#: Tabs the UI shows.
#:
#: Status answers "is anything wrong" and nothing else. Monitoring is where a
#: sensor is started, stopped or put on screen. Recording is its own tab now
#: that the visualiser lives under Monitoring. Map, prediction and planning are
#: somebody else's work, so they share one tab with a section each rather than
#: taking three rows of the rail for three empty screens.
TABS: list[dict[str, str]] = [
    {"id": "status", "label": "Status", "kind": "live"},
    {"id": "monitoring", "label": "Monitoring", "kind": "live"},
    {"id": "recording", "label": "Recording", "kind": "live"},
    {"id": "perception", "label": "Perception", "kind": "live"},
    {"id": "custom", "label": "Custom functionalities", "kind": "placeholder"},
]

#: The sections inside the "custom functionalities" tab. Each is a placeholder
#: with its own heading, so the shape of the eventual screen is already
#: visible.
CUSTOM_SECTIONS: list[dict[str, str]] = [
    {"id": "map", "label": "Map"},
    {"id": "prediction", "label": "Prediction"},
    {"id": "planning", "label": "Planning"},
]

#: Which managed processes belong to which tab.
RECORDING_PROCESSES = ("recording",)
MONITORING_PROCESSES = ("rviz",)
PERCEPTION_PROCESSES = ("preprocessing", "detection", "pose")

#: The process whose argv is built from the recording tab's switches.
RECORDER = "recording"


class App:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.monitor = SensorMonitor(self.config, resolve_backend(self.config))
        self.processes = ProcessManager(
            self.config.processes, self.config.log_dir
        )
        self.selection = RecordingSelection(self.config.sensors)
        self.events = EventLog()
        self._lock = threading.Lock()
        self._command_results: dict[str, CommandResult] = {}
        #: Sensors already reported red, so the terminal says so on the
        #: sweep that broke them rather than once per poll forever.
        self._reported_bad: set[str] = set()

    def _area_of(self, process: str) -> str:
        """Which tab a process belongs to, for grouping in the log."""
        if process in RECORDING_PROCESSES:
            return "recording"
        if process in MONITORING_PROCESSES:
            return "monitoring"
        if process in PERCEPTION_PROCESSES:
            return "perception"
        return "monitoring"

    def start(self) -> None:
        self.monitor.start_auto_refresh()
        # One sweep at boot, so the status tab has numbers by the time anyone
        # has finished reading the sensor names.
        self.monitor.refresh_async()

    def shutdown(self) -> None:
        self.monitor.shutdown()
        self.processes.stop_all()

    # --- reads ---

    def is_recording(self) -> bool:
        status = next(
            (s for s in self.processes.statuses() if s.name == RECORDER), None
        )
        return status is not None and status.state in (
            "initializing",
            "running",
        )

    def _note_status(self, blocks: list[Any]) -> None:
        """Report sensors that just went red, and ones that came back.

        Called from `state()`, which several browsers poll at once, so it
        compares against what was already reported and only writes on a
        change. Optional sensors are skipped: a red fisheye is expected
        and would otherwise fill the terminal.
        """
        bad = {
            sensor.name
            for block in blocks
            for sensor in block.sensors
            if sensor.state == "bad" and sensor.critical
        }
        with self._lock:
            broke = bad - self._reported_bad
            fixed = self._reported_bad - bad
            self._reported_bad = bad
        for name in sorted(broke):
            self.events.add(
                "status", "went red", name, level="bad", source="panel"
            )
        for name in sorted(fixed):
            self.events.add("status", "recovered", name, source="panel")

    def state(self) -> dict[str, Any]:
        blocks, meta = self.monitor.snapshot()
        self._note_status(blocks)
        now = time.monotonic()
        with self._lock:
            results = {
                name: dataclasses.asdict(r)
                for name, r in self._command_results.items()
            }
        return {
            "tabs": TABS,
            # Switching topics mid-recording would do nothing to the bag
            # already being written, so the switches lock while the recorder is
            # up.
            "recording": self.selection.snapshot(locked=self.is_recording()),
            "sensors": {
                **meta,
                "blocks": [dataclasses.asdict(block) for block in blocks],
            },
            "processes": [
                {
                    **dataclasses.asdict(status),
                    "uptime_seconds": (
                        None
                        if status.started_at is None
                        else now - status.started_at
                    ),
                }
                for status in self.processes.statuses()
            ],
            "commands": [
                {
                    "name": c.name,
                    "label": c.label,
                    "description": c.description,
                }
                for c in self.config.commands
            ],
            "command_results": results,
            "groups": {
                "recording": list(RECORDING_PROCESSES),
                "monitoring": list(MONITORING_PROCESSES),
                "perception": list(PERCEPTION_PROCESSES),
            },
            "custom_sections": CUSTOM_SECTIONS,
            "events": self.events.snapshot(),
            "recordings_dir": self.config.recordings_dir,
            "instructions_dir": self.config.instructions_dir,
        }

    def log(self, name: str, lines: int = 200) -> dict[str, Any]:
        if name not in self.processes:
            raise KeyError(name)
        return {"name": name, "lines": self.processes.log_tail(name, lines)}

    def document(self, tab_id: str) -> dict[str, Any]:
        """The note behind one tab's button in the right-hand rail.

        One `<tab-id>.md` per tab, read from the repo on every request so an
        edit shows up without restarting the panel. A missing file is a normal
        answer rather than an error: several of these are placeholders until
        the equivalents are copied off the car.
        """
        tab = next((t for t in TABS if t["id"] == tab_id), None)
        if tab is None:
            raise KeyError(tab_id)
        path = Path(self.config.instructions_dir).expanduser() / f"{tab_id}.md"
        if not path.is_file():
            return {
                "tab": tab_id,
                "label": tab["label"],
                "path": str(path),
                "exists": False,
                "text": f"No notes yet. Create {path} and they will "
                "show up here.",
            }
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {
                "tab": tab_id,
                "label": tab["label"],
                "path": str(path),
                "exists": True,
                "text": f"could not read: {exc}",
            }
        return {
            "tab": tab_id,
            "label": tab["label"],
            "path": str(path),
            "exists": True,
            "text": text,
        }

    # --- writes ---

    def refresh_sensors(self) -> dict[str, Any]:
        return {"started": self.monitor.refresh_async()}

    def toggle_recording_topic(
        self, key: str, source: Source = "click"
    ) -> dict[str, Any]:
        """Flip one switch, or one group of switches, on the recording
        tab."""
        if self.is_recording():
            return {
                "ok": False,
                "error": "recording is running; stop it before "
                "changing topics",
            }
        before = self.selection.selected()
        self.selection.toggle(key)
        after = self.selection.selected()
        for name in sorted(after - before):
            self.events.add("recording", "activated", name, source=source)
        for name in sorted(before - after):
            self.events.add("recording", "deactivated", name, source=source)
        return {"ok": True, "topics": self.selection.topics()}

    def start_process(
        self, name: str, source: Source = "click"
    ) -> dict[str, Any]:
        if name not in self.processes:
            raise KeyError(name)
        extra_args: list[str] = []
        extra_env: dict[str, str] = {}
        if name == RECORDER:
            # The switches decide the recorder's argv. A recording with nothing
            # switched on would be an empty bag, so it is refused rather than
            # started.
            extra_args = self.selection.topics()
            if not extra_args:
                self.events.add(
                    "recording",
                    "refused to start",
                    "nothing selected",
                    level="bad",
                    source=source,
                )
                return {"ok": False, "error": "no topics selected"}
            extra_env = {"CODRIVER_TOPICS": " ".join(extra_args)}
        try:
            self.processes.start(name, extra_args, extra_env)
        except ProcessConflictError as exc:
            self.events.add(
                self._area_of(name),
                "could not start",
                f"{name}: {exc}",
                level="bad",
                source=source,
            )
            return {"ok": False, "error": str(exc)}
        self.events.add(self._area_of(name), "started", name, source=source)
        return {"ok": True}

    def stop_process(
        self, name: str, source: Source = "click"
    ) -> dict[str, Any]:
        if name not in self.processes:
            raise KeyError(name)
        self.processes.stop(name)
        self.events.add(self._area_of(name), "stopped", name, source=source)
        return {"ok": True}

    def say(self, text: str) -> dict[str, Any]:
        """Take a line typed into the terminal.

        The language layer is not built, so this records what was asked
        and says plainly that nothing is listening. The path exists end
        to end, which is what makes the typed and spoken channels a
        wiring job later rather than a new surface.
        """
        text = text.strip()
        if not text:
            return {"ok": False, "reply": "nothing to do"}
        self.events.add("terminal", "asked", text, source="click")
        reply = (
            "The language layer is not connected yet. When it is, this "
            "will go to the model, which may only run the actions on "
            "these tabs."
        )
        self.events.add("terminal", "replied", reply, source="panel")
        return {"ok": True, "reply": reply}

    def run(self, name: str, source: Source = "click") -> dict[str, Any]:
        spec = self.config.command(name)
        if spec is None:
            raise KeyError(name)
        result = run_command(spec)
        self.events.add(
            "monitoring",
            "ran" if result.exit_code == 0 else "failed to run",
            spec.label,
            level="info" if result.exit_code == 0 else "bad",
            source=source,
        )
        with self._lock:
            self._command_results[name] = result
        return dataclasses.asdict(result)
