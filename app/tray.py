"""System tray icon (pystray), started detached in the main thread.

`run_detached()` is the reliable way on Windows — `run()` in a background
thread leaves the icon invisible (learned from the sleep-pause-timer app).
The icon carries a small state dot: green = listening, grey = off.
"""

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

_BASE = (40, 90, 200, 255)      # microphone body
_ON = (63, 191, 111, 255)       # green dot
_OFF = (150, 154, 160, 255)     # grey dot


def _draw_icon(dot_rgba) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((22, 6, 42, 32), radius=9, fill=_BASE)
    d.rounded_rectangle((17, 27, 47, 36), radius=4, fill=_BASE)
    d.rectangle((28, 36, 36, 46), fill=_BASE)
    d.rounded_rectangle((21, 49, 43, 55), radius=2, fill=_BASE)
    d.ellipse((46, 44, 62, 60), fill=dot_rgba)
    return img


_IMAGES = {
    True: _draw_icon(_ON),
    False: _draw_icon(_OFF),
}


class Tray:
    def __init__(self, on_show, on_toggle, on_quit, get_enabled):
        self._get_enabled = get_enabled
        self._icon = Icon(
            "voice-text-input", _IMAGES[get_enabled()], "Голосовой наборщик",
            Menu(
                MenuItem("Открыть", default=True, action=on_show),
                MenuItem("Включено", action=on_toggle,
                         checked=lambda icon: get_enabled()),
                MenuItem("Выход", action=on_quit),
            ))
        self._started = False

    def set_tooltip_hook(self, window) -> None:
        """window: gui.AppWindow — its poller pushes status into the tooltip."""
        window.set_tooltip_hook(lambda text: setattr(self._icon, "title", text))

    def start(self) -> None:
        if not self._started:
            self._icon.run_detached()
            self._started = True

    def update_state(self) -> None:
        """Refresh the checkmark and the state dot after a toggle."""
        try:
            self._icon.icon = _IMAGES[self._get_enabled()]
            self._icon.update_menu()
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
