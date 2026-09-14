"""The terminal's event log.

The panel's first claim is that nothing the language layer does is
invisible to somebody watching the screen. That only holds if every
action actually lands in the log, and if a click can be told apart from
a model action, so both are asserted here rather than assumed.
"""

import time
from typing import Any

import pytest

from codriver.app import App
from codriver.config import Config, default_config


@pytest.fixture()
def app(tmp_path: Any) -> App:
    base = default_config()
    return App(
        Config(
            sensors=base.sensors,
            processes=[],
            commands=[],
            ros_backend="mock",
            probe_seconds=0.1,
            log_dir=str(tmp_path / "logs"),
        )
    )


def _find(app: App, verb: str) -> list[dict[str, Any]]:
    return [e for e in app.events.snapshot() if e["verb"] == verb]


def _sweep(app: App) -> None:
    """Run one sensor sweep and wait for it, since it runs in a thread."""
    app.monitor.refresh_async()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        _, meta = app.monitor.snapshot()
        if not meta.get("sweeping"):
            return
        time.sleep(0.02)
    raise AssertionError("the sweep never finished")


def test_a_switch_records_what_it_turned_on(app: App) -> None:
    # The fisheye starts off, so one toggle is one activation.
    app.toggle_recording_topic("camera_front_center")
    activated = _find(app, "activated")
    assert [e["subject"] for e in activated] == ["camera_front_center"]
    assert activated[0]["area"] == "recording"
    assert activated[0]["source"] == "click"


def test_turning_a_switch_off_records_the_deactivation(app: App) -> None:
    app.toggle_recording_topic("camera_front_left")  # on by default: off
    assert [e["subject"] for e in _find(app, "deactivated")] == [
        "camera_front_left"
    ]


def test_a_group_switch_records_every_sensor_it_moved(app: App) -> None:
    # "cameras" is partially on by default, so pressing it turns the
    # rest on rather than everything off. Each one is its own line.
    app.toggle_recording_topic("cameras")
    assert _find(app, "activated")


def test_the_model_is_labelled_differently_from_a_click(app: App) -> None:
    app.toggle_recording_topic("camera_front_center", source="model")
    assert _find(app, "activated")[0]["source"] == "model"


def test_a_typed_question_is_logged_with_the_reply(app: App) -> None:
    result = app.say("activate all lidars")
    assert result["ok"] is True
    assert "not connected" in result["reply"]
    assert _find(app, "asked")[0]["subject"] == "activate all lidars"
    assert _find(app, "replied")[0]["area"] == "terminal"


def test_an_empty_question_does_nothing(app: App) -> None:
    assert app.say("   ")["ok"] is False
    assert not app.events.snapshot()


def test_a_red_sensor_is_reported_once_not_every_poll(app: App) -> None:
    # The mock scenario holds the GNSS at 1 Hz, so a sweep turns it red.
    # state() is polled once a second by every open browser; the log has
    # to carry one line per failure, not one per poll.
    _sweep(app)
    for _ in range(5):
        app.state()
    went_red = _find(app, "went red")
    assert [e["subject"] for e in went_red] == ["gnss"]
    assert went_red[0]["level"] == "bad"
    assert went_red[0]["source"] == "panel"


def test_an_optional_sensor_going_red_is_not_reported(app: App) -> None:
    # The fisheye is expected to be dead and would otherwise fill the
    # terminal on every restart.
    _sweep(app)
    app.state()
    subjects = [e["subject"] for e in _find(app, "went red")]
    assert "camera_front_center" not in subjects


def test_the_log_is_newest_first(app: App) -> None:
    app.toggle_recording_topic("camera_front_center")
    app.say("hello")
    assert app.events.snapshot()[0]["verb"] == "replied"
