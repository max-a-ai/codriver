"""Lifecycle rules: readiness, clean stop, exclusive groups, honest crashes."""

import time
from pathlib import Path

import pytest

from codriver.config import CommandSpec, ProcessSpec
from codriver.processes import ProcessConflictError, ProcessManager, ProcessState, run_command

# A child that announces itself, then idles until interrupted. `trap` proves the
# stop path really delivers SIGINT rather than killing the process outright.
SAYS_READY = [
    "bash",
    "-c",
    'trap "echo bye; exit 0" INT; echo starting; sleep 0.2; echo ready;'
    " while true; do sleep 0.1; done",
]
NEVER_EXITS = ["bash", "-c", 'trap "exit 0" INT; while true; do sleep 0.1; done']
DIES = ["bash", "-c", "echo boom >&2; exit 3"]


def _wait_for(
    manager: ProcessManager, name: str, state: ProcessState, timeout: float = 15.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = next(s for s in manager.statuses() if s.name == name)
        if current.state == state:
            return
        time.sleep(0.05)
    current = next(s for s in manager.statuses() if s.name == name)
    raise AssertionError(f"{name} stayed {current.state} ({current.detail}), wanted {state}")


def _manager(specs: list[ProcessSpec], tmp_path: Path) -> ProcessManager:
    return ProcessManager(specs, str(tmp_path / "logs"))


def test_process_is_initializing_until_it_reports_ready(tmp_path: Path) -> None:
    spec = ProcessSpec("pose", "Pose", SAYS_READY, ready_pattern="ready", ready_after_seconds=30.0)
    manager = _manager([spec], tmp_path)
    manager.start("pose")
    # It is up immediately but must not claim to be running yet.
    assert next(s for s in manager.statuses() if s.name == "pose").state == "initializing"
    _wait_for(manager, "pose", "running")
    manager.stop("pose")
    _wait_for(manager, "pose", "idle")


def test_a_process_without_a_marker_goes_green_after_its_grace(tmp_path: Path) -> None:
    spec = ProcessSpec("rviz", "RViz2", NEVER_EXITS, ready_after_seconds=0.3)
    manager = _manager([spec], tmp_path)
    manager.start("rviz")
    _wait_for(manager, "rviz", "running")
    manager.stop("rviz")
    _wait_for(manager, "rviz", "idle")


def test_stopping_sends_sigint_so_the_child_can_close_cleanly(tmp_path: Path) -> None:
    spec = ProcessSpec("recording", "Recording", SAYS_READY, ready_pattern="ready")
    manager = _manager([spec], tmp_path)
    manager.start("recording")
    _wait_for(manager, "recording", "running")
    manager.stop("recording")
    _wait_for(manager, "recording", "idle")
    # The child's own SIGINT handler ran, which is what keeps a bag readable.
    assert any("bye" in line for line in manager.log_tail("recording"))


def test_recording_and_rviz_cannot_run_together(tmp_path: Path) -> None:
    specs = [
        ProcessSpec("recording", "Recording", NEVER_EXITS, exclusive_group="bag_io"),
        ProcessSpec("rviz", "RViz2", NEVER_EXITS, exclusive_group="bag_io"),
    ]
    manager = _manager(specs, tmp_path)
    manager.start("recording")
    with pytest.raises(ProcessConflictError, match="cannot do both"):
        manager.start("rviz")
    # The UI needs to know which one is holding the group, to grey out the other.
    rviz = next(s for s in manager.statuses() if s.name == "rviz")
    assert rviz.blocked_by == "recording"
    manager.stop("recording")
    _wait_for(manager, "recording", "idle")
    manager.start("rviz")
    _wait_for(manager, "rviz", "running")
    manager.stop("rviz")


def test_inference_may_run_alongside_a_recording(tmp_path: Path) -> None:
    specs = [
        ProcessSpec("recording", "Recording", NEVER_EXITS, exclusive_group="bag_io"),
        ProcessSpec("detection", "Detection", NEVER_EXITS, ready_after_seconds=0.2),
    ]
    manager = _manager(specs, tmp_path)
    manager.start("recording")
    manager.start("detection")
    _wait_for(manager, "detection", "running")
    _wait_for(manager, "recording", "running")
    manager.stop_all()


def test_a_process_that_exits_on_its_own_is_crashed(tmp_path: Path) -> None:
    manager = _manager([ProcessSpec("detection", "Detection", DIES)], tmp_path)
    manager.start("detection")
    _wait_for(manager, "detection", "crashed")
    status = next(s for s in manager.statuses() if s.name == "detection")
    assert status.exit_code == 3
    assert "exited with code 3" in status.detail


def test_a_missing_script_is_crashed_and_says_so(tmp_path: Path) -> None:
    spec = ProcessSpec("pose", "Pose", [str(tmp_path / "not-here.sh")])
    manager = _manager([spec], tmp_path)
    manager.start("pose")
    status = next(s for s in manager.statuses() if s.name == "pose")
    assert status.state == "crashed"
    assert "could not start" in status.detail


def test_log_is_written_to_disk_as_well_as_kept_in_memory(tmp_path: Path) -> None:
    manager = _manager([ProcessSpec("detection", "Detection", DIES)], tmp_path)
    manager.start("detection")
    _wait_for(manager, "detection", "crashed")
    time.sleep(0.2)  # let the reader thread drain the pipe
    assert any("boom" in line for line in manager.log_tail("detection"))
    assert (tmp_path / "logs" / "detection.log").is_file()


def test_run_command_reports_output_and_exit_code() -> None:
    result = run_command(CommandSpec("om", "OM", ["bash", "-c", "echo done; exit 0"]))
    assert result.ok and result.exit_code == 0
    assert "done" in result.output


def test_run_command_survives_a_missing_script() -> None:
    result = run_command(CommandSpec("om", "OM", ["/definitely/not/here.sh"]))
    assert not result.ok
    assert "could not run" in result.output
