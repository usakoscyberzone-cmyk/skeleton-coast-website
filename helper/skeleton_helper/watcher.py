import logging
from pathlib import Path
from threading import RLock, Timer
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


logger = logging.getLogger(__name__)


def should_trigger_scan(master: Path, changed: Path) -> bool:
    """Return whether a new folder is a direct child of the master folder."""
    return changed.parent == master


def _make_timer(delay_seconds: float, callback: Callable[[], None]) -> Timer:
    return Timer(delay_seconds, callback)


def _log_sync_error(error: Exception) -> None:
    logger.error(
        "Delayed project synchronization failed: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )


class ProjectFolderWatcher:
    """Watch direct project folders and synchronize the local API safely."""

    def __init__(
        self,
        master_folder: Path,
        api_base_url: str,
        *,
        sync: Callable[[str], object] | None = None,
        observer_factory: Callable[[], Observer] = Observer,
        timer_factory: Callable[[float, Callable[[], None]], Timer] = _make_timer,
        on_error: Callable[[Exception], None] = _log_sync_error,
        debounce_seconds: float = 2,
    ) -> None:
        self.master_folder = master_folder
        self.api_base_url = api_base_url
        if sync is None:
            from .sync_client import sync_projects

            sync = sync_projects
        self.sync = sync
        self.observer_factory = observer_factory
        self.timer_factory = timer_factory
        self.on_error = on_error
        self.debounce_seconds = debounce_seconds
        self._lock = RLock()
        self._timer: Timer | None = None
        self._timer_token: object | None = None
        self._observer: Observer | None = None
        self._running = False

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._observer = self.observer_factory()
            self._observer.schedule(
                _CreatedDirectoryHandler(self), str(self.master_folder), recursive=False
            )
            self._observer.start()
        try:
            self.sync(self.api_base_url)
        except Exception:
            self.stop()
            raise

    def handle_directory_created(self, changed: Path) -> None:
        if not should_trigger_scan(self.master_folder, changed):
            return
        with self._lock:
            if not self._running:
                return
            if self._timer is not None:
                self._timer.cancel()
            token = object()
            self._timer_token = token
            self._timer = self.timer_factory(
                self.debounce_seconds,
                lambda: self._sync_after_debounce(token),
            )
            self._timer.start()

    def _sync_after_debounce(self, token: object) -> None:
        error: Exception | None = None
        with self._lock:
            if not self._running or token is not self._timer_token:
                return
            self._timer = None
            self._timer_token = None
            try:
                self.sync(self.api_base_url)
            except Exception as caught_error:
                error = caught_error
        if error is not None:
            self.on_error(error)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._timer_token = None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            observer = self._observer
            self._observer = None
        if observer is not None:
            observer.stop()
            observer.join()


class _CreatedDirectoryHandler(FileSystemEventHandler):
    def __init__(self, watcher: ProjectFolderWatcher) -> None:
        self.watcher = watcher

    def on_created(self, event) -> None:
        if event.is_directory:
            self.watcher.handle_directory_created(Path(event.src_path))
