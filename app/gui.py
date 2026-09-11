"""The app's main window (tkinter): Home tab with a big microphone toggle,
Settings tab with everything else, dark/light theme.

The window owns the DictationEngine: it applies settings on start and on
save, polls the engine status into the home screen and the tray tooltip, and
hides to the tray instead of closing.
"""

import logging
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageTk

from src.dictation import DictationEngine
from src.settings import ENGINES, WHISPER_MODELS, Settings

from . import models, store

log = logging.getLogger("voice-text-input.app")

STATUS_TEXT = {
    "off": "Выключено",
    "disabled": "Выключено",
    "listening": "Слушаю…",
    "dictating": "● Диктовка",
    "sending": "Отправка…",
    "vosk model missing (see models/)": "Нет модели Vosk — вкладка «Настройки»",
}

ENGINE_TEXT = {
    "faster-whisper": "faster-whisper (локально)",
    "vosk": "vosk (локально, лёгкий)",
    "yandex": "Яндекс SpeechKit (облако)",
    "openai": "OpenAI / совместимые (облако)",
    "google": "Google Cloud (облако)",
}

THEMES = {
    "dark": {
        "bg": "#1e1f22", "surface": "#2b2d31", "field": "#383a40",
        "fg": "#e8eaed", "muted": "#9aa0a6", "accent": "#4f8cff",
        "accent_fg": "#ffffff", "on": "#3fbf6f", "off": "#4a4d52",
        "border": "#3a3d42", "mic_glyph": "#ffffff",
    },
    "light": {
        "bg": "#f2f3f5", "surface": "#ffffff", "field": "#ffffff",
        "fg": "#1c1e21", "muted": "#5f6368", "accent": "#2f6fed",
        "accent_fg": "#ffffff", "on": "#1fa557", "off": "#b8bcc2",
        "border": "#d5d8dd", "mic_glyph": "#ffffff",
    },
}


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable container for the settings tab."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw", tags="inner")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", self._on_resize)
        self.inner.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.inner.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_resize(self, event) -> None:
        self.canvas.itemconfigure("inner", width=event.width)

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")


