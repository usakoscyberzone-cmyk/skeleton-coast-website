from typing import Any
import time

import httpx

MAX_SYNC_ATTEMPTS = 3
SYNC_RETRY_DELAY_SECONDS = 0.1
SYNC_TIMEOUT_SECONDS = 10


def sync_projects(api_base_url: str) -> dict[str, Any]:
    endpoint = f"{api_base_url.rstrip('/')}/projects/scan"
    for attempt in range(MAX_SYNC_ATTEMPTS):
        try:
            response = httpx.post(endpoint, timeout=SYNC_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return {"projects": payload}
            if isinstance(payload, dict):
                return payload
            raise ValueError("Project scan response must be a JSON object or list")
        except httpx.HTTPStatusError as error:
            if error.response.status_code < 500 or attempt == MAX_SYNC_ATTEMPTS - 1:
                raise
        except httpx.RequestError:
            if attempt == MAX_SYNC_ATTEMPTS - 1:
                raise

        time.sleep(SYNC_RETRY_DELAY_SECONDS * 2**attempt)

    raise RuntimeError("unreachable")
