import json
from contextlib import contextmanager
from pathlib import Path

from whisprflow import (
    AppType,
    EditingStrength,
    RuntimeRoute,
    TranscriptionContext,
    TranscriptionOptions,
    WisprClient,
)
from whisprflow.protocol import _message, _string


class RecordingTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def stream(self, requests, **kwargs):
        self.calls.append((list(requests), kwargs))
        return self.responses


def test_client_hides_auth_route_and_protocol_details():
    transcription = _string(2, "Hello world")
    result = _message(1, transcription) + b"\x28\x01"
    response = _message(1, result)
    transport = RecordingTransport([response])
    route = RuntimeRoute(host="proxy.example")
    client = WisprClient(
        auth=lambda: "synthetic-token",
        user_id="user-1",
        route=route,
        transport=transport,
    )

    output = client.transcribe(
        b"RIFF synthetic wav",
        options=TranscriptionOptions(
            replacements={"world": "SDK"}, client_version=(1, 2, 3)
        ),
        context=TranscriptionContext(before_text="Greeting:"),
    )

    assert output.final == "Hello SDK"
    assert output.status == 1
    packets, kwargs = transport.calls[0]
    assert len(packets) == 3
    assert kwargs["route"] == route
    assert kwargs["access_token"] == "synthetic-token"


def test_client_uses_options_provider_only_when_options_are_omitted():
    response = _message(1, _message(1, _string(2, "Desktop output")))
    transport = RecordingTransport([response, response])
    seen_app_types = []

    def options_provider(app_type):
        seen_app_types.append(app_type)
        return TranscriptionOptions(
            app_type=app_type,
            cleanup=EditingStrength.LIGHT,
        )

    client = WisprClient(
        auth=lambda: "synthetic-token",
        user_id="user-1",
        options_provider=options_provider,
        transport=transport,
    )

    client.transcribe(
        b"RIFF first wav",
        context=TranscriptionContext(app_type=AppType.EMAIL),
    )
    client.transcribe(
        b"RIFF second wav",
        options=TranscriptionOptions(cleanup=EditingStrength.HEAVY),
    )

    assert seen_app_types == [AppType.EMAIL]


def test_from_desktop_can_enable_desktop_preferences(tmp_path, monkeypatch):
    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "sb-project-auth-token": json.dumps(
                    {
                        "access_token": "synthetic-access-token",
                        "refresh_token": "synthetic-refresh-token",
                        "expires_at": 9_999_999_999,
                        "user": {"id": "user-1"},
                    }
                )
            }
        ),
        encoding="utf-8",
    )
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
        "whisprflow.client.DesktopPreferencesStore", FakePreferencesStore
    )
    response = _message(1, _message(1, _string(2, "Desktop output")))
    client = WisprClient.from_desktop(
        session_path=session_path,
        supabase_anon_key="synthetic-key",
        use_desktop_preferences=True,
        preferences_config_path=preferences_config,
        preferences_database_path=preferences_database,
        transport=RecordingTransport([response]),
    )

    result = client.transcribe(
        b"RIFF synthetic wav",
        context=TranscriptionContext(app_type=AppType.EMAIL),
    )

    assert result.final == "Loaded output"
    assert seen == {
        "paths": (preferences_config, preferences_database),
        "app_type": AppType.EMAIL,
    }


def test_edge_route_does_not_require_private_backend_key():
    metadata = dict(RuntimeRoute().metadata("token"))
    assert metadata["authorization"] == "Bearer token"
    assert "baseten-authorization" not in metadata
    assert "baseten-model-id" not in metadata


def test_direct_route_formats_explicit_backend_values():
    route = RuntimeRoute(
        host="model.example",
        model_id="abc",
        environment="production",
        backend_key="placeholder",
    )
    metadata = dict(route.metadata("token"))
    assert metadata["baseten-authorization"] == "Api-Key placeholder"
    assert metadata["baseten-model-id"] == "model-abc"


def test_client_can_capture_from_audio_input():
    response = _message(1, _message(1, _string(2, "From microphone")))
    transport = RecordingTransport([response])
    client = WisprClient(
        auth=lambda: "synthetic-token",
        user_id="user-1",
        transport=transport,
    )

    class FakeInput:
        def capture(self):
            return b"RIFF synthetic microphone wav"

    output = client.transcribe(FakeInput())

    assert output.final == "From microphone"


def test_client_normalizes_file_source(monkeypatch):
    response = _message(1, _message(1, _string(2, "From file")))
    transport = RecordingTransport([response])
    client = WisprClient(
        auth=lambda: "synthetic-token",
        user_id="user-1",
        transport=transport,
    )
    source = Path("recording.mp3")

    @contextmanager
    def fake_normalized_audio(path):
        assert path == source
        yield b"RIFF normalized wav"

    monkeypatch.setattr("whisprflow.client.normalized_audio", fake_normalized_audio)

    output = client.transcribe(source)

    assert output.final == "From file"


def test_client_rejects_unsupported_audio_source():
    client = WisprClient(auth=lambda: "token", user_id="user-1")

    try:
        client.transcribe(123)  # ty: ignore[no-matching-overload]
    except TypeError as exc:
        assert str(exc) == "Unsupported audio source: <class 'int'>"
    else:
        raise AssertionError("Expected unsupported source to raise TypeError")
