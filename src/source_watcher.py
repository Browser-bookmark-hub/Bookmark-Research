"""Process-scoped, standard-library polling for registered live directories."""

import math
import threading
from pathlib import Path

from bookmark_index import BookmarkIndex
from source_manager import SourceManager


class SourceWatcher:
    def __init__(self, db_path, interval=1.0, debounce=2.0, deletion_grace=5.0, on_change=None):
        for value in (interval, debounce, deletion_grace):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Watcher intervals must be finite positive seconds")
        self.db_path = Path(db_path)
        self.interval, self.debounce, self.deletion_grace = interval, debounce, deletion_grace
        self.on_change = on_change
        self.stop_event, self.ready = threading.Event(), threading.Event()
        self.thread = None
        self.last_error = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="bookmark-source-watch", daemon=True)
            self.thread.start()
        return self

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)

    def status(self):
        return {"running": bool(self.thread and self.thread.is_alive() and not self.stop_event.is_set()),
                "mechanism": "poll", "interval_seconds": self.interval,
                "debounce_seconds": self.debounce, "deletion_grace_seconds": self.deletion_grace,
                "error": self.last_error, "lifetime": "host_process"}

    def run(self):
        previous = {}
        try:
            # Each monitor owns its connection; it never shares SQLite objects
            # with the MCP request thread or another host process.
            with BookmarkIndex(self.db_path) as index:
                manager = SourceManager(index, debounce=self.debounce, deletion_grace=self.deletion_grace)
                self.ready.set()
                while not self.stop_event.is_set():
                    try:
                        for source_id in manager.live_sources():
                            if self.stop_event.is_set():
                                break
                            result = manager.refresh(source_id, force=False)
                            signature = (result["state"], result.get("version_id"),
                                         tuple(result.get("pending_files", [])), result.get("error"))
                            if self.on_change is not None and signature != previous.get(source_id):
                                self.on_change(result)
                            previous[source_id] = signature
                        self.last_error = None
                    except Exception as exc:
                        # A locked database or temporary I/O failure is retried
                        # on the next tick, without terminating tool service.
                        self.last_error = type(exc).__name__ + ": " + str(exc)[:1000]
                    self.stop_event.wait(self.interval)
        except Exception as exc:
            self.last_error = type(exc).__name__ + ": " + str(exc)[:1000]
        finally:
            self.ready.set()
