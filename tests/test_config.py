"""The sensor registry is the spec of this car, so it gets asserted, not assumed."""

import json
from pathlib import Path

import pytest

from codriver.config import (
    ConfigError,
    SensorSpec,
    _apply_overrides,
    default_config,
    dump_config,
    load_config,
)


def test_camera_registry_matches_the_car() -> None:
    config = default_config()
    cameras = [s for s in config.sensors if s.kind == "camera"]
    assert len(cameras) == 8
    # Seven have to work; the front-centre fisheye is listed but never required.
    assert sum(c.critical for c in cameras) == 7
    fisheye = config.sensor("camera_front_center")
    assert fisheye is not None and not fisheye.critical
    assert all(c.expected_hz == 20.0 for c in cameras)


def test_lidar_registry_matches_the_car() -> None:
    config = default_config()
    lidars = [s for s in config.sensors if s.kind == "lidar"]
    assert len(lidars) == 7
    # Roof: one OS2 plus four OS1/OS0. The two bumper units are optional.
    assert sum(lidar.critical for lidar in lidars) == 5
    for name in ("lidar_bumper_front", "lidar_bumper_back"):
        spec = config.sensor(name)
        assert spec is not None and not spec.critical
    assert all(lidar.expected_hz == 10.0 for lidar in lidars)


def test_gnss_is_expected_at_20hz() -> None:
    gnss = default_config().sensor("gnss")
    assert gnss is not None
    assert gnss.expected_hz == 20.0 and gnss.critical


def test_rate_tolerance_catches_the_gnss_falling_to_1hz() -> None:
    gnss = SensorSpec("gnss", "gnss", "/gnss/fix", 20.0)
    assert gnss.rate_ok(20.0)
    assert gnss.rate_ok(19.2)
    assert not gnss.rate_ok(1.0)
    assert not gnss.rate_ok(10.0)


def test_recording_and_rviz_share_an_exclusive_group() -> None:
    config = default_config()
    recording = config.process("recording")
    rviz = config.process("rviz")
    assert recording is not None and rviz is not None
    assert recording.exclusive_group == rviz.exclusive_group is not None
    # Inference must stay free to run alongside a recording.
    for name in ("preprocessing", "detection", "pose"):
        spec = config.process(name)
        assert spec is not None and spec.exclusive_group is None


def test_pose_pipeline_waits_for_a_ready_marker() -> None:
    pose = default_config().process("pose")
    assert pose is not None
    assert pose.ready_pattern is not None
    assert pose.ready_after_seconds >= 30


def test_operating_mode_commands_point_at_the_script_directory() -> None:
    config = default_config()
    names = {c.name for c in config.commands}
    assert names == {"om_normal_all", "om_standby_all", "om_normal_bumper", "om_standby_bumper"}
    for command in config.commands:
        assert command.command[0].startswith("~/scripts/")


def test_every_default_command_and_process_lives_under_the_script_directory() -> None:
    config = default_config()
    launched = [c.command[0] for c in config.commands]
    launched += [p.command[0] for p in config.processes if p.name != "rviz"]
    assert all(path.startswith("~/scripts/") for path in launched), launched


def test_overrides_replace_lists_and_scalars(tmp_path: Path) -> None:
    raw = {
        "ros_backend": "mock",
        "port": 9999,
        "sensors": [{"name": "only", "kind": "lidar", "topic": "/x", "expected_hz": 10}],
    }
    config = _apply_overrides(default_config(), raw, tmp_path / "c.json")
    assert config.ros_backend == "mock"
    assert config.port == 9999
    assert [s.name for s in config.sensors] == ["only"]
    # Untouched sections keep their defaults.
    assert len(config.processes) == 5


def test_unknown_key_is_an_error_not_a_silent_ignore(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown keys"):
        _apply_overrides(default_config(), {"portt": 1}, tmp_path / "c.json")


def test_missing_field_names_the_offending_entry(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="expected_hz"):
        _apply_overrides(
            default_config(),
            {"sensors": [{"name": "x", "kind": "lidar", "topic": "/x"}]},
            tmp_path / "c.json",
        )


def test_dump_config_round_trips(tmp_path: Path) -> None:
    original = default_config()
    path = tmp_path / "codriver.json"
    path.write_text(dump_config(original))
    reloaded = _apply_overrides(default_config(), json.loads(path.read_text()), path)
    assert reloaded == original


def test_explicit_config_path_that_does_not_exist_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODRIVER_CONFIG", str(tmp_path / "nope.json"))
    with pytest.raises(ConfigError, match="does not exist"):
        load_config()
