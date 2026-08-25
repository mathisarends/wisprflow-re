import pytest

from whisprflow import (
    CredentialsError,
    DesktopAuth,
    DesktopSessionStore,
    ResolvedPublishableKey,
    SupabaseTokenRefresher,
)


class StubResolver:
    def __init__(self, resolved=None):
        self.resolved = resolved
        self.calls = []

    def resolve(self, project_ref):
        self.calls.append(project_ref)
        return self.resolved


def test_fresh_token_is_returned_without_refreshing(write_session, jwt):
    token = jwt(sub="user-1", exp=2000)
    path = write_session(access_token=token)

    def fail(refresh_token):
        raise AssertionError("A fresh session must not be refreshed")

    auth = DesktopAuth(DesktopSessionStore(path), fail, clock=lambda: 1000)

    assert auth() == token
    assert auth.user_id == "user-1"
    assert auth.credentials.access_token == token


def test_token_inside_the_skew_window_is_refreshed(write_session, jwt):
    path = write_session(access_token=jwt(sub="user-1", exp=1060), expires_at=1060)
    refreshed = jwt(sub="user-1", exp=3000)
    seen = []

    def refresh(refresh_token):
        seen.append(refresh_token)
        return {"access_token": refreshed, "expires_at": 3000}

    auth = DesktopAuth(DesktopSessionStore(path), refresh, clock=lambda: 1000)

    assert auth() == refreshed
    assert seen == ["refresh-1"]


def test_expired_token_without_refresh_token_is_unrecoverable(write_session, jwt):
    path = write_session(
        access_token=jwt(sub="user-1", exp=900),
        refresh_token=None,
        expires_at=900,
    )
    auth = DesktopAuth(DesktopSessionStore(path), clock=lambda: 1000)

    with pytest.raises(CredentialsError, match="no refresh token"):
        auth()


def test_expired_token_without_refresher_names_the_missing_setting(write_session, jwt):
    path = write_session(access_token=jwt(sub="user-1", exp=900), expires_at=900)
    auth = DesktopAuth(DesktopSessionStore(path), clock=lambda: 1000)

    with pytest.raises(CredentialsError, match="supabase_anon_key"):
        auth()


@pytest.mark.parametrize(
    ("now", "status", "ok"),
    [(1000, "valid", True), (1950, "near_expiry", True), (2100, "expired", False)],
)
def test_status_reports_the_lifetime_of_the_session(
    write_session, jwt, now, status, ok
):
    path = write_session(access_token=jwt(sub="user-1", exp=2000))
    auth = DesktopAuth(DesktopSessionStore(path), clock=lambda: now)

    report = auth.status()

    assert report.status == status
    assert report.ok is ok
    assert report.expires_at == 2000
    assert report.seconds_remaining == 2000 - now
    assert report.refresh_available is False


def test_status_reports_where_a_resolvable_key_came_from(write_session):
    path = write_session()
    resolver = StubResolver(ResolvedPublishableKey("resolved-key", "desktop:test"))
    refresher = SupabaseTokenRefresher(project_ref="project", key_resolver=resolver)

    status = DesktopAuth(
        DesktopSessionStore(path), refresher, clock=lambda: 1000
    ).status()

    assert status.refresh_available is True
    assert status.refresh_source == "desktop:test"


def test_status_reports_refresh_as_unavailable_when_no_key_resolves(write_session):
    path = write_session()
    refresher = SupabaseTokenRefresher(
        project_ref="project", key_resolver=StubResolver(None)
    )

    status = DesktopAuth(
        DesktopSessionStore(path), refresher, clock=lambda: 1000
    ).status()

    assert status.refresh_available is False
    assert status.refresh_source is None


def test_status_of_a_session_without_expiry_is_valid(write_session, jwt):
    path = write_session(access_token="opaque-token", expires_at=None)
    auth = DesktopAuth(DesktopSessionStore(path), clock=lambda: 1000)

    status = auth.status()

    assert status.status == "valid"
    assert status.seconds_remaining is None
    assert auth() == "opaque-token"
