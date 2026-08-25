import json

import pytest

from wisprflow import CredentialsError, DesktopSessionStore


def test_reads_credentials_from_the_desktop_session(write_session, jwt):
    path = write_session(access_token=jwt(sub="user-1", exp=2000))
    store = DesktopSessionStore(path)

    credentials = store.load()

    assert credentials.user_id == "user-1"
    assert credentials.refresh_token == "refresh-1"
    assert credentials.expires_at == 2000
    assert credentials.session_path == path
    assert store.project_ref == "project"


def test_falls_back_to_jwt_claims_when_the_entry_omits_them(write_session, jwt):
    path = write_session(
        access_token=jwt(sub="user-from-token", exp=4242),
        expires_at=None,
        user_id=None,
    )

    credentials = DesktopSessionStore(path).load()

    assert credentials.user_id == "user-from-token"
    assert credentials.expires_at == 4242


def test_refresh_preserves_unknown_fields_and_the_outer_document(write_session, jwt):
    path = write_session()
    store = DesktopSessionStore(path)

    credentials = store.save_refresh(
        {
            "access_token": jwt(sub="user-1", exp=3000),
            "refresh_token": "refresh-2",
            "expires_at": 3000,
        }
    )

    assert credentials.refresh_token == "refresh-2"
    outer = json.loads(path.read_text(encoding="utf-8"))
    stored = json.loads(outer["sb-project-auth-token"])
    assert stored["future_field"] == {"preserved": True}
    assert outer["outer"] == "keep"


def test_refresh_derives_expiry_from_expires_in(write_session, jwt, monkeypatch):
    path = write_session()
    monkeypatch.setattr("wisprflow.auth.session.time.time", lambda: 1000.0)

    credentials = DesktopSessionStore(path).save_refresh(
        {"access_token": jwt(sub="user-1"), "expires_in": 3600}
    )

    assert credentials.expires_at == 4600


def test_refresh_keeps_the_entry_unencoded_when_the_desktop_wrote_it_that_way(
    write_session, jwt
):
    path = write_session(
        storage_key="sb-another-project-auth-token",
        encoded=False,
    )
    store = DesktopSessionStore(path)
    assert store.project_ref == "another-project"

    store.save_refresh({"access_token": jwt(sub="user-1", exp=3000)})

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(stored["sb-another-project-auth-token"], dict)
    assert stored["sb-another-project-auth-token"]["future_field"] == {
        "preserved": True
    }


def test_refresh_leaves_no_temporary_file_behind_when_writing_fails(
    write_session, jwt, monkeypatch
):
    path = write_session()
    monkeypatch.setattr(
        "wisprflow.auth.session.os.replace",
        lambda *args: (_ for _ in ()).throw(OSError("locked")),
    )
    store = DesktopSessionStore(path)

    with pytest.raises(CredentialsError, match="Cannot update"):
        store.save_refresh({"access_token": jwt(sub="user-1", exp=3000)})

    assert list(path.parent.glob("*.tmp")) == []


def test_missing_session_points_at_the_desktop_login(tmp_path):
    store = DesktopSessionStore(tmp_path / "missing.json")

    with pytest.raises(CredentialsError, match="Sign in first"):
        store.load()


def test_unreadable_session_is_reported_with_its_path(tmp_path):
    store = DesktopSessionStore(tmp_path)

    with pytest.raises(CredentialsError, match="Cannot read"):
        store.load()


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("{not json", "Cannot read"),
        ('["list"]', "Unexpected session format"),
        ("{}", "found 0"),
        (
            '{"sb-a-auth-token": {}, "sb-b-auth-token": {}}',
            "found 2",
        ),
        ('{"sb-a-auth-token": "{not json"}', "Malformed auth entry"),
        ('{"sb-a-auth-token": "[]"}', "Unexpected auth entry"),
        ('{"sb-a-auth-token": {"user": {"id": "user-1"}}}', "No access token"),
        ('{"sb-a-auth-token": {"access_token": "opaque"}}', "No user id"),
    ],
)
def test_malformed_sessions_explain_what_is_wrong(tmp_path, document, message):
    path = tmp_path / "session.json"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(CredentialsError, match=message):
        DesktopSessionStore(path).load()
