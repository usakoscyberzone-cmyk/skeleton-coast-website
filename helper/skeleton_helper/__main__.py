from time import sleep

from .settings import get_settings
from .watcher import ProjectFolderWatcher


def main() -> None:
    settings = get_settings()
    watcher = ProjectFolderWatcher(
        settings.master_project_folder,
        settings.api_base_url,
    )
    print(f"Master folder: {settings.master_project_folder}")
    print(f"API: {settings.api_base_url}")
    print("Watching for new projects...")

    try:
        watcher.start()
        while True:
            sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()


if __name__ == "__main__":
    main()
