from contextlib import contextmanager
from pathlib import Path

import pytest

from wisprflow import (
    AppType,
    DefaultPublishableKeyResolver,
    EditingStrength,
    RuntimeRoute,
    TranscriptionContext,
    TranscriptionOptions,
    WisprClient,
)
from wisprflow.protocol import _message, _string


class RecordingTransport:
    def __init__(self, transcript: str = "Hello world", calls: int = 1):
        self.responses = [_message(1, _message(1, _string(2, transcript)))]
        self.calls: list[tuple[list[bytes], dict]] = []
        self._remaining = calls

    def stream(self, requests, **kwargs):
        self.calls.append((list(requests), kwargs))
        return self.responses


def client(transport: RecordingTransport, **overrides) -> WisprClient:
    options = {
        "auth": lambda: "synthetic-token",
        "user_id": "user-1",
        "transport": transport,
    }
    options.update(overrides)
    return WisprClient(**options)


def test_the_client_hides_auth_route_and_protocol_details():
    transport = RecordingTransport("Hello world")
    route = RuntimeRoute(host="proxy.example")

    output = client(transport, route=route, timeout=30.0).transcribe(
        b"RIFF synthetic wav",
        options=TranscriptionOptions(replacements={"world": "SDK"}),
        context=TranscriptionContext(before_text="Greeting:"),
    )

    assert output.final == "Hello SDK"
    packets, kwargs = transport.calls[0]
    assert len(packets) == 3, "init, context and audio frames"
    assert kwargs == {
        "route": route,
        "access_token": "synthetic-token",
        "timeout": 30.0,
    }


def test_auth_user_and_route_are_resolved_per_request():
    transport = RecordingTransport(calls=2)
    tokens = iter(["token-1", "token-2"])
    routes = [RuntimeRoute(host="first.example"), RuntimeRoute(host="second.example")]
    instance = client(
        transport,
        auth=lambda: next(tokens),
        user_id=lambda: "user-1",
        route=lambda: routes.pop(0),
    )

    instance.transcribe(b"RIFF one")
    instance.transcribe(b"RIFF two")

    assert [call[1]["access_token"] for call in transport.calls] == [
        "token-1",
        "token-2",
    ]
    assert [call[1]["route"].host for call in transport.calls] == [
        "first.example",
        "second.example",
    ]


def test_the_options_provider_is_used_only_when_options_are_omitted():
    transport = RecordingTransport("Desktop output")
    seen: list[AppType] = []

    def options_provider(app_type):
        seen.append(app_type)
        return TranscriptionOptions(app_type=app_type, cleanup=EditingStrength.LIGHT)

    instance = client(transport, options_provider=options_provider)

    instance.transcribe(
        b"RIFF first wav", context=TranscriptionContext(app_type=AppType.EMAIL)
    )
    instance.transcribe(b"RIFF second wav")
    instance.transcribe(
        b"RIFF third wav", options=TranscriptionOptions(cleanup=EditingStrength.HEAVY)
    )

    assert seen == [AppType.EMAIL, AppType.OTHER]


def test_an_audio_input_adapter_is_captured_lazily():
    transport = RecordingTransport("From microphone")
    captures = []

    class FakeInput:
        def capture(self):
            captures.append("captured")
            return b"RIFF synthetic microphone wav"

    output = client(transport).transcribe(FakeInput())

    assert output.final == "From microphone"
    assert captures == ["captured"]


def test_a_file_source_is_normalized_before_upload(monkeypatch):
    transport = RecordingTransport("From file")
    source = Path("recording.mp3")

    @contextmanager
    def fake_normalized_audio(path):
        assert path == source
        yield b"RIFF normalized wav"

    monkeypatch.setattr("wisprflow.client.normalized_audio", fake_normalized_audio)

    assert client(transport).transcribe(source).final == "From file"


def test_an_unsupported_source_names_the_offending_type():
    with pytest.raises(TypeError, match="Unsupported audio source: <class 'int'>"):
        client(RecordingTransport()).transcribe(123)  # ty: ignore[no-matching-overload]


def test_empty_audio_is_rejected_before_contacting_the_backend():
    transport = RecordingTransport()

    with pytest.raises(ValueError, match="must not be empty"):
        client(transport).transcribe(b"")

    assert transport.calls == []


def test_auth_status_is_only_offered_for_desktop_sessions():
    with pytest.raises(TypeError, match="desktop authentication"):
        client(RecordingTransport()).auth_status()


def test_from_desktop_reports_the_status_of_the_desktop_session(write_session):
    instance = WisprClient.from_desktop(
        session_path=write_session(expires_at=9_999_999_999),
        supabase_anon_key="synthetic-key",
        transport=RecordingTransport(),
    )

    status = instance.auth_status()

    assert status.ok is True
    assert status.refresh_available is True
    assert status.refresh_source == "explicit"


def test_from_desktop_transcribes_with_the_desktop_identity(write_session):
    transport = RecordingTransport("From desktop")
    instance = WisprClient.from_desktop(
        session_path=write_session(expires_at=9_999_999_999),
        supabase_anon_key="synthetic-key",
        transport=transport,
    )

    output = instance.transcribe(b"RIFF synthetic wav")

    assert output.final == "From desktop"
    assert transport.calls[0][1]["access_token"].startswith("eyJ")


def test_from_desktop_can_load_preferences_from_the_desktop_files(
    write_session, tmp_path, monkeypatch
):
    preferences_config = tmp_path / "desktop-config.json"
    preferences_database = tmp_path / "flow.sqlite"
    seen = {}

    class FakePreferencesStore:
        def __init__(self, *, config_path, database_path):
            seen["paths"] = (config_path, database_path)

        def load(self, app_type):
            seen["app_type"] = app_type
            return TranscriptionOptions(replacements={"Desktop": "Loaded"})

    monkeypatch.setattr(
        "wisprflow.client.DesktopPreferencesStore", FakePreferencesStore
    )
    instance = WisprClient.from_desktop(
        session_path=write_session(expires_at=9_999_999_999),
        supabase_anon_key="synthetic-key",
        use_desktop_preferences=True,
        preferences_config_path=preferences_config,
        preferences_database_path=preferences_database,
        transport=RecordingTransport("Desktop output"),
    )

    result = instance.transcribe(
        b"RIFF synthetic wav", context=TranscriptionContext(app_type=AppType.EMAIL)
    )

    assert result.final == "Loaded output"
    assert seen == {
        "paths": (preferences_config, preferences_database),
        "app_type": AppType.EMAIL,
    }


@pytest.mark.parametrize(
    "conflicting", [{"supabase_anon_key": "key"}, {"config_path": Path("config.json")}]
)
def test_a_custom_key_resolver_cannot_be_combined_with_key_settings(
    write_session, conflicting
):
    with pytest.raises(ValueError, match="publishable_key_resolver"):
        WisprClient.from_desktop(
            session_path=write_session(),
            publishable_key_resolver=DefaultPublishableKeyResolver(),
            **conflicting,
        )
