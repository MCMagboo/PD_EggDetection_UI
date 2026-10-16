"""Touchscreen UI (CustomTkinter), laid out after Figure 2-11 of the design paper.

Screen: optical | infrared | XGrad-CAM heatmap, result + confidence, UV-C panel
(auto-on-cracks switch + manual RUN UV-C with tap-again confirm), 10-egg tray strip
(tap an egg to review it), and big Start / Stop / Reset buttons.
Widgets are only touched from the main thread; the worker thread talks through a queue.
"""
from __future__ import annotations

import queue
import time

import customtkinter as ctk
from PIL import Image

from .backend_base import Backend
from .config import Config
from .controller import InspectionController
from .datatypes import EggResult, Summary, UvcOutcome

C = {
    "bg": "#EEF1F5", "card": "#FFFFFF", "text": "#1F2933", "muted": "#6B7785", "line": "#D5DAE1",
    "idle": "#C9CFD8", "dark": "#101418", "blue": "#2F6DB5", "green": "#2E9E5B",
    "red": "#C62828", "amber": "#D98200", "uv": "#6B46C1", "slate": "#5B6673",
}
FONT = "DejaVu Sans"
TRAY_COLORS = {"pending": C["idle"], "ok": C["green"], "bad": C["red"]}
UVC_CONFIRM_MS = 3000                     # second tap must land within this window


def _darker(color: str, f: float = 0.85) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"#{int(r * f):02x}{int(g * f):02x}{int(b * f):02x}"


class ImagePanel(ctk.CTkFrame):
    def __init__(self, master, title, size, font_title, font_body):
        super().__init__(master, fg_color=C["card"], border_color=C["line"], border_width=1, corner_radius=10)
        self.size, self._img = size, None
        self._blank = ctk.CTkImage(Image.new("RGB", size, C["dark"]), size=size)   # avoids CTk's image=None bug
        ctk.CTkLabel(self, text=title, text_color=C["muted"], font=font_title, height=0).pack(
            anchor="w", padx=10, pady=(5, 2))
        self.view = ctk.CTkLabel(self, text="", image=self._blank, width=size[0], height=size[1],
                                 fg_color=C["dark"], text_color="#8A94A0", font=font_body, corner_radius=0)
        self.view.pack(padx=8, pady=(0, 8))

    def show(self, img: Image.Image | None, empty_text: str = "No image") -> None:
        if img is None:
            self._img = None
            self.view.configure(image=self._blank, text=empty_text)
            return
        self._img = ctk.CTkImage(img, size=self.size)
        self.view.configure(image=self._img, text="")


