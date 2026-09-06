import httpx
import pytest

from skeleton_helper.sync_client import sync_projects


def test_sync_projects_posts_scan(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:8000/projects/scan",
        json={"projects": []},
    )

    result = sync_projects("http://127.0.0.1:8000")

    assert result == {"projects": []}
    request = httpx_mock.get_request()
    assert request.method == "POST"
    assert str(request.url) == "http://127.0.0.1:8000/projects/scan"


def test_sync_projects_retries_a_transient_server_error(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:8000/projects/scan",
        status_code=503,
    )
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:8000/projects/scan",
        json={"projects": []},
    )

    result = sync_projects("http://127.0.0.1:8000")

    assert result == {"projects": []}
    assert len(httpx_mock.get_requests()) == 2


def test_sync_projects_retries_a_connection_failure(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("API unavailable"))
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:8000/projects/scan",
        json={"projects": []},
    )

    result = sync_projects("http://127.0.0.1:8000")

    assert result == {"projects": []}
    assert len(httpx_mock.get_requests()) == 2


def test_sync_projects_does_not_retry_a_client_error(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:8000/projects/scan",
        status_code=400,
    )

    with pytest.raises(httpx.HTTPStatusError):
        sync_projects("http://127.0.0.1:8000")

    assert len(httpx_mock.get_requests()) == 1


def test_sync_projects_raises_after_three_server_errors(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(
            method="POST",
            url="http://127.0.0.1:8000/projects/scan",
            status_code=503,
        )

    with pytest.raises(httpx.HTTPStatusError):
        sync_projects("http://127.0.0.1:8000")

    assert len(httpx_mock.get_requests()) == 3
