import base64
import json

import pytest

from whisprflow import CredentialsError, DesktopAuth, DesktopSessionStore


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


def test_expired_token_without_refresher_has_actionable_error(tmp_path):
    path = tmp_path / "session.json"
    _write_session(path, access=_jwt(sub="user-1", exp=900), expires_at=900)
    auth = DesktopAuth(DesktopSessionStore(path), clock=lambda: 1000)

    with pytest.raises(CredentialsError, match="supabase_anon_key"):
        auth()
