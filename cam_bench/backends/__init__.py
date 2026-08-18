from .base import CameraBackend, ControlSpec, DeviceInfo
from .gige import GigeBackend
from .opt import OptBackend
from .v4l2 import V4L2Backend

BACKENDS: dict[str, type[CameraBackend]] = {
    "v4l2": V4L2Backend,
    "opt": OptBackend,
    "gige": GigeBackend,
}

__all__ = ["CameraBackend", "ControlSpec", "DeviceInfo", "BACKENDS",
           "V4L2Backend", "OptBackend", "GigeBackend"]
