import json

import httpx2
import pytest

from ocost.api import API, APIError, Connection
from ocost.window import Window


@pytest.mark.parametrize("status", [401, 403, 404, 500, 302])
def test_http_failures_are_safe_and_redirects_are_not_followed(status):
    # GIVEN an API failure or a redirect to a different origin
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(status, text="sensitive response", headers={"Location": "http://example.com/"})

    connection = Connection(url="http://127.0.0.1:1234", password="private-password")
    # WHEN requesting statistics
    with connection.client(transport=httpx2.MockTransport(respond)) as client, pytest.raises(APIError) as error:
        API(client).stats(Window(0, 1000, "Test"))
    # THEN the error excludes secrets and no redirect receives credentials
    assert len(requests) == 1
    assert "private-password" not in str(error.value)
    assert "sensitive response" not in str(error.value)
    assert "authentication" in str(error.value) if status in {401, 403} else str(status) in str(error.value)


@pytest.mark.parametrize("failure", [httpx2.ConnectError, httpx2.ReadTimeout])
def test_transport_failure_is_actionable_without_exposing_exception(failure):
    # GIVEN an unavailable or unresponsive service
    def respond(request):
        raise failure("secret network diagnostics", request=request)

    # WHEN requesting statistics
    with (
        httpx2.Client(transport=httpx2.MockTransport(respond), base_url="http://127.0.0.1:1234") as client,
        pytest.raises(APIError) as error,
    ):
        API(client).stats(Window(0, 1000, "Test"))
    # THEN the user sees a safe connection failure
    assert "secret network diagnostics" not in str(error.value)
    assert "OpenCode" in str(error.value)


@pytest.mark.parametrize("body", [b"null", b"{}", b"not json", b'{"data": {"cost": 0}}'])
def test_invalid_statistics_are_not_treated_as_empty(body):
    # GIVEN an incomplete or malformed API response
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, content=body))
    # WHEN fetching statistics
    # THEN it is rejected instead of rendering zeros
    with (
        httpx2.Client(transport=transport, base_url="http://127.0.0.1:1234") as client,
        pytest.raises(APIError, match="Invalid OpenCode usage"),
    ):
        API(client).stats(Window(0, 1000, "Test"))


@pytest.mark.parametrize("cost", ["12", True, float("nan"), float("inf")])
def test_non_numeric_or_non_finite_cost_is_rejected(stats_payload, cost):
    # GIVEN a cost unsuitable for meaningful reporting
    stats_payload["data"]["cost"] = cost
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, content=json.dumps(stats_payload)))
    # WHEN fetching usage
    # THEN invalid values cannot be displayed as valid spending
    with (
        httpx2.Client(transport=transport, base_url="http://127.0.0.1:1234") as client,
        pytest.raises(APIError, match="Invalid OpenCode usage"),
    ):
        API(client).stats(Window(0, 1000, "Test"))


def test_wrong_response_window_is_rejected(stats_payload):
    # GIVEN an API that did not apply our requested time range
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=stats_payload))
    # WHEN requesting another range
    # THEN the report fails rather than mislabelling usage
    with (
        httpx2.Client(transport=transport, base_url="http://127.0.0.1:1234") as client,
        pytest.raises(APIError, match="different time range"),
    ):
        API(client).stats(Window(500, 1000, "Test"))


@pytest.mark.parametrize("projects", [None, {}, [{}], [{"id": "one", "canonical": "/repo"}] * 2])
def test_invalid_project_discovery_cannot_omit_or_double_count(projects):
    # GIVEN malformed project discovery or duplicate IDs
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=projects))
    # WHEN discovering projects
    # THEN no partial or duplicated project list is accepted
    with (
        httpx2.Client(transport=transport, base_url="http://127.0.0.1:1234") as client,
        pytest.raises(APIError),
    ):
        API(client).projects()


@pytest.mark.parametrize("url", ["http://example.com:80", "http://127.0.0.1:1234/?password=secret", "not a URL"])
def test_invalid_registration_never_discloses_credentials(tmp_path, url):
    # GIVEN a registration with an unsafe URL and a real-looking secret
    path = tmp_path / "opencode/service.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"url": url, "password": "private-password"}))
    # WHEN discovering the connection
    with pytest.raises(APIError) as error:
        Connection.discover(path)
    # THEN credentials cannot be sent to that destination or leaked in validation output
    assert "private-password" not in str(error.value)
    assert url not in str(error.value)


def test_registration_determines_request_destination(tmp_path):
    # GIVEN an explicit registration file with a dynamically assigned port
    path = tmp_path / "registration/service.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"url": "http://127.0.0.1:3456", "password": "fixture-password"}))
    # WHEN connecting using the discovered endpoint
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, json=[])

    with Connection.discover(path).client(transport=httpx2.MockTransport(respond)) as client:
        API(client).projects()
    # THEN the registration, not a fixed port, determines the request destination
    assert str(requests[0].url) == "http://127.0.0.1:3456/api/project"
