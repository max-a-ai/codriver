"""Everything the panel needs to know about this car: sensors, scripts, pipelines.

Nothing in here is discovered at runtime. The vehicle's topic names, script paths
and launch commands are deployment facts, so they live in one JSON file that can
be edited on the car without touching the code. The values below are the
defaults; a config file only has to name the keys it disagrees with.

Lookup order for the config file:

    $CODRIVER_CONFIG            explicit path, must exist if set
    ./codriver.json             next to wherever the app was started
    ~/.config/codriver/config.json

Write the effective config out with `python -m codriver --dump-config` to get a
starting point that already lists every key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

SensorKind = Literal["camera", "lidar", "gnss"]

#: How far a measured rate may drift from the expected one before it counts as
#: bad, as a fraction. 0.15 at 20 Hz means anything in [17.0, 23.0] passes. The
#: GNSS failure this panel exists to catch is a drop to 1 Hz, so the tolerance
#: only has to be tighter than "one twentieth of nominal".
DEFAULT_RATE_TOLERANCE = 0.15


def _repo_instructions() -> Path:
    """The `instructions/` folder in the checkout: one `<tab-id>.md` per tab.

    Found from the package location first, which covers running from source and
    an editable install, then from the working directory, which covers being
    started from the repo root by some other means. If neither exists the first
    is still returned, and every tab simply reports "no notes yet" rather than
    the panel refusing to start. `instructions_dir` in the config overrides all
    of it.
    """
    candidates = [
        Path(__file__).resolve().parents[2] / "instructions",
        Path.cwd() / "instructions",
    ]
    return next((path for path in candidates if path.is_dir()), candidates[0])


#: On the car this is a git clone, so editing a note is a commit like any other.
REPO_INSTRUCTIONS = _repo_instructions()


@dataclass(frozen=True)
class SensorSpec:
    """One row in the status tab."""

    name: str
    kind: SensorKind
    topic: str
    expected_hz: float
    #: False for sensors that are wired up and listed but whose failure must not
    #: colour the whole block red: the front-centre fisheye and the two bumper
    #: lidars are never recorded, so a bad reading there is noise, not a stop.
    critical: bool = True
    tolerance: float = DEFAULT_RATE_TOLERANCE
    #: Every topic that goes into the bag when this sensor is switched on for a
    #: recording. A camera is two topics, not one: an `image_raw` without its
    #: `camera_info` is a bag nobody can calibrate afterwards.
    record_topics: tuple[str, ...] = ()
    #: Recorded whether or not anything is toggled, and not offered as a button.
    #: The GNSS is the only one: it is small, it is always wanted, and a
    #: recording that silently lost it is worthless.
    always_record: bool = False

    def rate_ok(self, measured_hz: float) -> bool:
        span = self.expected_hz * self.tolerance
        return abs(measured_hz - self.expected_hz) <= span


def default_record_topics(kind: SensorKind, topic: str) -> tuple[str, ...]:
    """What a sensor contributes to a recording, derived from its live topic.

    Used when a config file names a sensor but not its recording topics.
    """
    namespace = topic.rsplit("/", 1)[0]
    if kind == "camera":
        return (topic, f"{namespace}/camera_info")
    # Ouster units also publish `/imu`, and optionally `scan`, `metadata` and
    # the range/signal/reflectivity images. Only the cloud is recorded by
    # default; see PROJECT_PLAN.md if the IMU should join it.
    return (topic,)


@dataclass(frozen=True)
class ProcessSpec:
    """A long-running child process the panel starts and Ctrl-C's."""

    name: str
    label: str
    command: list[str]
    #: Regex matched against the process's own output. Until it matches, the
    #: process reports as "initializing" rather than "running". Pose inference
    #: loads a large checkpoint and is unusable for the first half minute, and a
    #: green light during that window is a lie. None means "green once it has
    #: survived `ready_after_seconds`".
    ready_pattern: str | None = None
    ready_after_seconds: float = 3.0
    #: Processes naming the same group cannot run at the same time. Recording
    #: and RViz share one: the car cannot do both.
    exclusive_group: str | None = None
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandSpec:
    """A short-lived script run to completion, output shown in the panel."""

    name: str
    label: str
    command: list[str]
    description: str = ""


