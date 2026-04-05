from __future__ import annotations

import threading
import time
from flask import Flask

from .poller import poll_once

_thread: threading.Thread | None = None
_stop = threading.Event()

def start(app: Flask) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return

    def loop():
        while not _stop.is_set():
            try:
                with app.app_context():
                    if app.config.get("CFE_POLL_ENABLED", False):
                        poll_once()
            except Exception:
                # avoid crashing background thread
                pass
            sec = float(app.config.get("CFE_POLL_SECONDS") or 5)
            # sleep with stop responsiveness
            for _ in range(int(max(1, sec*10))):
                if _stop.is_set():
                    break
                time.sleep(0.1)

    _thread = threading.Thread(target=loop, name="cfe_poll", daemon=True)
    _thread.start()

def stop() -> None:
    _stop.set()