class AppWindow:
    def __init__(self, root: tk.Tk, engine: DictationEngine, on_quit):
        self.root = root
        self.engine = engine
        self.on_quit = on_quit
        self.app_cfg = store.load_app()
        self.settings = Settings.from_config(self.app_cfg)
        self.theme_name = self.app_cfg.get("theme", "dark")
        if self.theme_name not in THEMES:
            self.theme_name = "dark"
        self.enabled_var = tk.BooleanVar(value=self.settings.enabled)
        self.on_state_change: Callable[[], None] | None = None
        self._tooltip_hook = None
        self._download_cancel = threading.Event()

        root.title("Голосовой наборщик")
        root.minsize(560, 500)
        root.protocol("WM_DELETE_WINDOW", self._hide)
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._apply_theme()
        self._build()
        self._load_settings()
        self._start_engine()
        root.after(400, self._poll_status)

    # ── theme ────────────────────────────────────────────────────────────

    @property
    def theme(self) -> dict:
        return THEMES[self.theme_name]

    def _apply_theme(self) -> None:
        t = self.theme
        s = self.style
        self.root.configure(bg=t["bg"])
        s.configure(".", background=t["bg"], foreground=t["fg"],
                    fieldbackground=t["field"], bordercolor=t["border"],
                    lightcolor=t["surface"], darkcolor=t["surface"])
        s.configure("TFrame", background=t["bg"])
        s.configure("Surface.TFrame", background=t["surface"])
        s.configure("TLabel", background=t["bg"], foreground=t["fg"])
        s.configure("Muted.TLabel", background=t["bg"], foreground=t["muted"])
        s.configure("Status.TLabel", background=t["bg"], foreground=t["fg"],
                    font=("Segoe UI", 15, "bold"))
        s.configure("TLabelframe", background=t["bg"], bordercolor=t["border"])
        s.configure("TLabelframe.Label", background=t["bg"],
                    foreground=t["muted"], font=("Segoe UI", 9))
        s.configure("TButton", background=t["surface"], foreground=t["fg"],
                    bordercolor=t["border"], padding=[10, 5])
        s.map("TButton",
              background=[("pressed", t["field"]), ("active", t["field"])])
        # Tab buttons: same padding in every state, so switching tabs never
        # changes their size (ttk.Notebook in clam did).
        s.configure("Tab.TButton", background=t["surface"], foreground=t["muted"],
                    bordercolor=t["surface"], padding=[20, 9],
                    font=("Segoe UI", 10, "bold"))
        s.map("Tab.TButton",
              background=[("pressed", t["field"]), ("active", t["field"])],
              bordercolor=[("pressed", t["surface"]), ("active", t["surface"])])
        s.configure("TabActive.TButton", background=t["accent"],
                    foreground=t["accent_fg"], bordercolor=t["accent"],
                    padding=[20, 9], font=("Segoe UI", 10, "bold"))
        s.map("TabActive.TButton",
              background=[("pressed", t["accent"]), ("active", t["accent"])],
              bordercolor=[("pressed", t["accent"]), ("active", t["accent"])])
        s.configure("Accent.TButton", background=t["accent"], foreground=t["accent_fg"])
        s.map("Accent.TButton",
              background=[("pressed", t["accent"]), ("active", t["accent"])],
              foreground=[("active", t["accent_fg"])])
        s.configure("TEntry", fieldbackground=t["field"], foreground=t["fg"],
                    insertcolor=t["fg"], bordercolor=t["border"])
        s.configure("TCombobox", fieldbackground=t["field"], background=t["surface"],
                    foreground=t["fg"], arrowcolor=t["fg"], bordercolor=t["border"])
        s.map("TCombobox", fieldbackground=[("readonly", t["field"])],
              foreground=[("readonly", t["fg"])])
        s.configure("TCheckbutton", background=t["bg"], foreground=t["fg"],
                    indicatorbackground=t["field"], indicatorforeground=t["fg"],
                    bordercolor=t["border"], focuscolor=t["bg"])
        s.map("TCheckbutton",
              background=[("active", t["bg"])],
              indicatorbackground=[("selected", t["accent"]), ("pressed", t["accent"])],
              indicatorforeground=[("selected", t["accent_fg"])])
        s.configure("Horizontal.TProgressbar", background=t["accent"],
                    troughcolor=t["surface"], bordercolor=t["surface"])
        # root option for anything tk-native
        self.root.option_add("*Font", ("Segoe UI", 10))

    def _toggle_theme(self) -> None:
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.app_cfg["theme"] = self.theme_name
        store.save_app({**store.settings_fields(self.settings), **self.app_cfg})
        self._apply_theme()
        self.mic_canvas.configure(bg=self.theme["bg"])
        self._render_mic_images()

    # ── layout ───────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Custom tab bar: ttk.Notebook in clam resizes the selected tab,
        # which looked broken — flat buttons keep a fixed size.
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=8, pady=(8, 0))
        self.tab_buttons: dict[str, ttk.Button] = {}
        for name, title in (("home", "Главная"), ("settings", "Настройки")):
            btn = ttk.Button(header, text=title, style="Tab.TButton",
                             command=lambda n=name: self._show_tab(n))
            btn.pack(side="left", padx=(0, 6))
            self.tab_buttons[name] = btn
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.home_tab = ttk.Frame(body)
        self.settings_tab = ScrollableFrame(body)
        self.home_tab.grid(row=0, column=0, sticky="nsew")
        self.settings_tab.grid(row=0, column=0, sticky="nsew")
        self._build_home(self.home_tab)
        self._build_settings(self.settings_tab.inner)
        self._show_tab("home")

    def _show_tab(self, name: str) -> None:
        if name == "home":
            self.home_tab.tkraise()
        else:
            self.settings_tab.tkraise()
        for tab, btn in self.tab_buttons.items():
            btn.configure(style="TabActive.TButton" if tab == name else "Tab.TButton")

    def _build_home(self, parent) -> None:
        wrap = ttk.Frame(parent)
        wrap.pack(expand=True)
        self.mic_canvas = tk.Canvas(wrap, width=210, height=210,
                                    highlightthickness=0, bd=0,
                                    bg=self.theme["bg"], cursor="hand2")
        self.mic_canvas.pack(pady=(28, 10))
        self.mic_canvas.bind("<Button-1>", lambda e: self.toggle_from_tray())
        self._mic_item = self.mic_canvas.create_image(105, 105, image=None)
        self._mic_photos: dict[bool, ImageTk.PhotoImage] = {}
        self._render_mic_images()
        self.status_label = ttk.Label(wrap, text="—", style="Status.TLabel")
        self.status_label.pack()
        hint = ttk.Label(
            wrap, style="Muted.TLabel", justify="center",
            text="Скажите «напиши …» — текст печатается в активное окно\n"
                 "по мере речи. «отправить» — Enter и дальше без «напиши»,\n"
                 "«закончить» — завершить, «отмена» — стереть набранное.\n"
                 "Кликните по микрофону, чтобы включить или выключить.")
        hint.pack(pady=(14, 24))

    def _render_mic_images(self) -> None:
        """Anti-aliased microphone button, drawn with PIL at 4x and downscaled."""
        t = self.theme
        size = 210
        scale = 4
        big = size * scale
        for enabled, color in ((True, t["on"]), (False, t["off"])):
            img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            s = big / 210.0
            # state disc
            d.ellipse((10 * s, 10 * s, 200 * s, 200 * s), fill=color)
            white = t["mic_glyph"]
            lw = int(9 * s)
            # capsule
            d.rounded_rectangle((86 * s, 42 * s, 124 * s, 112 * s),
                                radius=19 * s, fill=white)
            # cradle arc (lower half of a circle around the capsule bottom)
            d.arc((64 * s, 62 * s, 146 * s, 144 * s), start=0, end=180,
                  fill=white, width=lw)
            # stem and base
            d.rounded_rectangle((100 * s, 144 * s, 110 * s, 162 * s),
                                radius=2 * s, fill=white)
            d.rounded_rectangle((78 * s, 164 * s, 132 * s, 176 * s),
                                radius=6 * s, fill=white)
            photo = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
            self._mic_photos[enabled] = photo
        self._update_mic_button()

    def _update_mic_button(self) -> None:
        photo = self._mic_photos.get(bool(self.enabled_var.get()))
        if photo is not None:
            self.mic_canvas.itemconfigure(self._mic_item, image=photo)

    def _build_settings(self, parent) -> None:
        pad = {"padx": 10, "pady": 4}

        words = ttk.LabelFrame(parent, text="Командные слова")
        words.pack(fill="x", **pad)
        self.start_word = self._row(words, 0, "Начало диктовки:")
        self.send_word = self._row(words, 1, "Отправить (Enter, набор продолжается):")
        self.finish_word = self._row(words, 2, "Закончить (Enter и завершить):")
        self.cancel_word = self._row(words, 3, "Отмена (стереть):")
        self.new_line_word = self._row(words, 4, "С новой строки (перенос строки):")
        self.wake_words = self._row(words, 5, "Слова-префиксы (через запятую):")
        ttk.Label(words, style="Muted.TLabel", wraplength=520, justify="left",
                  text="После «отправить» диктовка продолжается — не нужно снова "
                       "говорить слово начала. Очистите поле, чтобы «отправить» "
                       "сразу завершала диктовку. «С новой строки» вставляет "
                       "перенос строки (в мессенджерах сообщение не отправляет)."
                  ).grid(row=6, column=0, columnspan=2, sticky="we", padx=6, pady=(0, 6))

        eng = ttk.LabelFrame(parent, text="Распознавание")
        eng.pack(fill="x", **pad)
        ttk.Label(eng, text="Движок:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self.engine_box = ttk.Combobox(
            eng, values=[ENGINE_TEXT[e] for e in ENGINES], state="readonly", width=32)
        self.engine_box.grid(row=0, column=1, sticky="we", padx=6, pady=3)
        ttk.Label(eng, text="Модель Whisper:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self.whisper_box = ttk.Combobox(eng, values=list(WHISPER_MODELS),
                                        state="readonly", width=10)
        self.whisper_box.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        self.corrections_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(eng, text="Уточнять текст после пауз (движок качества)",
                        variable=self.corrections_var).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=6, pady=3)
        self.download_btn = ttk.Button(eng, text="Скачать модель Vosk",
                                       command=self._download_model)
        self.download_btn.grid(row=3, column=0, sticky="w", padx=6, pady=3)
        self.download_progress = ttk.Progressbar(eng, length=160, maximum=100)
        self.download_progress.grid(row=3, column=1, sticky="w", padx=6, pady=3)
        eng.columnconfigure(1, weight=1)

        cloud = ttk.LabelFrame(parent, text="Ключи облачных провайдеров")
        cloud.pack(fill="x", **pad)
        self.yandex_key = self._row(cloud, 0, "Яндекс SpeechKit, Api-Key:", show="*")
        self.openai_key = self._row(cloud, 1, "OpenAI, ключ:", show="*")
        self.openai_url = self._row(cloud, 2, "OpenAI-совместимый сервер:")
        self.openai_model = self._row(cloud, 3, "Модель OpenAI:")
        self.google_key = self._row(cloud, 4, "Google Cloud STT, ключ:", show="*")
        ttk.Label(cloud, style="Muted.TLabel", wraplength=520, justify="left",
                  text="Без ключа облачный движок работает через локальный vosk. "
                       "Ключ хранится только на этом компьютере."
                  ).grid(row=5, column=0, columnspan=2, sticky="we", padx=6, pady=(0, 6))

        misc = ttk.LabelFrame(parent, text="Отправка")
        misc.pack(fill="x", **pad)
        ttk.Label(misc, text="Клавиша:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self.send_key_box = ttk.Combobox(misc, values=["enter", "ctrl+enter"],
                                         state="readonly", width=12)
        self.send_key_box.grid(row=0, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(misc, text="Ждать коррекцию, с:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self.send_wait = self._entry(misc, 1, 1, width=6)

        look = ttk.LabelFrame(parent, text="Внешний вид")
        look.pack(fill="x", **pad)
        self.dark_var = tk.BooleanVar(value=self.theme_name == "dark")
        ttk.Checkbutton(look, text="Тёмная тема", variable=self.dark_var,
                        command=self._toggle_theme).pack(anchor="w", padx=6, pady=4)

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", **pad)
        ttk.Button(buttons, text="Сохранить и применить", style="Accent.TButton",
                   command=self._save).pack(side="left")

    def _row(self, parent, row: int, label: str, show: str = "") -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        entry = self._entry(parent, row, 1, show=show)
        parent.columnconfigure(1, weight=1)
        return entry

    @staticmethod
    def _entry(parent, row: int, col: int, width: int = 34, show: str = "") -> ttk.Entry:
        entry = ttk.Entry(parent, width=width, show=show)
        entry.grid(row=row, column=col, sticky="we", padx=6, pady=3)
        return entry

    # ── settings ↔ ui ────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        s = self.settings
        self.start_word.insert(0, s.start_word)
        self.send_word.insert(0, s.send_word)
        self.finish_word.insert(0, s.finish_word)
        self.cancel_word.insert(0, s.cancel_word)
        self.new_line_word.insert(0, s.new_line_word)
        self.wake_words.insert(0, s.wake_words)
        if s.engine in ENGINES:
            self.engine_box.current(ENGINES.index(s.engine))
        if s.whisper_model in WHISPER_MODELS:
            self.whisper_box.current(WHISPER_MODELS.index(s.whisper_model))
        self.corrections_var.set(s.corrections)
        self.yandex_key.insert(0, s.yandex_api_key)
        self.openai_key.insert(0, s.openai_api_key)
        self.openai_url.insert(0, s.openai_base_url)
        self.openai_model.insert(0, s.openai_model)
        self.google_key.insert(0, s.google_api_key)
        self.send_key_box.set(s.send_key)
        self.send_wait.insert(0, str(s.send_wait_secs))
        self._update_mic_button()

    def _collect(self) -> Settings:
        try:
            wait = float(str(self.send_wait.get()).replace(",", "."))
        except ValueError:
            wait = 1.2
        return Settings.from_config({
            "enabled": self.enabled_var.get(),
            "start_word": self.start_word.get().strip(),
            "send_word": self.send_word.get().strip(),
            "finish_word": self.finish_word.get().strip(),
            "cancel_word": self.cancel_word.get().strip(),
            "new_line_word": self.new_line_word.get().strip(),
            "wake_words": self.wake_words.get().strip(),
            "engine": ENGINES[self.engine_box.current()],
            "whisper_model": WHISPER_MODELS[self.whisper_box.current()],
            "corrections": self.corrections_var.get(),
            "yandex_api_key": self.yandex_key.get().strip(),
            "openai_api_key": self.openai_key.get().strip(),
            "openai_base_url": self.openai_url.get().strip(),
            "openai_model": self.openai_model.get().strip(),
            "google_api_key": self.google_key.get().strip(),
            "send_key": self.send_key_box.get(),
            "send_wait_secs": wait,
        })

    def _save(self) -> None:
        self.settings = self._collect()
        self.app_cfg.update(store.settings_fields(self.settings))
        store.save_app(self.app_cfg)
        self.engine.apply_settings(self.settings)
        self._set_status_text("Настройки сохранены")

    def _on_toggle(self) -> None:
        self.settings.enabled = self.enabled_var.get()
        self.app_cfg.update(store.settings_fields(self.settings))
        store.save_app(self.app_cfg)
        self.engine.apply_settings(self.settings)
        self._update_mic_button()
        if self.on_state_change is not None:
            self.on_state_change()

    def toggle_from_tray(self) -> None:
        self.enabled_var.set(not self.enabled_var.get())
        self._on_toggle()

    def _start_engine(self) -> None:
        self.engine.apply_settings(self.settings)

    # ── home screen state ────────────────────────────────────────────────

    def _poll_status(self) -> None:
        status = self.engine.status()
        self.status_label.config(text=STATUS_TEXT.get(status, status))
        if self._tooltip_hook is not None:
            self._tooltip_hook(f"Голосовой наборщик — {STATUS_TEXT.get(status, status)}")
        self.root.after(400, self._poll_status)

    def set_tooltip_hook(self, hook) -> None:
        self._tooltip_hook = hook

    def _set_status_text(self, text: str) -> None:
        self.status_label.config(text=text)

    # ── tray / quit ──────────────────────────────────────────────────────

    def _hide(self) -> None:
        self.root.withdraw()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def _download_model(self) -> None:
        self.download_btn.state(["disabled"])
        self._download_cancel.clear()

        def progress(done_mb: float, total_mb: float) -> None:
            pct = min(100.0, done_mb / total_mb * 100.0) if total_mb else 0
            self.root.after(0, lambda p=pct: self.download_progress.configure(value=p))

        def worker() -> None:
            result = models.download_vosk_model(progress, self._download_cancel.is_set)

            def done():
                self.download_btn.state(["!disabled"])
                self.download_progress.configure(value=0)
                if result:
                    self._set_status_text("Модель Vosk скачана")
                    self.engine.apply_settings(self.settings)
                else:
                    self._set_status_text("Не удалось скачать модель")
            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def quit(self) -> None:
        try:
            self.engine.stop()
        finally:
            self.on_quit()