@dataclass(frozen=True)
class Config:
    sensors: list[SensorSpec]
    processes: list[ProcessSpec]
    commands: list[CommandSpec]
    #: "auto" resolves to rclpy when a ROS environment is present, else mock.
    ros_backend: Literal["auto", "mock", "rclpy", "ros2cli", "bag"] = "auto"
    #: Seconds of traffic each rate measurement observes. Two seconds is eight
    #: frames of the slowest sensor here, enough to tell 10 Hz from 1 Hz without
    #: making the status tab feel stuck.
    probe_seconds: float = 2.0
    #: Seconds between automatic sensor sweeps. 0 disables them; the refresh
    #: button still works.
    auto_refresh_seconds: float = 0.0
    recordings_dir: str = "~/recordings"
    #: One `<tab-id>.md` per tab, opened by the right-hand rail. Defaults to the
    #: `instructions/` folder in this checkout, so the notes are version
    #: controlled and edited like any other file in the repo.
    instructions_dir: str = str(REPO_INSTRUCTIONS)
    log_dir: str = "~/.codriver/logs"
    host: str = "127.0.0.1"
    port: int = 8420

    def sensor(self, name: str) -> SensorSpec | None:
        return next((s for s in self.sensors if s.name == name), None)

    def process(self, name: str) -> ProcessSpec | None:
        return next((p for p in self.processes if p.name == name), None)

    def command(self, name: str) -> CommandSpec | None:
        return next((c for c in self.commands if c.name == name), None)


# --- defaults ---------------------------------------------------------------

# The seven cameras that have to be healthy, in the order they sit around the
# car, plus the front-centre fisheye which is listed but not required.
_CAMERAS: list[tuple[str, bool]] = [
    ("camera_front_left", True),
    ("camera_front_right", True),
    ("camera_right_front", True),
    ("camera_right_back", True),
    ("camera_back", True),
    ("camera_left_back", True),
    ("camera_left_front", True),
    ("camera_front_center", False),
]

# Five lidars we care about (one long-range OS2 on the roof, two OS1 facing
# front and back, two short-range OS0 covering the sides) and the two bumper
# units that are listed for completeness.
_LIDARS: list[tuple[str, bool]] = [
    ("lidar_roof_top", True),
    ("lidar_roof_front", True),
    ("lidar_roof_back", True),
    ("lidar_roof_left", True),
    ("lidar_roof_right", True),
    ("lidar_bumper_front", False),
    ("lidar_bumper_back", False),
]

CAMERA_HZ = 20.0
LIDAR_HZ = 10.0
GNSS_HZ = 20.0

#: Where every script the panel runs lives on the car.
SCRIPT_DIR = "~/scripts"


def _default_sensors() -> list[SensorSpec]:
    sensors = [
        SensorSpec(
            name,
            "camera",
            f"/{name}/image_raw",
            CAMERA_HZ,
            critical,
            record_topics=(f"/{name}/image_raw", f"/{name}/camera_info"),
        )
        for name, critical in _CAMERAS
    ]
    sensors += [
        SensorSpec(
            name,
            "lidar",
            f"/{name}/points",
            LIDAR_HZ,
            critical,
            record_topics=(f"/{name}/points",),
        )
        for name, critical in _LIDARS
    ]
    # The GNSS comes up at 1 Hz after a computer restart, which is why it gets
    # its own block in the status tab rather than a row among the lidars. It has
    # no recording toggle either: it is small and always wanted.
    sensors.append(
        SensorSpec(
            "gnss",
            "gnss",
            "/gnss/fix",
            GNSS_HZ,
            critical=True,
            record_topics=("/gnss/fix",),
            always_record=True,
        )
    )
    return sensors


