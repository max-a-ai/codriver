"""Entry point: `python -m codriver` or `codriver`."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import webbrowser
from collections.abc import Sequence
from dataclasses import replace
from types import FrameType

from .app import App
from .config import ConfigError, default_config, dump_config, load_config
from .server import PanelServer


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="codriver",
        description="In-car panel for starting demos and checking sensor health.",
    )
    parser.add_argument("--host", help="bind address (default from config)")
    parser.add_argument("--port", type=int, help="port (default from config)")
    parser.add_argument(
        "--backend",
        choices=["auto", "mock", "rclpy", "ros2cli", "bag"],
        help="how to measure sensor rates; overrides the config",
    )
    parser.add_argument("--open", action="store_true", help="open a browser once up")
    parser.add_argument(
        "--dump-config",
        action="store_true",
        help="print the effective config as JSON and exit",
    )
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="with --dump-config, print the built-in defaults instead of the loaded config",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    try:
        config = default_config() if args.defaults else load_config()
    except ConfigError as exc:
        print(f"codriver: {exc}", file=sys.stderr)
        return 2

    if args.dump_config:
        sys.stdout.write(dump_config(config))
        return 0

    overrides = {}
    if args.host:
        overrides["host"] = args.host
    if args.port:
        overrides["port"] = args.port
    if args.backend:
        overrides["ros_backend"] = args.backend
    if overrides:
        config = replace(config, **overrides)

    app = App(config)
    app.start()
    server = PanelServer((config.host, config.port), app)
    url = f"http://{config.host}:{config.port}"
    print(f"codriver   {url}   (rates via {app.monitor.backend.name})")

    def shut_down(_signum: int, _frame: FrameType | None) -> None:
        # Ctrl-C on the panel has to take the recorder and RViz with it,
        # otherwise a stopped panel leaves a bag being written by a process
        # nobody can see any more.
        #
        # `shutdown()` blocks until `serve_forever()` has returned, and the
        # handler runs on the thread that is inside `serve_forever()`. Calling
        # it here directly deadlocks: the loop cannot finish because the thread
        # that would finish it is waiting for the loop. So it goes to a thread
        # of its own, which is the only supported way to stop one of these
        # servers from the inside.
        print("\ncodriver   stopping children and shutting down")
        threading.Thread(target=server.shutdown, name="shutdown", daemon=True).start()

    signal.signal(signal.SIGINT, shut_down)
    signal.signal(signal.SIGTERM, shut_down)

    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        app.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
