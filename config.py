"""Central settings. Edit values here instead of hunting through the code."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    egg_count: int = 10               # eggs per tray (Table 1-1)
    uvc_seconds: int = 30             # UV-C exposure per run (Figure 2-11)
    auto_uvc: bool = True             # start UV-C automatically when cracked eggs are found (operator can toggle)
    detect_threshold: float = 0.18    # SOLOv2 validation-calibrated threshold (Table 2-4)
    screen_w: int = 800               # used only in windowed mode; fullscreen reads the real screen
    screen_h: int = 480
    fullscreen: bool = True
    time_scale: float = 1.0           # <1.0 speeds up the mock backend for demos/tests


# BCM pin numbers. PLACEHOLDERS: edit to match your schematic (Figure 2-3).
PINS = {
    "backlight": 5,            # LED transillumination array (via driver/relay)
    "uvc_relay": 6,            # UV-C module (optocoupler relay)
    "tray_motor": 13,          # rotary tray motor relay
    "buzzer": 19,              # 70-85 dB alert
    "door_switch": 26,         # enclosure interlock; pressed = door closed
    "defect_leds": [2, 3, 4, 14, 15, 17, 18, 22, 23, 24],  # one per tray slot
}
