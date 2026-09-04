"""Which sensors go into the next bag.

The recording tab is a set of switches, one per camera and one per lidar, plus
group switches that flip a whole column at once. What comes out is a list of
topics, handed to the recording script as arguments, so adapting the script is a
matter of accepting `"$@"` rather than editing a hard-coded topic list.

Three rules the switches encode:

*   A camera is two topics. An `image_raw` recorded without its `camera_info` is
    a bag nobody can calibrate afterwards, so the two are never separable.
*   The default is the sensors that matter: every camera except the front-centre
    fisheye, every lidar except the two bumper units. The optional ones sit at
    the bottom of their column and start off, so recording one is always a
    deliberate act.
*   The GNSS has no switch. It is small, it is always wanted, and a recording
    that quietly lost it is worthless.
"""

from __future__ import annotations

import threading
from typing import Any, Literal

from .config import SensorSpec

#: on = every member selected, off = none, partial = some. Group buttons show
#: partial so "all cameras" being half-lit is visible rather than a lie.
ToggleState = Literal["on", "off", "partial"]

#: The columns of switches, in the order they are drawn, and the group buttons
#: that sit above each one.
_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("camera", "Cameras", "cameras", "cameras_required"),
    ("lidar", "Lidar", "lidars", "lidars_required"),
)

GROUP_ALL = "all"


class RecordingSelection:
    """The set of switched-on sensors, and the topic list it resolves to."""

    def __init__(self, sensors: list[SensorSpec]) -> None:
        self._sensors = list(sensors)
        #: The ones that get a switch: cameras and lidars that are not pinned on.
        self._switchable = [
            s for s in self._sensors if s.kind in ("camera", "lidar") and not s.always_record
        ]
        self._lock = threading.Lock()
        # Default: everything that matters, nothing that does not.
        self._selected: set[str] = {s.name for s in self._switchable if s.critical}

    # --- groups ---

    def _members(self, key: str) -> list[str]:
        """The sensors a button covers. KeyError if the button does not exist."""
        if key == GROUP_ALL:
            return [s.name for s in self._switchable]
        for kind, _label, all_key, required_key in _COLUMNS:
            if key == all_key:
                return [s.name for s in self._switchable if s.kind == kind]
            if key == required_key:
                return [s.name for s in self._switchable if s.kind == kind and s.critical]
        if any(s.name == key for s in self._switchable):
            return [key]
        raise KeyError(key)

    def _state(self, members: list[str], selected: set[str]) -> ToggleState:
        if not members:
            return "off"
        hit = sum(name in selected for name in members)
        if hit == len(members):
            return "on"
        return "off" if hit == 0 else "partial"

    # --- switching ---

    def toggle(self, key: str) -> None:
        """Flip a switch. A group that is fully on goes off; anything else
        goes fully on, which is what makes a half-lit group button useful."""
        members = self._members(key)
        with self._lock:
            if all(name in self._selected for name in members):
                self._selected.difference_update(members)
            else:
                self._selected.update(members)

    def set_selected(self, names: list[str]) -> None:
        known = {s.name for s in self._switchable}
        unknown = set(names) - known
        if unknown:
            raise KeyError(sorted(unknown)[0])
        with self._lock:
            self._selected = set(names)

    # --- output ---

    def topics(self) -> list[str]:
        """Every topic the next recording should contain, in registry order and
        without duplicates."""
        with self._lock:
            selected = set(self._selected)
        out: list[str] = []
        for spec in self._sensors:
            if not (spec.always_record or spec.name in selected):
                continue
            for topic in spec.record_topics or (spec.topic,):
                if topic not in out:
                    out.append(topic)
        return out

    def snapshot(self, locked: bool) -> dict[str, Any]:
        with self._lock:
            selected = set(self._selected)

        def switch(spec: SensorSpec) -> dict[str, Any]:
            return {
                "name": spec.name,
                "state": "on" if spec.name in selected else "off",
                "topics": list(spec.record_topics or (spec.topic,)),
            }

        def group(key: str, label: str) -> dict[str, Any]:
            return {
                "key": key,
                "label": label,
                "state": self._state(self._members(key), selected),
            }

        columns = []
        for kind, label, all_key, required_key in _COLUMNS:
            members = [s for s in self._switchable if s.kind == kind]
            columns.append(
                {
                    "kind": kind,
                    "label": label,
                    "groups": [
                        group(all_key, f"All {label.lower()}"),
                        group(required_key, f"Required {label.lower()}"),
                    ],
                    "required": [switch(s) for s in members if s.critical],
                    "optional": [switch(s) for s in members if not s.critical],
                }
            )

        return {
            "locked": locked,
            "selected": sorted(selected),
            "topics": self.topics(),
            "all": group(GROUP_ALL, "All sensors"),
            "columns": columns,
            "always": [
                {"name": s.name, "topics": list(s.record_topics or (s.topic,))}
                for s in self._sensors
                if s.always_record
            ],
        }
