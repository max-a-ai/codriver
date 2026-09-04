"""Which readings turn a light red, and when a red light drags its block down."""

import time

from codriver.config import Config, SensorSpec, default_config
from codriver.ros import RateReading
from codriver.ros.mock import MockBackend
from codriver.sensors import SensorMonitor, evaluate, group_into_blocks

CAMERA = SensorSpec("camera_back", "camera", "/camera_back/image_raw", 20.0)
OPTIONAL = SensorSpec("camera_front_center", "camera", "/cfc/image_raw", 20.0, critical=False)


def test_unprobed_sensor_is_unknown_not_bad() -> None:
    status = evaluate(CAMERA, None)
    assert status.state == "unknown"
    assert status.hz is None


def test_absent_publisher_is_bad() -> None:
    status = evaluate(CAMERA, RateReading.missing(CAMERA.topic, error="no publisher"))
    assert status.state == "bad"
    assert status.detail == "no publisher"


def test_advertised_but_silent_is_bad() -> None:
    reading = RateReading(
        CAMERA.topic, present=True, hz=None, error="publisher advertised but silent"
    )
    assert evaluate(CAMERA, reading).state == "bad"


def test_on_rate_is_ok() -> None:
    status = evaluate(CAMERA, RateReading(CAMERA.topic, present=True, hz=19.8, samples=40))
    assert status.state == "ok"
    assert status.detail == ""


def test_off_rate_is_bad_and_says_what_it_saw() -> None:
    status = evaluate(CAMERA, RateReading(CAMERA.topic, present=True, hz=12.4, samples=25))
    assert status.state == "bad"
    assert "12.4 Hz" in status.detail and "20 Hz" in status.detail


def test_a_failing_optional_sensor_does_not_redden_its_block() -> None:
    statuses = [
        evaluate(CAMERA, RateReading(CAMERA.topic, present=True, hz=20.0)),
        evaluate(OPTIONAL, RateReading.missing(OPTIONAL.topic)),
    ]
    (block,) = group_into_blocks(statuses)
    assert block.state == "ok"
    # The optional sensor still shows its own red light in the list.
    assert [s.state for s in block.sensors] == ["ok", "bad"]
    assert (block.ok_count, block.required_count) == (1, 1)


def test_a_failing_required_sensor_reddens_its_block() -> None:
    statuses = [
        evaluate(CAMERA, RateReading.missing(CAMERA.topic)),
        evaluate(OPTIONAL, RateReading(OPTIONAL.topic, present=True, hz=20.0)),
    ]
    (block,) = group_into_blocks(statuses)
    assert block.state == "bad"
    assert (block.ok_count, block.required_count) == (0, 1)


def test_an_unprobed_required_sensor_leaves_the_block_unknown() -> None:
    (block,) = group_into_blocks([evaluate(CAMERA, None)])
    assert block.state == "unknown"


def _config_with_mock() -> Config:
    base = default_config()
    return Config(
        sensors=base.sensors,
        processes=base.processes,
        commands=base.commands,
        ros_backend="mock",
        probe_seconds=0.1,
    )


def test_monitor_sweep_populates_every_block() -> None:
    monitor = SensorMonitor(_config_with_mock(), MockBackend("typical"))
    assert monitor.refresh_async()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        blocks, meta = monitor.snapshot()
        if meta["last_checked"] is not None and not meta["sweeping"]:
            break
        time.sleep(0.05)

    blocks, meta = monitor.snapshot()
    assert meta["error"] is None
    # Stacked down a portrait screen in this order, GNSS first.
    assert [b.kind for b in blocks] == ["gnss", "camera", "lidar"]
    # The default mock scenario reproduces the two faults worth seeing: the GNSS
    # has fallen back to 1 Hz and the fisheye is off.
    gnss = next(b for b in blocks if b.kind == "gnss")
    assert gnss.state == "bad"
    cameras = next(b for b in blocks if b.kind == "camera")
    fisheye = next(s for s in cameras.sensors if s.name == "camera_front_center")
    assert fisheye.state == "bad"
    assert cameras.state == "ok"  # the fisheye is not required


def test_healthy_scenario_is_all_green() -> None:
    monitor = SensorMonitor(_config_with_mock(), MockBackend("healthy"))
    monitor.refresh_async()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        _, meta = monitor.snapshot()
        if meta["last_checked"] is not None and not meta["sweeping"]:
            break
        time.sleep(0.05)
    blocks, _ = monitor.snapshot()
    assert all(b.state == "ok" for b in blocks)