class TrayStrip(ctk.CTkCanvas):
    def __init__(self, master, count, height, font, on_pick):
        super().__init__(master, height=height, bg=C["card"], highlightthickness=0)
        self.count, self.font, self.on_pick = count, font, on_pick
        self.states = ["pending"] * count
        self.selected: int | None = None
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._click)

    def set_state(self, i: int, state: str) -> None:
        self.states[i] = state
        self.redraw()

    def select(self, i: int | None) -> None:
        self.selected = i
        self.redraw()

    def reset(self) -> None:
        self.states, self.selected = ["pending"] * self.count, None
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        cell = w / self.count
        r = min(cell, h) / 2 - 5
        for i, state in enumerate(self.states):
            cx, cy = cell * (i + 0.5), h / 2
            if i == self.selected:                                  # dark ring drawn outside the coloured dot
                self.create_oval(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4, outline=C["text"], width=2)
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=TRAY_COLORS[state], outline="")
            self.create_text(cx, cy, text=str(i + 1), fill="white", font=self.font)

    def _click(self, event) -> None:
        i = int(event.x // (max(self.winfo_width(), 1) / self.count))
        if 0 <= i < self.count and self.states[i] != "pending":
            self.on_pick(i)


class App(ctk.CTk):
    def __init__(self, cfg: Config, backend: Backend):
        ctk.deactivate_automatic_dpi_awareness()      # 1 widget px = 1 screen px, so the layout math holds
        ctk.set_appearance_mode("light")
        super().__init__(fg_color=C["bg"])
        self.cfg, self.backend = cfg, backend
        self.events: queue.Queue = queue.Queue()
        self.ctrl = InspectionController(backend, cfg, self.events)
        self.results: dict[int, EggResult] = {}
        self.auto_uvc = ctk.BooleanVar(value=cfg.auto_uvc)
        self._fonts: dict[tuple[int, bool], ctk.CTkFont] = {}
        self._confirm_job: str | None = None
        self._uvc_elapsed = 0
        self.title("Duck Egg Inspector")
        self._setup_window()
        self.s = self.H / 480                          # scale factor so 1024x600 etc. also fit
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.bind("<Escape>", lambda e: self._quit())
        self._reset_view()
        self._set_running(False)
        self.after(40, self._poll)
        self._tick_clock()

    # ---------------------------------------------------------------- window
    def _setup_window(self) -> None:
        if self.cfg.fullscreen:
            self.attributes("-fullscreen", True)
            try:
                self.configure(cursor="none")          # hide the mouse pointer on a touchscreen
            except Exception:
                pass
            self.update_idletasks()
            self.W, self.H = self.winfo_screenwidth(), self.winfo_screenheight()
        else:
            self.W, self.H = self.cfg.screen_w, self.cfg.screen_h
            self.geometry(f"{self.W}x{self.H}")

    def _f(self, size: int, bold: bool = False) -> ctk.CTkFont:
        """Font sized in points (like the old Tk UI); CTkFont takes pixels, hence the 1.33."""
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = ctk.CTkFont(FONT, max(9, round(size * 1.33 * self.s)), "bold" if bold else "normal")
        return self._fonts[key]

    def _px(self, n: int) -> int:
        return max(1, int(n * self.s))

    # ----------------------------------------------------------------- build
    def _build(self) -> None:
        pad = self._px(10)
        self._build_header(pad)
        self._build_buttons(pad)                       # packed at the bottom first so it never gets squeezed out
        self._build_images(pad)
        self._build_cards(pad)
        self._build_tray(pad)

    def _card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, fg_color=C["card"], border_color=C["line"], border_width=1,
                            corner_radius=self._px(10))

    def _row(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)

    def _label(self, parent, text="", size=10, bold=False, fg=None) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, text_color=fg or C["text"], font=self._f(size, bold), height=0)

    def _chip(self, parent, size=9) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text="", text_color="white", fg_color=C["idle"], font=self._f(size, True),
                            corner_radius=self._px(10), height=self._px(20), padx=self._px(6))

    def _button(self, parent, text, cmd, size=14, height=52) -> ctk.CTkButton:
        return ctk.CTkButton(parent, text=text, command=cmd, font=self._f(size, True), height=self._px(height),
                             corner_radius=self._px(10), text_color="white", text_color_disabled="#F4F6F8")

    def _build_header(self, pad: int) -> None:
        bar = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=0)
        bar.pack(fill="x", pady=(0, pad))
        self._label(bar, "Duck Egg Inspection + UV-C", 14, True).pack(side="left", padx=pad, pady=self._px(6))
        self.exit_btn = self._button(bar, "EXIT", self._quit, size=9, height=24)   # touchscreen has no Esc key
        self.exit_btn.configure(width=self._px(56), corner_radius=self._px(6))
        self.exit_btn.pack(side="right", padx=(0, pad))
        self.clock = self._label(bar, "", 11, fg=C["muted"])
        self.clock.pack(side="right", padx=pad)
        self.chip = self._chip(bar, 10)
        self.chip.pack(side="right", padx=pad)
        self.status = self._label(bar, "", 11, fg=C["muted"])
        self.status.pack(side="right")

    def _build_images(self, pad: int) -> None:
        gap = pad
        outer = (self.W - 2 * pad - 2 * gap) // 3
        inner = outer - 18                                  # border + inner padding
        size = (inner, int(inner * 0.48))                   # short images leave room for the tray row on 480 px screens
        row = self._row(self)
        row.pack(fill="x", padx=pad, pady=(0, pad))
        specs = [("OPTICAL (TRANSILLUMINATED)", "optical"), ("INFRARED", "thermal"), ("XGRAD-CAM HEATMAP", "heat")]
        self.panels = {}
        for col, (title, key) in enumerate(specs):
            panel = ImagePanel(row, title, size, self._f(8, True), self._f(10))
            panel.grid(row=0, column=col, padx=(0 if col == 0 else gap // 2, 0 if col == 2 else gap // 2))
            self.panels[key] = panel
        row.columnconfigure((0, 1, 2), weight=1, uniform="img")

    def _build_cards(self, pad: int) -> None:
        row = self._row(self)
        row.pack(fill="x", padx=pad, pady=(0, pad))
        row.columnconfigure(0, weight=3, uniform="card")
        row.columnconfigure(1, weight=2, uniform="card")
        self._build_result_card(row).grid(row=0, column=0, sticky="nsew", padx=(0, pad // 2))
        self._build_uvc_card(row).grid(row=0, column=1, sticky="nsew", padx=(pad // 2, 0))

    def _build_result_card(self, parent) -> ctk.CTkFrame:
        card = self._card(parent)
        top = self._row(card)
        top.pack(fill="x", padx=12, pady=(8, 0))
        self._label(top, "INSPECTION RESULT", 8, True, C["muted"]).pack(side="left")
        self.egg_tag = self._label(top, "", 9, True, C["muted"])
        self.egg_tag.pack(side="right")
        mid = self._row(card)
        mid.pack(fill="x", padx=12)
        self.verdict = self._label(mid, "", 22, True)
        self.verdict.pack(side="left")
        self.detail = self._label(mid, "", 10, fg=C["muted"])
        self.detail.pack(side="left", padx=12)
        row = self._row(card)
        row.pack(fill="x", padx=12)
        self._label(row, "Confidence", 9, fg=C["muted"]).pack(side="left")
        self.conf_val = self._label(row, "", 10, True)
        self.conf_val.pack(side="right")
        self.conf_bar = ctk.CTkProgressBar(card, height=self._px(10), fg_color=C["idle"], corner_radius=self._px(5))
        self.conf_bar.pack(fill="x", padx=12, pady=(4, 10))
        return card

    def _build_uvc_card(self, parent) -> ctk.CTkFrame:
        card = self._card(parent)
        top = self._row(card)
        top.pack(fill="x", padx=12, pady=(8, 0))
        self._label(top, "UV-C DISINFECTION", 8, True, C["muted"]).pack(side="left")
        self.uvc_chip = self._chip(top, 8)
        self.uvc_chip.pack(side="right")
        mid = self._row(card)
        mid.pack(fill="x", padx=12, pady=(2, 0))
        self.uvc_val = self._label(mid, "", 15, True)
        self.uvc_val.pack(side="left")
        self.auto_switch = ctk.CTkSwitch(mid, text="Auto on cracks", variable=self.auto_uvc,
                                         command=self._toggle_auto, font=self._f(9), text_color=C["text"],
                                         progress_color=C["uv"], switch_width=self._px(40),
                                         switch_height=self._px(20), height=self._px(24))
        self.auto_switch.pack(side="right")
        self.uvc_bar = ctk.CTkProgressBar(card, height=self._px(10), fg_color=C["idle"], corner_radius=self._px(5))
        self.uvc_bar.pack(fill="x", padx=12, pady=(4, 6))
        self.uvc_btn = self._button(card, "RUN UV-C", self._btn_uvc, size=11, height=34)
        self.uvc_btn.pack(fill="x", padx=12, pady=(0, 10))
        return card

    def _build_tray(self, pad: int) -> None:
        card = self._card(self)
        card.pack(fill="x", padx=pad, pady=(0, pad))
        top = self._row(card)
        top.pack(fill="x", padx=12, pady=(6, 0))
        self._label(top, "TRAY  (tap an egg to review it)", 8, True, C["muted"]).pack(side="left")
        self.timing = self._label(top, "", 9, True, C["muted"])
        self.timing.pack(side="right")
        self.tray = TrayStrip(card, self.cfg.egg_count, self._px(44), self._f(11, True), self._show_egg)
        self.tray.pack(fill="x", padx=12, pady=2)
        self.message = self._label(card, "", 10, True)
        self.message.pack(anchor="w", padx=12, pady=(0, 6))

    def _build_buttons(self, pad: int) -> None:
        row = self._row(self)
        row.pack(side="bottom", fill="x", padx=pad, pady=(0, pad))
        row.columnconfigure((0, 1, 2), weight=1, uniform="btn")
        self.btns = {}
        for col, (key, text, cmd) in enumerate([("start", "START", self._btn_start),
                                                ("stop", "STOP", self._btn_stop),
                                                ("reset", "RESET", self._btn_reset)]):
            btn = self._button(row, text, cmd)
            btn.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else pad // 2, 0 if col == 2 else pad // 2))
            self.btns[key] = btn

    # --------------------------------------------------------------- display
    def _set_chip(self, text: str, color: str) -> None:
        self.chip.configure(text=text, fg_color=color)

    def _set_message(self, text: str, color: str | None = None) -> None:
        self.message.configure(text=text, text_color=color or C["text"])

    @staticmethod
    def _style(btn: ctk.CTkButton, color: str, enabled: bool) -> None:
        btn.configure(state="normal" if enabled else "disabled",
                      fg_color=color if enabled else C["idle"], hover_color=_darker(color))

    def _set_running(self, running: bool) -> None:
        self._style(self.btns["start"], C["blue"], not running)
        self._style(self.btns["stop"], C["red"], running)
        self._style(self.btns["reset"], C["slate"], not running)
        self._style(self.uvc_btn, C["uv"], not running)
        self._style(self.exit_btn, C["slate"], not running)

    def _reset_view(self) -> None:
        self.results.clear()
        self.tray.reset()
        self.panels["optical"].show(None, "Optical")
        self.panels["thermal"].show(None, "Infrared")
        self.panels["heat"].show(None, "XGrad-CAM")
        self.verdict.configure(text="-", text_color=C["muted"])
        self.detail.configure(text="Waiting for inspection")
        self.egg_tag.configure(text="")
        self.conf_val.configure(text="-")
        self._set_bar(self.conf_bar, 0, C["idle"])
        self._set_uvc(0, "WAITING", C["idle"])
        self.timing.configure(text="")
        self.status.configure(text="")
        self._set_message("")
        self._set_chip("READY", C["blue"])

    @staticmethod
    def _set_bar(bar: ctk.CTkProgressBar, frac: float, color: str) -> None:
        frac = max(0.0, min(1.0, frac))
        bar.configure(progress_color=color if frac > 0 else C["idle"])   # CTk draws a stub dot at 0
        bar.set(frac)

    def _set_uvc(self, elapsed: int, chip: str, color: str) -> None:
        total = self.cfg.uvc_seconds
        self._uvc_elapsed = elapsed
        self.uvc_val.configure(text=f"{elapsed} / {total} s")
        self._set_bar(self.uvc_bar, elapsed / total, color)
        self.uvc_chip.configure(text=chip, fg_color=color)

    def _show_uvc_outcome(self, o: UvcOutcome, cracks: bool) -> None:
        if o.status == "completed":
            self._set_uvc(self.cfg.uvc_seconds, "COMPLETED", C["green"])
        elif o.status == "skipped":
            self._set_uvc(0, "PENDING" if cracks else "NOT NEEDED", C["amber"] if cracks else C["muted"])
        else:                                          # interrupted | blocked
            self._set_uvc(self._uvc_elapsed, o.status.upper(), C["amber"])

    def _show_egg(self, i: int) -> None:
        r = self.results[i]
        self.tray.select(i)
        self.panels["optical"].show(r.optical)
        self.panels["thermal"].show(r.thermal)
        self.panels["heat"].show(r.heatmap, "No defect: no heatmap")
        bad = r.defective
        self.verdict.configure(text="REJECT" if bad else "ACCEPT", text_color=C["red"] if bad else C["green"])
        self.detail.configure(text="Micro-fissure detected" if bad else "No micro-fissure detected")
        self.egg_tag.configure(text=f"Egg {i + 1}/{self.cfg.egg_count}")
        self.conf_val.configure(text=f"{r.confidence * 100:.1f}%")
        self._set_bar(self.conf_bar, r.confidence, C["red"] if bad else C["green"])

    # --------------------------------------------------------------- buttons
    def _btn_start(self) -> None:
        self._cancel_confirm()
        self._reset_view()
        self._set_running(True)
        self._set_chip("RUNNING", C["blue"])
        self.ctrl.start()

    def _btn_stop(self) -> None:
        self.ctrl.stop()                               # UV-C is cut by the controller within ~50 ms
        self.status.configure(text="Stopping...")

    def _btn_reset(self) -> None:
        if self.ctrl.running:
            return
        self._cancel_confirm()
        self.backend.clear_leds()
        self._reset_view()

    def _btn_uvc(self) -> None:
        """Manual UV-C. First tap arms, second tap within UVC_CONFIRM_MS starts the lamp."""
        if self.ctrl.running:
            return
        if self._confirm_job is None:
            self.uvc_btn.configure(text="TAP AGAIN TO START", fg_color=C["amber"], hover_color=_darker(C["amber"]))
            self._confirm_job = self.after(UVC_CONFIRM_MS, self._cancel_confirm)
            return
        self._cancel_confirm()
        self._set_running(True)
        self._set_uvc(0, "STARTING", C["uv"])
        self._set_chip("UV-C", C["uv"])
        self._set_message("Manual UV-C running. Keep the chamber door closed.", C["uv"])
        self.ctrl.start_uvc()

    def _cancel_confirm(self) -> None:
        if self._confirm_job is not None:
            self.after_cancel(self._confirm_job)
            self._confirm_job = None
        self.uvc_btn.configure(text="RUN UV-C")
        self._style(self.uvc_btn, C["uv"], not self.ctrl.running)

    def _toggle_auto(self) -> None:
        self.ctrl.auto_uvc = bool(self.auto_uvc.get())   # picked up when the current inspection ends

    # ---------------------------------------------------------------- events
    def _poll(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                getattr(self, f"_ev_{ev.kind}")(ev.data)
        except queue.Empty:
            pass
        self.after(40, self._poll)

    def _ev_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _ev_egg(self, r: EggResult) -> None:
        self.results[r.index] = r
        self.tray.set_state(r.index, "bad" if r.defective else "ok")
        self._show_egg(r.index)

    def _ev_uvc(self, data: tuple[int, int]) -> None:
        self._set_uvc(data[0], "RUNNING", C["uv"])
        self._set_chip("UV-C", C["uv"])
        self.status.configure(text="UV-C treatment")

    def _ev_done(self, s: Summary) -> None:
        cracks = bool(s.defective)
        self._show_uvc_outcome(s.uvc, cracks)
        settled = not cracks or s.uvc.status == "completed"
        self._set_chip("DONE" if settled else "CHECK", C["green"] if settled else C["amber"])
        self.timing.configure(text=f"Inspection time: {s.inspection_s:.1f} s")
        if cracks:
            flagged = ", ".join(f"#{i + 1}" for i in s.defective)
            tail = "UV-C completed." if s.uvc.status == "completed" else s.uvc.note
            self._set_message(f"Remove flagged eggs (LED on): {flagged}. {tail}", C["red"])
        else:
            self._set_message(f"No micro-fissures found. {s.uvc.note}", C["green"])
        self.status.configure(text="Finished")

    def _ev_uvc_done(self, o: UvcOutcome) -> None:
        self._show_uvc_outcome(o, cracks=False)
        ok = o.status == "completed"
        self._set_chip("UV-C DONE" if ok else "CHECK", C["green"] if ok else C["amber"])
        self._set_message("Manual UV-C completed." if ok else o.note, C["green"] if ok else C["amber"])
        self.status.configure(text="")

    def _ev_stopped(self, _=None) -> None:
        self._set_chip("STOPPED", C["amber"])
        self._set_message("Stopped by operator before the batch finished.", C["amber"])
        self.status.configure(text="")

    def _ev_error(self, msg: str) -> None:
        self._set_chip("ERROR", C["red"])
        self._set_message(msg, C["red"])
        self.status.configure(text="")

    def _ev_finished(self, _=None) -> None:
        self._set_running(False)

    # ------------------------------------------------------------------ misc
    def _tick_clock(self) -> None:
        self.clock.configure(text=time.strftime("%H:%M"))
        self.after(1000, self._tick_clock)

    def _quit(self) -> None:
        self.ctrl.stop()
        self.ctrl.join()
        self.backend.close()
        self.destroy()
