import argparse
from collections.abc import Sequence
import sys
from time import sleep

from .settings import get_settings
from .sync_client import sync_projects
from .watcher import ProjectFolderWatcher


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Skeleton Coast project-folder helper")
    parser.add_argument(
        "--sync-once",
        action="store_true",
        help="perform one project scan through the local API and exit",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    print(f"Master folder: {settings.master_project_folder}")
    print(f"API: {settings.api_base_url}")
    if args.sync_once:
        result = sync_projects(settings.api_base_url)
        count = len(result.get("projects", []))
        noun = "project" if count == 1 else "projects"
        print(f"Manual project sync: PASS ({count} {noun})")
        return 0

    watcher = ProjectFolderWatcher(
        settings.master_project_folder,
        settings.api_base_url,
    )
    print("Watching for new projects...")

    try:
        watcher.start()
        while True:
            sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
