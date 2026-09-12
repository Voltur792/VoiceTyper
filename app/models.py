"""Model discovery and download for the standalone app.

The exe does not bundle models (hundreds of MB). Vosk's small Russian model
(~45 MB) is downloaded on demand; faster-whisper models are fetched by HF hub
into the user cache automatically on first use.
"""

import logging
import sys
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("voice-text-input.app")

VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
VOSK_MODEL_SIZE_MB = 45


def repo_root() -> Path:
    """The folder that holds models/ — next to the exe when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def models_dir() -> Path:
    return repo_root() / "models"


def vosk_model_present() -> bool:
    return any(models_dir().glob("vosk-model*ru*"))


def download_vosk_model(progress=None, should_cancel=None) -> Path | None:
    """Download and unpack the Vosk model. `progress(done_mb, total_mb)`.

    Returns the model folder, or None on failure/cancel. Runs in the caller's
    thread — the GUI wraps it in a worker thread.
    """
    target = models_dir()
    target.mkdir(parents=True, exist_ok=True)
    archive = target / "_vosk-model.zip"
    try:
        request = urllib.request.Request(
            VOSK_MODEL_URL, headers={"User-Agent": "voice-text-input/1.0"})

        with urllib.request.urlopen(request, timeout=60) as response, \
                open(archive, "wb") as out:
            # shutil.copyfileobj has no progress callback — read in chunks.
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if should_cancel is not None and should_cancel():
                    raise KeyboardInterrupt
                chunk = response.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress is not None and total > 0:
                    progress(done / 1e6, total / 1e6)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
        unpacked = sorted(target.glob("vosk-model*ru*"))
        return unpacked[0] if unpacked else None
    except KeyboardInterrupt:
        log.info("vosk model download cancelled")
        return None
    except Exception as exc:
        log.warning("vosk model download failed: %s", exc)
        raise RuntimeError(f"не удалось скачать модель: {exc}") from exc
    finally:
        archive.unlink(missing_ok=True)
