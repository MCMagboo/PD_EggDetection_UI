# This is A Project Design for Course CPE029/030 in Technological Institute of the Philippines by Group 24

# Duck Egg Inspector

Touchscreen app for the duck egg micro-fissure inspection + UV-C station (Raspberry Pi 5).
It inspects a 10-egg tray, flags cracked eggs (screen, LED, buzzer), shows the optical, infrared and
XGrad-CAM heatmap images, and runs UV-C disinfection.

The UI is built with [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) and laid out for an
800x480 touchscreen. It scales to larger screens such as 1024x600.

## Quick start (any PC, no hardware)

```bash
pip install customtkinter pillow numpy
# run from the folder that CONTAINS egg_inspector/
python -m egg_inspector --windowed --fast
```

The default `mock` backend generates fake candled-egg images, so the full flow works without a camera,
GPIO or model.

| Option | Meaning |
|---|---|
| `--backend mock\|pi` | `mock` = fake data (default); `pi` = real camera, GPIO, UV-C relay and model |
| `--windowed` | Run in a window instead of fullscreen |
| `--size 1024x600` | Window size when `--windowed` |
| `--fast` | Speed up the mock backend (demos/tests) |
| `--seed N` | Repeatable mock results |

## Install on the Raspberry Pi (desktop app)

1. Copy the whole `egg_inspector` folder somewhere permanent, e.g. `~/egg_inspector`. Keep that folder name;
   the icon runs the app from there.
2. Install:
   ```bash
   cd ~/egg_inspector
   bash deploy/install.sh
   ```
3. Double-tap **Egg Inspector** on the desktop (also in Menu > Accessories).

Re-run the installer to change options:

| Option | Meaning |
|---|---|
| *(none)* | Mock backend; works before the model and hardware are ready |
| `--backend pi` | Real hardware + model (needs the TODOs in `pi_backend.py` filled in first) |
| `--autostart` | Open the app automatically at login (kiosk mode) |
| `--no-apt` | Skip `apt-get` (offline or already installed) |
| `--uninstall` | Remove icons, autostart entry and venv; keeps the source folder |

The installer installs the system packages, creates a venv at `~/.local/share/egg_inspector/venv`
(with access to the apt-installed `picamera2`/`gpiozero`), and adds the desktop and menu icons.

- **Logs:** `~/.local/state/egg_inspector/app.log`. If the app crashes, an error box shows the last lines.
- **Single instance:** a second tap on the icon while the app is open does nothing.
- **Exit:** the **EXIT** button (top right) or Esc. EXIT is disabled during an inspection or UV-C run.

## Operating the station

| Control | What it does |
|---|---|
| **START** | Inspects all 10 eggs, then runs UV-C if cracks were found (see below) |
| **STOP** | Stops inspection or UV-C immediately |
| **RESET** | Clears the screen and the defect LEDs |
| **Tray dots** | Tap an inspected egg to review its images and result |
| **RUN UV-C** | Manual UV-C at any time. Tap once to arm (turns amber), tap again within 3 s to start |
| **Auto on cracks** | Switch: start UV-C automatically when a cracked egg is found |

### UV-C behaviour

- **Cracks found + auto on:** UV-C starts automatically after inspection.
- **Cracks found + auto off:** UV-C shows **PENDING**; the operator taps RUN UV-C.
- **No cracks:** UV-C is skipped (**NOT NEEDED**).
- **Default:** the switch's starting position is `auto_uvc` in `config.py`.

Safety rules in software:
- UV-C never starts with the chamber door open (**BLOCKED**).
- It stops within about 50 ms of STOP or the door opening (**INTERRUPTED**).
- It is always switched off when a run ends, including after errors.

**The hardware door interlock must also cut UV-C power on its own.** Don't rely on the software alone.

## Project layout

| File | Purpose |
|---|---|
| `__main__.py` | Command-line entry point; picks the backend |
| `config.py` | All settings: egg count, UV-C time, threshold, screen, GPIO pins |
| `ui.py` | CustomTkinter touchscreen UI (main thread only) |
| `controller.py` | Background worker: inspection cycle, UV-C policy and safety checks |
| `backend_base.py` | `Backend` interface that both backends implement |
| `mock_backend.py` | Fake images for development without hardware |
| `pi_backend.py` | Real camera, GPIO, UV-C relay and model (**model parts still TODO**) |
| `datatypes.py` | `EggResult`, `Summary`, `UvcOutcome`, `Event` |
| `deploy/` | Pi installer, launcher script, icon, pip requirements |

The UI never talks to hardware directly. The controller runs on a worker thread, calls the backend, and
sends events to the UI through a queue. You can swap the mock for the real backend without UI changes.

## Integrating the trained model

Fill in these methods in `pi_backend.py`:

| Method | Must do |
|---|---|
| `_load_model()` | Load the trained SOLOv2 weights |
| `_rotate_to(index, stop)` | Drive the tray to slot `index` and spin 360°; return `False` if `stop` is set |
| `_thermal_frame()` | Return a frame from the infrared camera as a PIL image |
| `_predict(optical)` | Return `(max crack score, score >= cfg.detect_threshold)` |
| `_explain(optical)` | XGrad-CAM on ResNet-50 layer 3, upsampled and overlaid on `optical` (PIL image) |

Checklist when the model is ready:

- **Threshold:** set `detect_threshold` in `config.py` to the value calibrated on your validation set.
- **Preprocessing:** must match training. The camera captures 1640x1232 RGB (configured in `PiBackend.__init__`);
  check resolution, crop, colour order and normalisation against your training pipeline.
- **Dependencies:** add PyTorch and your detection framework to `deploy/requirements.txt`. Test installing them
  on the Pi early; mmcv in particular can be hard to build on ARM.
- **Confidence display:** for a cracked egg the screen shows the raw crack score. With a low threshold, a correct
  reject can display a low percentage, so consider showing a calibrated value.
- **Speed:** inference runs on the worker thread, so slow models won't freeze the UI. Measure per-egg time on the
  Pi 5; it is shown as "Inspection time" after each batch.

### Known open items

- `PiBackend` imports the camera and GPIO libraries on start-up. The model therefore can't be tested on a PC
  without hardware yet. Splitting the model into its own module is planned.
- Only one optical frame is captured per egg after the 360° spin. Decide whether to capture several frames
  during the rotation, so cracks on the far side are not missed.
- `eggs_loaded()` always returns `True`; it needs a tray-presence sensor or camera check.
- GPIO pin numbers in `config.py` are placeholders; match them to the schematic.
