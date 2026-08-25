import io
import json
import urllib.error

import pytest

from wisprflow import CredentialsError, ResolvedPublishableKey, SupabaseTokenRefresher


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class RecordingOpener:
    def __init__(self, body: bytes = b'{"access_token":"new-token"}'):
        self.body = body
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append((request, timeout))
        return FakeResponse(self.body)


class StubResolver:
    def __init__(self, resolved):
        self.resolved = resolved
        self.calls = []

    def resolve(self, project_ref):
        self.calls.append(project_ref)
        return self.resolved


def test_a_key_or_a_resolver_is_required():
    with pytest.raises(ValueError, match="'anon_key' or 'key_resolver'"):
        SupabaseTokenRefresher(project_ref="project")


def test_refresh_posts_the_token_to_the_project_endpoint():
    opener = RecordingOpener()
    refresher = SupabaseTokenRefresher(
        project_ref="project", anon_key="explicit-key", opener=opener
    )

    assert refresher("refresh-token") == {"access_token": "new-token"}

    request, timeout = opener.requests[0]
    assert request.full_url == (
        "https://project.supabase.co/auth/v1/token?grant_type=refresh_token"
    )
    assert json.loads(request.data) == {"refresh_token": "refresh-token"}
    assert request.get_header("Apikey") == "explicit-key"
    assert request.get_header("Authorization") == "Bearer explicit-key"
    assert timeout == refresher.timeout
    assert refresher.key_source == "explicit"


def test_the_resolver_is_consulted_only_when_a_refresh_happens():
    resolver = StubResolver(ResolvedPublishableKey("resolved-key", "test"))
    opener = RecordingOpener()
    refresher = SupabaseTokenRefresher(
        project_ref="project", key_resolver=resolver, opener=opener
    )
    assert resolver.calls == []

    refresher("refresh-token")

    assert resolver.calls == ["project"]
    assert opener.requests[0][0].get_header("Apikey") == "resolved-key"
    assert refresher.key_source == "test"


def test_an_unresolvable_key_explains_how_to_supply_one():
    refresher = SupabaseTokenRefresher(
        project_ref="project", key_resolver=StubResolver(None)
    )

    assert refresher.resolve_key() is None
    with pytest.raises(CredentialsError, match="WISPRFLOW_SUPABASE_ANON_KEY"):
        refresher("refresh-token")


def test_http_errors_surface_the_status_and_body():
    def opener(request, *, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", {}, io.BytesIO(b"invalid grant")
        )

    refresher = SupabaseTokenRefresher(
        project_ref="project", anon_key="key", opener=opener
    )

    with pytest.raises(CredentialsError, match="HTTP 400.*invalid grant"):
        refresher("refresh-token")


def test_network_failures_are_wrapped():
    def opener(request, *, timeout):
        raise OSError("connection reset")

    refresher = SupabaseTokenRefresher(
        project_ref="project", anon_key="key", opener=opener
    )

    with pytest.raises(CredentialsError, match="connection reset"):
        refresher("refresh-token")


def test_a_non_json_response_is_wrapped():
    refresher = SupabaseTokenRefresher(
        project_ref="project",
        anon_key="key",
        opener=RecordingOpener(b"<html>gateway timeout</html>"),
    )

    with pytest.raises(CredentialsError, match="refresh failed"):
        refresher("refresh-token")


@pytest.mark.parametrize("body", [b"[]", b"{}", b'{"access_token": ""}'])
def test_a_response_without_an_access_token_is_rejected(body):
    refresher = SupabaseTokenRefresher(
        project_ref="project", anon_key="key", opener=RecordingOpener(body)
    )

    with pytest.raises(CredentialsError, match="no access token"):
        refresher("refresh-token")
