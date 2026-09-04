"""The HTTP surface, exercised against a real socket."""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from codriver.app import TABS, App
from codriver.config import Config, default_config
from codriver.server import PanelServer


@pytest.fixture()
def panel(tmp_path: Any) -> Iterator[str]:
    base = default_config()
    config = Config(
        sensors=base.sensors,
        processes=[],
        commands=base.commands,
        ros_backend="mock",
        probe_seconds=0.1,
        log_dir=str(tmp_path / "logs"),
    )
    app = App(config)
    app.start()
    server = PanelServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        app.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


def _post(url: str) -> Any:
    request = urllib.request.Request(url, method="POST", data=b"")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def test_index_is_served(panel: str) -> None:
    with urllib.request.urlopen(panel + "/", timeout=10) as response:
        body = response.read().decode()
    assert response.headers["Content-Type"].startswith("text/html")
    assert "<title>Codriver</title>" in body


def test_state_lists_the_five_tabs_with_one_placeholder(panel: str) -> None:
    state = _get(panel + "/api/state")
    assert [t["id"] for t in state["tabs"]] == [t["id"] for t in TABS]
    assert len(state["tabs"]) == 5
    placeholders = [t["id"] for t in state["tabs"] if t["kind"] == "placeholder"]
    assert placeholders == ["custom"]


def test_custom_tab_carries_its_three_sections(panel: str) -> None:
    # Map, prediction and planning are sections of one tab now, not three tabs.
    state = _get(panel + "/api/state")
    assert [s["id"] for s in state["custom_sections"]] == ["map", "prediction", "planning"]


def test_the_visualiser_is_grouped_with_monitoring(panel: str) -> None:
    # RViz moved off the recording tab, but the two still share an exclusive
    # group, so the rail pips have to follow it to its new home.
    state = _get(panel + "/api/state")
    assert state["groups"]["monitoring"] == ["rviz"]
    assert state["groups"]["recording"] == ["recording"]


def test_state_carries_the_three_sensor_blocks(panel: str) -> None:
    state = _get(panel + "/api/state")
    assert [b["kind"] for b in state["sensors"]["blocks"]] == ["gnss", "camera", "lidar"]
    assert state["sensors"]["backend"] == "mock"


def test_refresh_is_accepted(panel: str) -> None:
    assert "started" in _post(panel + "/api/sensors/refresh")


def test_running_a_command_returns_its_output(panel: str) -> None:
    # The default commands point at scripts that do not exist off the car, so
    # this asserts the failure is reported rather than swallowed.
    result = _post(panel + "/api/commands/om_normal_all")
    assert result["name"] == "om_normal_all"
    assert result["exit_code"] != 0


def test_unknown_names_are_404_not_500(panel: str) -> None:
    for path, method in (("/api/commands/nope", "POST"), ("/api/processes/nope/log", "GET")):
        request = urllib.request.Request(
            panel + path, method=method, data=b"" if method == "POST" else None
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        assert caught.value.code == 404


def test_every_tab_has_a_note_in_the_repo(panel: str) -> None:
    # The right-hand rail has one button per tab, and each has to open
    # something. These are shipped in the repo's instructions/ folder.
    for tab in TABS:
        payload = _get(f"{panel}/api/document/{tab['id']}")
        assert payload["exists"] is True, f"instructions/{tab['id']}.md is missing"
        assert payload["label"] == tab["label"]
        assert payload["path"].endswith(f"instructions/{tab['id']}.md")
        assert payload["text"].strip()


def test_a_note_for_an_unknown_tab_is_404(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(panel + "/api/document/nope", timeout=10)
    assert caught.value.code == 404


def test_a_missing_note_file_is_a_normal_answer(panel: str, tmp_path: Any) -> None:
    # Point the panel at an empty folder: a tab with no note must still answer.
    empty = tmp_path / "no-notes"
    empty.mkdir()
    payload = _get(panel + "/api/document/status")
    assert payload["exists"] is True  # the real folder, sanity check
    from codriver.app import App
    from codriver.config import Config, default_config

    base = default_config()
    app = App(Config(base.sensors, [], [], instructions_dir=str(empty)))
    missing = app.document("custom")
    assert missing["exists"] is False
    assert "No notes yet" in missing["text"]


def test_static_traversal_is_refused(panel: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(panel + "/../pyproject.toml", timeout=10)
    assert caught.value.code == 404
