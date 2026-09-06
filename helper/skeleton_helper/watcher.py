from pathlib import Path
from threading import Lock, Timer
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


def should_trigger_scan(master: Path, changed: Path) -> bool:
    """Return whether a new folder is a direct child of the master folder."""
    return changed.parent == master


class ProjectFolderWatcher:
    """Debounce scan requests caused by new direct project folders."""

    def __init__(
        self,
        master_folder: Path,
        api_base_url: str,
        *,
        sync: Callable[[str], object] | None = None,
        observer_factory: Callable[[], Observer] = Observer,
        debounce_seconds: float = 2,
    ) -> None:
        self.master_folder = master_folder
        self.api_base_url = api_base_url
        if sync is None:
            from .sync_client import sync_projects

            sync = sync_projects
        self.sync = sync
        self.observer_factory = observer_factory
        self.debounce_seconds = debounce_seconds
        self._lock = Lock()
        self._timer: Timer | None = None
        self._observer: Observer | None = None

    def start(self) -> None:
        self.sync(self.api_base_url)
        self._observer = self.observer_factory()
        self._observer.schedule(
            _CreatedDirectoryHandler(self), str(self.master_folder), recursive=False
        )
        self._observer.start()

    def handle_directory_created(self, changed: Path) -> None:
        if not should_trigger_scan(self.master_folder, changed):
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = Timer(self.debounce_seconds, self.sync, args=(self.api_base_url,))
            self._timer.start()

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None


class _CreatedDirectoryHandler(FileSystemEventHandler):
    def __init__(self, watcher: ProjectFolderWatcher) -> None:
        self.watcher = watcher

    def on_created(self, event) -> None:
        if event.is_directory:
            self.watcher.handle_directory_created(Path(event.src_path))
