from typing import Any

import httpx

MAX_SYNC_ATTEMPTS = 3
SYNC_TIMEOUT_SECONDS = 10


def sync_projects(api_base_url: str) -> dict[str, Any]:
    endpoint = f"{api_base_url.rstrip('/')}/projects/scan"
    for attempt in range(MAX_SYNC_ATTEMPTS):
        try:
            response = httpx.post(endpoint, timeout=SYNC_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            if error.response.status_code < 500 or attempt == MAX_SYNC_ATTEMPTS - 1:
                raise
        except httpx.RequestError:
            if attempt == MAX_SYNC_ATTEMPTS - 1:
                raise

    raise RuntimeError("unreachable")
