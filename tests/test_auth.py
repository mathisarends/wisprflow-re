import base64
import json

import pytest

from whisprflow import (
    CredentialsError,
    DesktopAuth,
    DesktopSessionStore,
    ResolvedPublishableKey,
    SupabaseTokenRefresher,
)


def _jwt(**claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"header.{payload.decode()}.signature"


def _write_session(path, *, access, refresh="refresh-1", expires_at=2000):
    auth = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": expires_at,
        "user": {"id": "user-1"},
        "future_field": {"preserved": True},
    }
    path.write_text(
        json.dumps({"sb-project-auth-token": json.dumps(auth), "outer": "keep"}),
        encoding="utf-8",
    )


def test_desktop_auth_uses_fresh_token(tmp_path):
    path = tmp_path / "session.json"
    token = _jwt(sub="user-1", exp=2000)
    _write_session(path, access=token)
    auth = DesktopAuth(DesktopSessionStore(path), clock=lambda: 1000)

    assert auth() == token
    assert auth.user_id == "user-1"


def test_desktop_auth_refreshes_and_preserves_unknown_fields(tmp_path):
    path = tmp_path / "session.json"
    _write_session(path, access=_jwt(sub="user-1", exp=900), expires_at=900)
    seen = []

    def refresh(token):
        seen.append(token)
        return {
            "access_token": _jwt(sub="user-1", exp=3000),
            "refresh_token": "refresh-2",
            "expires_at": 3000,
        }

    auth = DesktopAuth(DesktopSessionStore(path), refresh, clock=lambda: 1000)
    assert auth() == _jwt(sub="user-1", exp=3000)
    assert seen == ["refresh-1"]

    outer = json.loads(path.read_text(encoding="utf-8"))
    stored = json.loads(outer["sb-project-auth-token"])
    assert stored["refresh_token"] == "refresh-2"
    assert stored["future_field"] == {"preserved": True}
    assert outer["outer"] == "keep"


def test_session_store_preserves_unencoded_auth_entry(tmp_path):
    path = tmp_path / "session.json"
    auth = {
        "access_token": _jwt(sub="user-1", exp=900),
        "refresh_token": "refresh-1",
        "user": {"id": "user-1"},
        "future_field": "keep",
    }
    path.write_text(
        json.dumps({"sb-another-project-auth-token": auth}), encoding="utf-8"
    )
    store = DesktopSessionStore(path)

    assert store.project_ref == "another-project"
    store.save_refresh(
        {
            "access_token": _jwt(sub="user-1", exp=3000),
            "expires_at": 3000,
        }
    )

    stored = json.loads(path.read_text(encoding="utf-8"))
    stored_auth = stored["sb-another-project-auth-token"]
    assert isinstance(stored_auth, dict)
    assert stored_auth["future_field"] == "keep"


def test_expired_token_without_refresher_has_actionable_error(tmp_path):
    path = tmp_path / "session.json"
    _write_session(path, access=_jwt(sub="user-1", exp=900), expires_at=900)
    auth = DesktopAuth(DesktopSessionStore(path), clock=lambda: 1000)

    with pytest.raises(CredentialsError, match="supabase_anon_key"):
        auth()


def test_supabase_refresher_resolves_key_only_when_called():
    calls = []

    class Resolver:
        def resolve(self, project_ref):
            calls.append(project_ref)
            return ResolvedPublishableKey("resolved-key", "test")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"access_token":"new-token"}'

    requests = []

    def open_request(request, *, timeout):
        requests.append((request, timeout))
        return Response()

    refresher = SupabaseTokenRefresher(
        project_ref="project", key_resolver=Resolver(), opener=open_request
    )
    assert calls == []

    assert refresher("refresh-token") == {"access_token": "new-token"}
    assert calls == ["project"]
    assert requests[0][0].get_header("Apikey") == "resolved-key"
    assert refresher.key_source == "test"


def test_auth_status_reports_resolved_refresh_source(tmp_path):
    path = tmp_path / "session.json"
    _write_session(path, access=_jwt(sub="user-1", exp=2000))

    class Resolver:
        def resolve(self, project_ref):
            return ResolvedPublishableKey("resolved-key", "desktop:test")

    refresher = SupabaseTokenRefresher(project_ref="project", key_resolver=Resolver())
    auth = DesktopAuth(DesktopSessionStore(path), refresher, clock=lambda: 1000)

    status = auth.status()

    assert status.refresh_available is True
    assert status.refresh_source == "desktop:test"
