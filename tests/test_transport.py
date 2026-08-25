import sys
from types import SimpleNamespace

import pytest

from wisprflow import GrpcTransport, RuntimeRoute


class FakeChannel:
    def __init__(self, target: str):
        self.target = target
        self.closed = False
        self.calls: list[dict] = []

    def stream_stream(self, method, *, request_serializer, response_deserializer):
        self.method = method
        self.request_serializer = request_serializer
        self.response_deserializer = response_deserializer

        def call(requests, *, metadata, timeout):
            self.calls.append(
                {
                    "requests": list(requests),
                    "metadata": metadata,
                    "timeout": timeout,
                }
            )
            yield b"first"
            yield b"second"

        return call

    def close(self):
        self.closed = True


@pytest.fixture
def grpc(monkeypatch):
    channels: list[FakeChannel] = []

    def secure_channel(target, credentials):
        channel = FakeChannel(target)
        channels.append(channel)
        return channel

    monkeypatch.setitem(
        sys.modules,
        "grpc",
        SimpleNamespace(
            secure_channel=secure_channel,
            ssl_channel_credentials=lambda: "ssl-credentials",
        ),
    )
    return channels


def test_the_route_determines_target_method_and_metadata(grpc):
    route = RuntimeRoute(host="proxy.example", port=8443)

    responses = list(
        GrpcTransport().stream(
            [b"request"], route=route, access_token="token", timeout=12.0
        )
    )

    channel = grpc[0]
    assert responses == [b"first", b"second"]
    assert channel.target == "proxy.example:8443"
    assert channel.method == route.method
    assert channel.calls[0]["requests"] == [b"request"]
    assert channel.calls[0]["metadata"] == route.metadata("token")
    assert channel.calls[0]["timeout"] == 12.0


def test_frames_are_sent_and_received_unwrapped(grpc):
    list(
        GrpcTransport().stream(
            [b"request"], route=RuntimeRoute(), access_token="token", timeout=1.0
        )
    )

    channel = grpc[0]
    assert channel.request_serializer(b"raw") == b"raw"
    assert channel.response_deserializer(b"raw") == b"raw"


def test_the_channel_is_closed_after_the_stream_is_drained(grpc):
    list(
        GrpcTransport().stream(
            [b"request"], route=RuntimeRoute(), access_token="token", timeout=1.0
        )
    )

    assert grpc[0].closed is True


def test_the_channel_is_closed_when_the_caller_stops_early(grpc):
    stream = GrpcTransport().stream(
        [b"request"], route=RuntimeRoute(), access_token="token", timeout=1.0
    )
    assert next(stream) == b"first"
    assert grpc[0].closed is False

    stream.close()

    assert grpc[0].closed is True
