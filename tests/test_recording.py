"""The recording switches: what is on by default, and what topics come out."""

import time
from pathlib import Path

import pytest

from codriver.app import App
from codriver.config import Config, ProcessSpec, default_config, default_record_topics
from codriver.recording import RecordingSelection


def _selection() -> RecordingSelection:
    return RecordingSelection(default_config().sensors)


def test_default_is_the_sensors_that_matter() -> None:
    selected = set(_selection().snapshot(locked=False)["selected"])
    assert "camera_front_center" not in selected
    assert "lidar_bumper_front" not in selected and "lidar_bumper_back" not in selected
    assert len(selected) == 12  # 7 required cameras + 5 required lidars


def test_default_topic_list() -> None:
    topics = _selection().topics()
    # Seven cameras at two topics each, five lidars at one, plus the GNSS.
    assert len(topics) == 7 * 2 + 5 + 1
    assert "/camera_back/image_raw" in topics
    assert "/camera_back/camera_info" in topics
    assert "/lidar_roof_top/points" in topics
    assert "/gnss/fix" in topics
    assert "/camera_front_center/image_raw" not in topics
    assert "/lidar_bumper_front/points" not in topics


def test_a_camera_is_never_recorded_without_its_calibration() -> None:
    selection = _selection()
    selection.toggle("camera_back")
    assert "/camera_back/image_raw" not in selection.topics()
    assert "/camera_back/camera_info" not in selection.topics()
    selection.toggle("camera_back")
    assert "/camera_back/image_raw" in selection.topics()
    assert "/camera_back/camera_info" in selection.topics()


def test_optional_sensors_have_to_be_switched_on_deliberately() -> None:
    selection = _selection()
    assert "/camera_front_center/image_raw" not in selection.topics()
    selection.toggle("camera_front_center")
    assert "/camera_front_center/image_raw" in selection.topics()
    assert "/camera_front_center/camera_info" in selection.topics()


def test_gnss_is_recorded_whatever_the_switches_say() -> None:
    selection = _selection()
    selection.toggle("all")  # everything on
    assert "/gnss/fix" in selection.topics()
    selection.toggle("all")  # everything off
    assert selection.topics() == ["/gnss/fix"]
    # And it is not offered as a switch.
    snapshot = selection.snapshot(locked=False)
    names = [s["name"] for col in snapshot["columns"] for s in col["required"] + col["optional"]]
    assert "gnss" not in names
    assert snapshot["always"] == [{"name": "gnss", "topics": ["/gnss/fix"]}]


def test_group_button_turns_a_whole_column_on_then_off() -> None:
    selection = _selection()
    selection.toggle("cameras")  # required were on, so this fills the column
    snapshot = selection.snapshot(locked=False)
    cameras = next(c for c in snapshot["columns"] if c["kind"] == "camera")
    assert all(s["state"] == "on" for s in cameras["required"] + cameras["optional"])
    assert next(g for g in cameras["groups"] if g["key"] == "cameras")["state"] == "on"

    selection.toggle("cameras")  # fully on, so now fully off
    snapshot = selection.snapshot(locked=False)
    cameras = next(c for c in snapshot["columns"] if c["kind"] == "camera")
    assert all(s["state"] == "off" for s in cameras["required"] + cameras["optional"])
    # Lidars were not touched.
    lidars = next(c for c in snapshot["columns"] if c["kind"] == "lidar")
    assert any(s["state"] == "on" for s in lidars["required"])


def test_a_half_lit_group_reads_partial_not_on() -> None:
    selection = _selection()
    groups = {
        g["key"]: g["state"]
        for col in selection.snapshot(locked=False)["columns"]
        for g in col["groups"]
    }
    # The default has every required camera but not the fisheye.
    assert groups["cameras"] == "partial"
    assert groups["cameras_required"] == "on"
    assert selection.snapshot(locked=False)["all"]["state"] == "partial"


def test_required_group_button_restores_exactly_the_default() -> None:
    selection = _selection()
    default = selection.topics()
    selection.toggle("all")  # everything on
    selection.toggle("all")  # everything off
    selection.toggle("cameras_required")
    selection.toggle("lidars_required")
    assert selection.topics() == default


def test_unknown_switch_is_an_error() -> None:
    with pytest.raises(KeyError):
        _selection().toggle("camera_nonexistent")


def test_record_topics_are_derived_when_a_config_omits_them() -> None:
    assert default_record_topics("camera", "/cam_a/image_raw") == (
        "/cam_a/image_raw",
        "/cam_a/camera_info",
    )
    assert default_record_topics("lidar", "/os2/points") == ("/os2/points",)


# --- wiring into the recorder ---


def _app_with_recorder(tmp_path: Path) -> App:
    base = default_config()
    marker = tmp_path / "argv.txt"
    script = tmp_path / "record.sh"
    script.write_text(
        '#!/usr/bin/env bash\ntrap "exit 0" INT\n'
        f'printf "%s\\n" "$@" > {marker}\n'
        f'echo "env:$CODRIVER_TOPICS" >> {marker}\n'
        "echo ready\nwhile true; do sleep 0.1; done\n"
    )
    script.chmod(0o755)
    config = Config(
        sensors=base.sensors,
        processes=[
            ProcessSpec(
                "recording",
                "Recording",
                [str(script)],
                ready_pattern="ready",
                exclusive_group="bag_io",
            )
        ],
        commands=[],
        ros_backend="mock",
        probe_seconds=0.1,
        log_dir=str(tmp_path / "logs"),
    )
    return App(config)


def test_the_recorder_is_started_with_the_selected_topics(tmp_path: Path) -> None:
    app = _app_with_recorder(tmp_path)
    app.selection.toggle("lidar_bumper_front")  # one extra, to prove it is not hardcoded
    expected = app.selection.topics()

    assert app.start_process("recording") == {"ok": True}
    marker = tmp_path / "argv.txt"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not marker.is_file():
        time.sleep(0.05)
    try:
        lines = marker.read_text().splitlines()
        argv, env_line = lines[:-1], lines[-1]
        assert argv == expected
        assert "/lidar_bumper_front/points" in argv
        # The same list is also on the environment, for scripts that prefer it.
        assert env_line == "env:" + " ".join(expected)
    finally:
        app.shutdown()


def test_topics_cannot_be_changed_while_the_recorder_runs(tmp_path: Path) -> None:
    app = _app_with_recorder(tmp_path)
    before = app.selection.topics()
    app.start_process("recording")
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not app.is_recording():
            time.sleep(0.05)
        result = app.toggle_recording_topic("cameras")
        assert result["ok"] is False
        assert "stop it" in result["error"]
        assert app.selection.topics() == before
        assert app.state()["recording"]["locked"] is True
    finally:
        app.shutdown()


def test_recording_with_nothing_selected_is_refused(tmp_path: Path) -> None:
    app = _app_with_recorder(tmp_path)
    # Switch everything off. The GNSS is pinned on, so drop it from the registry
    # first to reach a genuinely empty selection.
    app.selection = RecordingSelection([s for s in app.config.sensors if not s.always_record])
    app.selection.toggle("all")  # partial, so this fills it
    app.selection.toggle("all")  # now fully on, so this empties it
    assert app.selection.topics() == []
    assert app.start_process("recording") == {"ok": False, "error": "no topics selected"}
    app.shutdown()
