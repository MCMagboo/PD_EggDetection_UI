"""Run with:  python -m egg_inspector [--backend mock|pi] [--fake-vision] [--windowed] [--size 800x480] [--fast]"""
import argparse
import dataclasses
import logging

from .config import Config
from .ui import App


def main() -> None:
    ap = argparse.ArgumentParser(description="Duck egg inspection touchscreen app")
    ap.add_argument("--backend", choices=["mock", "pi"], default="mock",
                    help="mock = fake images (no model/hardware); pi = real camera/GPIO/model")
    ap.add_argument("--windowed", action="store_true", help="run in a window instead of fullscreen (for development)")
    ap.add_argument("--size", default="800x480", help="window size when --windowed, e.g. 1024x600")
    ap.add_argument("--fake-vision", action="store_true",
                    help="with --backend pi: real motors/LEDs/UV-C, synthetic images instead of camera + model")
    ap.add_argument("--fast", action="store_true", help="speed up the mock backend")
    ap.add_argument("--seed", type=int, default=None, help="random seed for the mock backend")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    w, h = (int(v) for v in args.size.lower().split("x"))
    cfg = Config(screen_w=w, screen_h=h, fullscreen=not args.windowed)
    if args.fast:
        cfg = dataclasses.replace(cfg, time_scale=0.25)

    if args.backend == "mock":
        from .mock_backend import MockBackend
        backend = MockBackend(cfg, args.seed)
    elif args.fake_vision:
        from .pi_backend import FakeVisionPiBackend
        backend = FakeVisionPiBackend(cfg)
    else:
        from .pi_backend import PiBackend
        backend = PiBackend(cfg)

    backend.prepare()
    App(cfg, backend).mainloop()


if __name__ == "__main__":
    main()
