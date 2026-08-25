import base64
import json

from whisprflow import DefaultPublishableKeyResolver


def _anon_key(project_ref: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"ref": project_ref, "role": "anon"}).encode()
    ).rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.synthetic_signature"


def test_resolver_uses_config_before_environment(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "supabase_anon_keys": {
                    "project": "configured-key",
                    "other": "other-key",
                }
            }
        ),
        encoding="utf-8",
    )
    resolver = DefaultPublishableKeyResolver(
        config_path=config,
        environment={"WISPRFLOW_SUPABASE_ANON_KEY": "environment-key"},
        desktop_archives=[],
    )

    resolved = resolver.resolve("project")

    assert resolved is not None
    assert resolved.value == "configured-key"
    assert resolved.source == str(config)


def test_resolver_uses_environment_without_config(tmp_path):
    resolver = DefaultPublishableKeyResolver(
        config_path=tmp_path / "missing.json",
        environment={"WISPRFLOW_SUPABASE_ANON_KEY": "environment-key"},
        desktop_archives=[],
    )

    resolved = resolver.resolve("project")

    assert resolved is not None
    assert resolved.value == "environment-key"
    assert resolved.source == "WISPRFLOW_SUPABASE_ANON_KEY"


def test_resolver_finds_matching_legacy_key_in_desktop_archive(tmp_path):
    matching = _anon_key("project")
    archive = tmp_path / "app.asar"
    archive.write_bytes(
        b"bundle-prefix\x00"
        + _anon_key("unrelated").encode()
        + b"\x00bundle-middle\x00"
        + matching.encode()
        + b"\x00bundle-suffix"
    )
    resolver = DefaultPublishableKeyResolver(
        config_path=tmp_path / "missing.json",
        environment={},
        desktop_archives=[archive],
    )

    resolved = resolver.resolve("project")

    assert resolved is not None
    assert resolved.value == matching
    assert resolved.source == f"desktop:{archive}"


def test_resolver_can_disable_desktop_discovery(tmp_path):
    archive = tmp_path / "app.asar"
    archive.write_bytes(_anon_key("project").encode())
    resolver = DefaultPublishableKeyResolver(
        config_path=tmp_path / "missing.json",
        environment={},
        desktop_archives=[archive],
        auto_discover=False,
    )

    assert resolver.resolve("project") is None
