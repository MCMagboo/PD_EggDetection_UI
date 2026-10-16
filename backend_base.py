"""The contract between the UI/controller and the hardware + model.

MockBackend and PiBackend both implement this, so the UI never changes when
you swap the fake data for the real camera, motor, UV-C relay and SOLOv2 model.
"""
from __future__ import annotations

import threading
from typing import Protocol

from .datatypes import EggResult


class Backend(Protocol):
    def prepare(self) -> None: ...
    def eggs_loaded(self) -> bool: ...
    def enclosure_closed(self) -> bool: ...
    def inspect_egg(self, index: int, stop: threading.Event) -> EggResult | None:
        """Rotate egg `index` through 360 deg, capture optical + IR, run the model.
        Return None if `stop` was set before finishing."""
    def set_defect_led(self, index: int, on: bool) -> None: ...
    def clear_leds(self) -> None: ...
    def beep(self) -> None: ...
    def uvc(self, on: bool) -> None: ...
    def safe_off(self) -> None:
        """Motor, UV-C and buzzer OFF. Defect LEDs stay on for identification."""
    def close(self) -> None: ...
