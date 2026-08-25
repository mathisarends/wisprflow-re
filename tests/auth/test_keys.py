import base64
import json

import pytest

from whisprflow import DefaultPublishableKeyResolver


def _anon_key(project_ref: str, *, role: str = "anon") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"ref": project_ref, "role": role}).encode()
    ).rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.synthetic_signature"


def _write_archive(path, *keys: str) -> None:
    path.write_bytes(b"\x00".join(key.encode() for key in keys))


@pytest.fixture
def resolver(tmp_path):
    def build(**overrides):
        options = {
            "config_path": tmp_path / "missing.json",
            "environment": {},
            "desktop_archives": [],
        }
        options.update(overrides)
        return DefaultPublishableKeyResolver(**options)

    return build


def test_an_explicit_key_wins_over_every_other_source(resolver, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"supabase_anon_key": "configured"}), "utf-8")

    resolved = resolver(explicit_key="explicit-key", config_path=config).resolve(
        "project"
    )

    assert resolved is not None
    assert resolved.value == "explicit-key"
    assert resolved.source == "explicit"


def test_config_is_preferred_over_the_environment(resolver, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {"supabase_anon_keys": {"project": "configured-key", "other": "other-key"}}
        ),
        encoding="utf-8",
    )

    resolved = resolver(
        config_path=config,
        environment={"WISPRFLOW_SUPABASE_ANON_KEY": "environment-key"},
    ).resolve("project")

    assert resolved is not None
    assert resolved.value == "configured-key"
    assert resolved.source == str(config)


def test_a_single_configured_key_serves_any_project(resolver, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"supabase_anon_keys": {"other": "x"}, "supabase_anon_key": "flat"}),
        encoding="utf-8",
    )

    resolved = resolver(config_path=config).resolve("project")

    assert resolved is not None
    assert resolved.value == "flat"


@pytest.mark.parametrize("document", ["[]", '{"supabase_anon_key": 42}', "{not json"])
def test_an_unusable_config_falls_through_to_the_environment(
    resolver, tmp_path, document
):
    config = tmp_path / "config.json"
    config.write_text(document, encoding="utf-8")

    resolved = resolver(
        config_path=config,
        environment={"WISPRFLOW_SUPABASE_ANON_KEY": "environment-key"},
    ).resolve("project")

    assert resolved is not None
    assert resolved.value == "environment-key"
    assert resolved.source == "WISPRFLOW_SUPABASE_ANON_KEY"


def test_the_desktop_archive_yields_the_key_minted_for_this_project(resolver, tmp_path):
    matching = _anon_key("project")
    archive = tmp_path / "app.asar"
    _write_archive(
        archive,
        _anon_key("unrelated"),
        matching,
        _anon_key("project", role="service_role"),
    )

    resolved = resolver(desktop_archives=[archive]).resolve("project")

    assert resolved is not None
    assert resolved.value == matching
    assert resolved.source == f"desktop:{archive}"


def test_a_publishable_key_is_used_when_no_legacy_key_matches(resolver, tmp_path):
    archive = tmp_path / "app.asar"
    archive.write_bytes(b"prefix sb_publishable_abcdefghijklmnopqrstuvwxyz suffix")

    resolved = resolver(desktop_archives=[archive]).resolve("project")

    assert resolved is not None
    assert resolved.value == "sb_publishable_abcdefghijklmnopqrstuvwxyz"


def test_an_ambiguous_archive_is_not_guessed(resolver, tmp_path):
    archive = tmp_path / "app.asar"
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    claims = json.dumps({"ref": "project", "role": "anon"}).encode()
    payload = base64.urlsafe_b64encode(claims).rstrip(b"=").decode()
    _write_archive(
        archive,
        f"{header}.{payload}.signature_one",
        f"{header}.{payload}.signature_two",
    )

    assert resolver(desktop_archives=[archive]).resolve("project") is None


def test_an_unreadable_archive_is_skipped(resolver, tmp_path):
    assert resolver(desktop_archives=[tmp_path]).resolve("project") is None


def test_discovery_can_be_disabled(resolver, tmp_path):
    archive = tmp_path / "app.asar"
    _write_archive(archive, _anon_key("project"))

    assert (
        resolver(desktop_archives=[archive], auto_discover=False).resolve("project")
        is None
    )


def test_a_resolved_key_is_scanned_for_only_once(resolver, tmp_path):
    archive = tmp_path / "app.asar"
    _write_archive(archive, _anon_key("project"))
    instance = resolver(desktop_archives=[archive])
    first = instance.resolve("project")

    archive.unlink()

    assert instance.resolve("project") == first
