from collections.abc import Iterable
from typing import Protocol

from wisprflow.models import RuntimeRoute


class Transport(Protocol):
    def stream(
        self,
        requests: Iterable[bytes],
        *,
        route: RuntimeRoute,
        access_token: str,
        timeout: float,
    ) -> Iterable[bytes]: ...


class GrpcTransport:
    def stream(
        self,
        requests: Iterable[bytes],
        *,
        route: RuntimeRoute,
        access_token: str,
        timeout: float,
    ) -> Iterable[bytes]:
        import grpc

        channel = grpc.secure_channel(
            f"{route.host}:{route.port}", grpc.ssl_channel_credentials()
        )
        method = channel.stream_stream(
            route.method,
            request_serializer=lambda value: value,
            response_deserializer=lambda value: value,
        )
        try:
            yield from method(
                requests,
                metadata=route.metadata(access_token),
                timeout=timeout,
            )
        finally:
            channel.close()
