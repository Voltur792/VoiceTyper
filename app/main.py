"""Voice Typer — standalone dictation app.

Reuses the dictation core (src/) with a tkinter window and a tray icon.
Run:  python app/main.py            (window + tray)
      python app/main.py --smoke    (headless self-test, exit code 0/1)
"""

import logging
import queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models, store  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("voice-text-input.app")


def build_engine():
    from src.dictation import DictationEngine

    return DictationEngine(models.repo_root())


def smoke() -> int:
    """Headless self-test: settings, models, engine lifecycle."""
    settings = store.load()
    settings.enabled = True  # the saved toggle must not affect the self-test
    log.info("settings loaded: engine=%s start_word=%r",
             settings.engine, settings.start_word)
    log.info("models dir: %s (vosk present: %s)",
             models.models_dir(), models.vosk_model_present())
    engine = build_engine()
    engine.apply_settings(settings)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = engine.status()
        if status in ("listening", "dictating"):
            break
        if "missing" in status:
            log.error("vosk model missing — run the app once and download it")
            engine.stop()
            return 1
        time.sleep(0.3)
    status = engine.status()
    log.info("engine status: %s", status)
    engine.stop()
    if status not in ("listening", "dictating"):
        log.error("engine did not reach listening state")
        return 1
    log.info("smoke OK")
    return 0


def main() -> int:
    if "--smoke" in sys.argv:
        return smoke()

    import tkinter as tk

    from app.gui import AppWindow
    from app.tray import Tray

    engine = build_engine()
    root = tk.Tk()
    events: queue.Queue = queue.Queue()  # tray → tkinter thread commands

    def quit_app() -> None:
        events.put("quit")

    window = AppWindow(root, engine, on_quit=quit_app)
    tray = Tray(
        on_show=window.show,
        on_toggle=lambda: events.put("toggle"),
        on_quit=quit_app,
        get_enabled=lambda: window.enabled_var.get(),
    )
    tray.set_tooltip_hook(window)
    window.on_state_change = tray.update_state
    tray.start()

    def poll() -> None:
        try:
            while True:
                event = events.get_nowait()
                if event == "quit":
                    tray.stop()
                    window.quit()
                    root.destroy()  # without this the process never exits
                    return
                if event == "toggle":
                    window.toggle_from_tray()
        except queue.Empty:
            pass
        root.after(150, poll)

    root.after(150, poll)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
