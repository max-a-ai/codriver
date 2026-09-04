"""Ctrl-C on the panel must exit and take its children with it.

This runs the real entry point in a real subprocess and sends it a real SIGINT,
because the bug this guards against only exists there: `shutdown()` blocks until
`serve_forever()` returns, so calling it from the signal handler's own thread
deadlocks and the panel hangs forever with a recorder still running.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

CHILD = ["bash", "-c", 'trap "exit 0" INT; echo ready; while true; do sleep 0.1; done']


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "codriver.json"
    path.write_text(
        json.dumps(
            {
                "ros_backend": "mock",
                "log_dir": str(tmp_path / "logs"),
                "sensors": [],
                "commands": [],
                "processes": [
                    {
                        "name": "recording",
                        "label": "Recording",
                        "command": CHILD,
                        "ready_pattern": "ready",
                    }
                ],
            }
        )
    )
    return path


def _post(port: int, path: str) -> None:
    import urllib.request

    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST", data=b"")
    urllib.request.urlopen(request, timeout=10).close()


def _wait_for_port(port: int, panel: subprocess.Popen[str], timeout: float = 20.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if panel.poll() is not None:
            raise AssertionError(f"panel exited early: {panel.communicate()[0]}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2).close()
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    raise AssertionError("panel never came up")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_sigint_exits_and_stops_children(tmp_path: Path) -> None:
    port = _free_port()
    panel = subprocess.Popen(
        [sys.executable, "-m", "codriver", "--port", str(port)],
        env={**os.environ, "CODRIVER_CONFIG": str(_config(tmp_path))},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        _wait_for_port(port, panel)
        _post(port, "/api/processes/recording/start")
        time.sleep(1.0)

        panel.send_signal(signal.SIGINT)
        try:
            output = panel.communicate(timeout=45)[0]
        except subprocess.TimeoutExpired:
            raise AssertionError("panel did not exit on SIGINT (the shutdown deadlock)") from None
        assert panel.returncode == 0
        assert "stopping children" in output
    finally:
        if panel.poll() is None:  # pragma: no cover - only on failure
            panel.kill()
            panel.wait(timeout=10)

    # The child was started in the panel's session; nothing of it may survive.
    leftovers = subprocess.run(
        ["pgrep", "-f", "trap .exit 0. INT"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert leftovers.stdout.strip() == ""
