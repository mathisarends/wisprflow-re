from contextlib import contextmanager
from pathlib import Path

from whisprflow import (
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
        client.transcribe(123)  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "Unsupported audio source: <class 'int'>"
    else:
        raise AssertionError("Expected unsupported source to raise TypeError")
