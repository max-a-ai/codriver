"""Ways of asking the car how fast its sensors are actually publishing.

Four backends, all behind `RateBackend`:

    mock      invented readings, so the UI can be developed off the car
    rclpy     subscribes directly, counts undeserialised messages (default)
    ros2cli   shells out to `ros2 topic hz`
    bag       records a short bag and divides message count by duration

`rclpy` is the one to trust. See README, "Measuring rates honestly".
"""

from .backend import RateBackend, RateReading, resolve_backend

__all__ = ["RateBackend", "RateReading", "resolve_backend"]
