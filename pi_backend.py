"""Real Raspberry Pi 5 backend. Fill in the NotImplementedError spots once the
model is trained and the wiring is final. Everything else (UI, flow, safety
logic) already works through the Backend contract.
"""
from __future__ import annotations

import threading
import time

from PIL import Image

from .config import PINS, Config
from .datatypes import EggResult


class PiBackend:
    def __init__(self, cfg: Config):
        from gpiozero import LED, Button, Buzzer, OutputDevice   # imported here so the mock runs anywhere
        from picamera2 import Picamera2

        self.cfg = cfg
        self.backlight = OutputDevice(PINS["backlight"])
        self.uvc_relay = OutputDevice(PINS["uvc_relay"])
        self.motor = OutputDevice(PINS["tray_motor"])
        self.buzzer = Buzzer(PINS["buzzer"])
        self.door = Button(PINS["door_switch"], pull_up=True)     # pressed = door closed (check your switch)
        self.defect_leds = [LED(p) for p in PINS["defect_leds"]]
        self.cam = Picamera2(0)
        self.cam.configure(self.cam.create_still_configuration(main={"size": (1640, 1232), "format": "RGB888"}))
        self.model = None

    # ---- lifecycle -------------------------------------------------------
    def prepare(self) -> None:
        self.cam.start()
        self.model = self._load_model()

    def close(self) -> None:
        self.safe_off()
        self.backlight.off()
        self.cam.stop()

    # ---- sensors ---------------------------------------------------------
    def eggs_loaded(self) -> bool:
        return True   # TODO: replace with your tray-presence sensor or a camera check

    def enclosure_closed(self) -> bool:
        return self.door.is_pressed

    # ---- inspection ------------------------------------------------------
    def inspect_egg(self, index: int, stop: threading.Event) -> EggResult | None:
        t0 = time.perf_counter()
        self.backlight.on()
        if not self._rotate_to(index, stop):
            return None
        optical = Image.fromarray(self.cam.capture_array()[..., ::-1])   # Picamera2 "RGB888" is BGR order
        thermal = self._thermal_frame()
        score, defective = self._predict(optical)
        heatmap = self._explain(optical) if defective else None
        return EggResult(index, defective, score if defective else 1 - score,
                         optical, thermal, heatmap, (time.perf_counter() - t0) * 1000)

    # ---- the pieces you still have to write ------------------------------
    def _load_model(self):
        raise NotImplementedError("Load the trained SOLOv2 weights (PyTorch) here")

    def _rotate_to(self, index: int, stop: threading.Event) -> bool:
        raise NotImplementedError("Drive the rotary tray to slot `index`; do a 360 deg spin; return False if stop is set")

    def _thermal_frame(self) -> Image.Image:
        raise NotImplementedError("Grab a frame from the infrared/thermal camera")

    def _predict(self, optical: Image.Image) -> tuple[float, bool]:
        raise NotImplementedError("Run SOLOv2; return (max crack score, score >= cfg.detect_threshold)")

    def _explain(self, optical: Image.Image) -> Image.Image:
        raise NotImplementedError("XGrad-CAM on ResNet-50 Layer 3 (1024x64x64), upsample, overlay on `optical`")

    # ---- outputs ---------------------------------------------------------
    def set_defect_led(self, index: int, on: bool) -> None:
        (self.defect_leds[index].on if on else self.defect_leds[index].off)()

    def clear_leds(self) -> None:
        for led in self.defect_leds:
            led.off()

    def beep(self) -> None:
        self.buzzer.beep(on_time=0.15, off_time=0.1, n=2, background=True)

    def uvc(self, on: bool) -> None:
        (self.uvc_relay.on if on else self.uvc_relay.off)()

    def safe_off(self) -> None:
        self.uvc_relay.off()
        self.motor.off()
        self.buzzer.off()
