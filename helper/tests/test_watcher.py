from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from skeleton_helper.watcher import ProjectFolderWatcher, should_trigger_scan


class ManualTimer:
    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.callback()


class RecordingObserver:
    def __init__(self):
        self.handler = None
        self.path = None
        self.recursive = None
        self.started = False
        self.stopped = False
        self.joined = False
        self.on_start = None
        self.on_stop = None

    def schedule(self, handler, path, recursive):
        self.handler = handler
        self.path = path
        self.recursive = recursive

    def start(self):
        self.started = True
        if self.on_start is not None:
            self.on_start()

    def stop(self):
        self.stopped = True
        if self.on_stop is not None:
            self.on_stop()

    def join(self):
        self.joined = True


def make_timer_factory(timers):
    def make_timer(interval, callback):
        timer = ManualTimer(interval, callback)
        timers.append(timer)
        return timer

    return make_timer


def test_should_trigger_scan_for_new_top_level_project(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()

    assert should_trigger_scan(master, master / "New Project") is True


def test_should_not_trigger_for_generated_subfolder(tmp_path: Path):
    master = tmp_path / "YouTube Projects"

    assert should_trigger_scan(master, master / "Pilchard" / "Thumbnails") is False


def test_watcher_debounces_project_creation_events_for_exactly_two_seconds(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    calls: list[str] = []
    timers: list[ManualTimer] = []
    observer = RecordingObserver()
    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=calls.append,
        observer_factory=lambda: observer,
        timer_factory=make_timer_factory(timers),
    )
    watcher.start()
    calls.clear()

    watcher.handle_directory_created(master / "New Project")
    watcher.handle_directory_created(master / "New Project")

    assert [timer.interval for timer in timers] == [2, 2]
    assert timers[0].cancelled is True
    assert calls == []

    timers[1].fire()
    watcher.stop()

    assert calls == ["http://127.0.0.1:8000"]


def test_start_syncs_immediately_and_handles_new_top_level_directory(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    calls: list[str] = []
    timers: list[ManualTimer] = []
    observer = RecordingObserver()
    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=calls.append,
        observer_factory=lambda: observer,
        timer_factory=make_timer_factory(timers),
    )

    watcher.start()
    observer.handler.on_created(
        SimpleNamespace(is_directory=True, src_path=str(master / "New Project"))
    )
    timers[0].fire()
    watcher.stop()

    assert calls == ["http://127.0.0.1:8000", "http://127.0.0.1:8000"]
    assert observer.path == str(master)
    assert observer.recursive is False
    assert observer.started is True
    assert observer.stopped is True
    assert observer.joined is True


def test_start_begins_observer_before_the_immediate_sync(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    observer = RecordingObserver()
    sync_started = Event()
    release_sync = Event()

    def blocking_sync(_: str):
        sync_started.set()
        release_sync.wait(timeout=1)

    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=blocking_sync,
        observer_factory=lambda: observer,
    )
    start_thread = Thread(target=watcher.start)
    start_thread.start()
    try:
        assert sync_started.wait(timeout=0.5)
        assert observer.started is True
    finally:
        release_sync.set()
        start_thread.join(timeout=1)
        watcher.stop()

    assert start_thread.is_alive() is False


def test_stop_rejects_event_dispatched_during_observer_shutdown(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    calls: list[str] = []
    timers: list[ManualTimer] = []
    observer = RecordingObserver()
    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=calls.append,
        observer_factory=lambda: observer,
        timer_factory=make_timer_factory(timers),
    )
    watcher.start()
    calls.clear()

    def dispatch_late_event():
        event_thread = Thread(
            target=watcher.handle_directory_created,
            args=(master / "New Project",),
        )
        event_thread.start()
        event_thread.join(timeout=1)
        assert event_thread.is_alive() is False

    observer.on_stop = dispatch_late_event
    watcher.stop()

    assert timers == []
    assert calls == []


def test_stop_cancels_a_pending_debounced_sync(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    calls: list[str] = []
    timers: list[ManualTimer] = []
    observer = RecordingObserver()
    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=calls.append,
        observer_factory=lambda: observer,
        timer_factory=make_timer_factory(timers),
    )
    watcher.start()
    calls.clear()

    watcher.handle_directory_created(master / "New Project")
    watcher.stop()
    timers[0].fire()

    assert calls == []


def test_delayed_sync_reports_error_without_raising_from_timer(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    timers: list[ManualTimer] = []
    observer = RecordingObserver()
    errors: list[Exception] = []
    fail_delayed_sync = False

    def sync(_: str):
        if fail_delayed_sync:
            raise RuntimeError("API unavailable")

    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=sync,
        observer_factory=lambda: observer,
        timer_factory=make_timer_factory(timers),
        on_error=errors.append,
    )
    watcher.start()
    fail_delayed_sync = True

    watcher.handle_directory_created(master / "New Project")
    timers[0].fire()
    watcher.stop()

    assert len(errors) == 1
    assert str(errors[0]) == "API unavailable"


def test_delayed_sync_isolates_a_failing_error_callback(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    timers: list[ManualTimer] = []
    observer = RecordingObserver()
    successful_syncs: list[str] = []
    fail_delayed_sync = False

    def sync(api_base_url: str):
        if fail_delayed_sync:
            raise RuntimeError("API unavailable")
        successful_syncs.append(api_base_url)

    def failing_error_callback(_: Exception):
        raise RuntimeError("logger unavailable")

    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=sync,
        observer_factory=lambda: observer,
        timer_factory=make_timer_factory(timers),
        on_error=failing_error_callback,
    )
    watcher.start()
    fail_delayed_sync = True
    watcher.handle_directory_created(master / "New Project")

    timers[0].fire()

    fail_delayed_sync = False
    watcher.handle_directory_created(master / "Another Project")
    timers[1].fire()
    watcher.stop()

    assert successful_syncs == [
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8000",
    ]


def test_start_stops_observer_if_immediate_sync_fails(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    observer = RecordingObserver()
    watcher = ProjectFolderWatcher(
        master,
        "http://127.0.0.1:8000",
        sync=lambda _: (_ for _ in ()).throw(RuntimeError("API unavailable")),
        observer_factory=lambda: observer,
    )

    with pytest.raises(RuntimeError, match="API unavailable"):
        watcher.start()

    assert observer.started is True
    assert observer.stopped is True
    assert observer.joined is True


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


def test_main_sync_once_calls_sync_without_starting_watcher(monkeypatch, capsys):
    import skeleton_helper.__main__ as helper_main

    calls: list[str] = []

    class UnexpectedWatcher:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("one-shot synchronization must not start the watcher")

    monkeypatch.setattr(
        helper_main,
        "get_settings",
        lambda: SimpleNamespace(
            master_project_folder=Path(r"I:\YouTube Projects"),
            api_base_url="http://127.0.0.1:8000",
        ),
    )
    monkeypatch.setattr(helper_main, "ProjectFolderWatcher", UnexpectedWatcher)
    monkeypatch.setattr(
        helper_main,
        "sync_projects",
        lambda url: calls.append(url) or {"projects": [{"id": 1}]},
    )

    result = helper_main.main(["--sync-once"])

    assert result == 0
    assert calls == ["http://127.0.0.1:8000"]
    assert capsys.readouterr().out.splitlines() == [
        r"Master folder: I:\YouTube Projects",
        "API: http://127.0.0.1:8000",
        "Manual project sync: PASS (1 project)",
    ]