def _default_processes() -> list[ProcessSpec]:
    return [
        ProcessSpec(
            name="recording",
            label="Recording",
            command=[f"{SCRIPT_DIR}/start_recording.sh"],
            exclusive_group="bag_io",
            ready_after_seconds=2.0,
        ),
        ProcessSpec(
            name="rviz",
            label="RViz2",
            command=["rviz2"],
            exclusive_group="bag_io",
            ready_after_seconds=5.0,
        ),
        ProcessSpec(
            name="preprocessing",
            label="Preprocessing pipeline",
            command=[f"{SCRIPT_DIR}/start_preprocessing.sh"],
            ready_after_seconds=5.0,
        ),
        ProcessSpec(
            name="detection",
            label="Detection pipeline",
            command=[f"{SCRIPT_DIR}/start_detection.sh"],
            ready_after_seconds=5.0,
        ),
        ProcessSpec(
            name="pose",
            label="Pose inference pipeline",
            command=[f"{SCRIPT_DIR}/start_pose_inference.sh"],
            # Loads a large checkpoint before it is usable, so it stays orange
            # until it says so itself.
            ready_pattern=r"(?i)(ready|running|checkpoint loaded)",
            ready_after_seconds=60.0,
        ),
    ]


def _default_commands() -> list[CommandSpec]:
    return [
        CommandSpec(
            "om_normal_all",
            "All lidars: normal",
            [f"{SCRIPT_DIR}/om_normal_all.sh"],
            "Bring every lidar back to normal operating mode.",
        ),
        CommandSpec(
            "om_standby_all",
            "All lidars: standby",
            [f"{SCRIPT_DIR}/om_standby_all.sh"],
            "Put every lidar into standby.",
        ),
        CommandSpec(
            "om_normal_bumper",
            "Bumper lidars: normal",
            [f"{SCRIPT_DIR}/om_normal_bumper.sh"],
            "Bring the two bumper lidars back to normal operating mode.",
        ),
        CommandSpec(
            "om_standby_bumper",
            "Bumper lidars: standby",
            [f"{SCRIPT_DIR}/om_standby_bumper.sh"],
            "Put the two bumper lidars into standby.",
        ),
    ]


def default_config() -> Config:
    return Config(
        sensors=_default_sensors(),
        processes=_default_processes(),
        commands=_default_commands(),
    )


# --- loading ----------------------------------------------------------------


class ConfigError(RuntimeError):
    """The config file exists but the panel cannot use it."""


def config_search_path() -> list[Path]:
    explicit = os.environ.get("CODRIVER_CONFIG")
    if explicit:
        return [Path(explicit).expanduser()]
    return [
        Path("codriver.json").resolve(),
        Path("~/.config/codriver/config.json").expanduser(),
    ]


def load_config() -> Config:
    """Read the first config file that exists, layered over the defaults."""
    base = default_config()
    explicit = os.environ.get("CODRIVER_CONFIG")
    for path in config_search_path():
        if path.is_file():
            return _apply_overrides(base, _read_json(path), path)
        if explicit:
            raise ConfigError(f"CODRIVER_CONFIG points at {path}, which does not exist")
    return base


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config {path} must contain a JSON object at the top level")
    return raw


_SCALAR_KEYS = (
    "ros_backend",
    "probe_seconds",
    "auto_refresh_seconds",
    "recordings_dir",
    "instructions_dir",
    "log_dir",
    "host",
    "port",
)


def _apply_overrides(base: Config, raw: dict[str, Any], path: Path) -> Config:
    """Layer a config file over the defaults.

    Lists replace wholesale rather than merging by name: a half-overridden
    sensor list is much harder to reason about on a car than an explicit one,
    and `--dump-config` hands you the full list to edit.
    """
    unknown = set(raw) - {*_SCALAR_KEYS, "sensors", "processes", "commands"}
    if unknown:
        raise ConfigError(f"config {path} has unknown keys: {', '.join(sorted(unknown))}")

    changes: dict[str, Any] = {k: raw[k] for k in _SCALAR_KEYS if k in raw}
    if "sensors" in raw:
        changes["sensors"] = [_sensor_from(item, path) for item in _as_list(raw["sensors"], path)]
    if "processes" in raw:
        changes["processes"] = [
            _process_from(item, path) for item in _as_list(raw["processes"], path)
        ]
    if "commands" in raw:
        changes["commands"] = [
            _command_from(item, path) for item in _as_list(raw["commands"], path)
        ]
    try:
        return replace(base, **changes)
    except TypeError as exc:  # pragma: no cover - guarded by the unknown-key check
        raise ConfigError(f"config {path}: {exc}") from exc


