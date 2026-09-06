from pathlib import Path
import time
from types import SimpleNamespace

from skeleton_helper.watcher import ProjectFolderWatcher, should_trigger_scan


def test_should_trigger_scan_for_new_top_level_project(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    created = master / "New Project"

    assert should_trigger_scan(master, created) is True


def test_should_not_trigger_for_generated_subfolder(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    project = master / "Pilchard" / "Thumbnails"

    assert should_trigger_scan(master, project) is False


def test_watcher_debounces_project_creation_events_for_two_seconds(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    calls: list[float] = []
    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=lambda _: calls.append(time.monotonic()),
    )
    started_at = time.monotonic()

    watcher.handle_directory_created(master / "New Project")
    time.sleep(0.1)
    watcher.handle_directory_created(master / "New Project")
    time.sleep(1.75)

    assert calls == []

    time.sleep(0.35)
    watcher.stop()

    assert len(calls) == 1
    assert calls[0] - started_at >= 2


class RecordingObserver:
    def __init__(self):
        self.handler = None
        self.path = None
        self.recursive = None
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler, path, recursive):
        self.handler = handler
        self.path = path
        self.recursive = recursive

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self):
        self.joined = True


def test_start_syncs_immediately_and_handles_new_top_level_directory(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    calls: list[str] = []
    observer = RecordingObserver()
    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=calls.append,
        observer_factory=lambda: observer,
        debounce_seconds=0.01,
    )

    watcher.start()
    observer.handler.on_created(
        SimpleNamespace(is_directory=True, src_path=str(master / "New Project"))
    )
    time.sleep(0.05)
    watcher.stop()

    assert calls == ["http://127.0.0.1:8000", "http://127.0.0.1:8000"]
    assert observer.path == str(master)
    assert observer.recursive is False
    assert observer.started is True
    assert observer.stopped is True
    assert observer.joined is True


def test_stop_cancels_a_pending_debounced_sync(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    calls: list[str] = []
    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=calls.append,
        debounce_seconds=0.05,
    )

    watcher.handle_directory_created(master / "New Project")
    watcher.stop()
    time.sleep(0.1)

    assert calls == []


def test_main_prints_configuration_starts_watcher_and_stops_on_interrupt(
    monkeypatch, capsys
):
    import skeleton_helper.__main__ as helper_main

    calls: list[str] = []

    class FakeWatcher:
        def __init__(self, master_folder, api_base_url):
            assert master_folder == Path(r"I:\YouTube Projects")
            assert api_base_url == "http://127.0.0.1:8000"

        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

    monkeypatch.setattr(
        helper_main,
        "get_settings",
        lambda: SimpleNamespace(
            master_project_folder=Path(r"I:\YouTube Projects"),
            api_base_url="http://127.0.0.1:8000",
        ),
    )
    monkeypatch.setattr(helper_main, "ProjectFolderWatcher", FakeWatcher)
    monkeypatch.setattr(helper_main, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt))

    helper_main.main()

    assert capsys.readouterr().out.splitlines() == [
        r"Master folder: I:\YouTube Projects",
        "API: http://127.0.0.1:8000",
        "Watching for new projects...",
    ]
    assert calls == ["start", "stop"]