def _as_list(value: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(i, dict) for i in value):
        raise ConfigError(f"config {path}: expected a list of objects")
    return value


def _require(item: dict[str, Any], key: str, path: Path) -> Any:
    if key not in item:
        raise ConfigError(f"config {path}: entry {item!r} is missing '{key}'")
    return item[key]


def _sensor_from(item: dict[str, Any], path: Path) -> SensorSpec:
    kind = _require(item, "kind", path)
    if kind not in ("camera", "lidar", "gnss"):
        raise ConfigError(f"config {path}: unknown sensor kind {kind!r}")
    topic = str(_require(item, "topic", path))
    raw_topics = item.get("record_topics")
    if raw_topics is None:
        record_topics = default_record_topics(kind, topic)
    elif isinstance(raw_topics, list):
        record_topics = tuple(str(t) for t in raw_topics)
    else:
        raise ConfigError(f"config {path}: 'record_topics' must be a list of strings")
    return SensorSpec(
        name=str(_require(item, "name", path)),
        kind=kind,
        topic=topic,
        expected_hz=float(_require(item, "expected_hz", path)),
        critical=bool(item.get("critical", True)),
        tolerance=float(item.get("tolerance", DEFAULT_RATE_TOLERANCE)),
        record_topics=record_topics,
        always_record=bool(item.get("always_record", False)),
    )


def _process_from(item: dict[str, Any], path: Path) -> ProcessSpec:
    command = _require(item, "command", path)
    if not isinstance(command, list) or not command:
        raise ConfigError(f"config {path}: 'command' must be a non-empty list of strings")
    return ProcessSpec(
        name=str(_require(item, "name", path)),
        label=str(item.get("label", item["name"])),
        command=[str(part) for part in command],
        ready_pattern=item.get("ready_pattern"),
        ready_after_seconds=float(item.get("ready_after_seconds", 3.0)),
        exclusive_group=item.get("exclusive_group"),
        cwd=item.get("cwd"),
        env={str(k): str(v) for k, v in dict(item.get("env", {})).items()},
    )


def _command_from(item: dict[str, Any], path: Path) -> CommandSpec:
    command = _require(item, "command", path)
    if not isinstance(command, list) or not command:
        raise ConfigError(f"config {path}: 'command' must be a non-empty list of strings")
    return CommandSpec(
        name=str(_require(item, "name", path)),
        label=str(item.get("label", item["name"])),
        command=[str(part) for part in command],
        description=str(item.get("description", "")),
    )


def dump_config(config: Config) -> str:
    """Serialise a config back to JSON, ready to be edited on the car."""
    payload: dict[str, Any] = {key: getattr(config, key) for key in _SCALAR_KEYS}
    payload["sensors"] = [
        {
            "name": s.name,
            "kind": s.kind,
            "topic": s.topic,
            "expected_hz": s.expected_hz,
            "critical": s.critical,
            "tolerance": s.tolerance,
            "record_topics": list(s.record_topics),
            "always_record": s.always_record,
        }
        for s in config.sensors
    ]
    payload["processes"] = [
        {
            "name": p.name,
            "label": p.label,
            "command": p.command,
            "ready_pattern": p.ready_pattern,
            "ready_after_seconds": p.ready_after_seconds,
            "exclusive_group": p.exclusive_group,
            "cwd": p.cwd,
            "env": p.env,
        }
        for p in config.processes
    ]
    payload["commands"] = [
        {
            "name": c.name,
            "label": c.label,
            "command": c.command,
            "description": c.description,
        }
        for c in config.commands
    ]
    return json.dumps(payload, indent=2) + "\n"
