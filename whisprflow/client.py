from collections.abc import Callable
from pathlib import Path

from whisprflow.audio import normalized_audio
from whisprflow.audio_input import AudioInput
from whisprflow.auth import (
    DefaultPublishableKeyResolver,
    DesktopAuth,
    DesktopSessionStore,
    PublishableKeyResolver,
    SupabaseTokenRefresher,
)
from whisprflow.models import (
    AuthStatus,
    RuntimeRoute,
    TranscriptionContext,
    TranscriptionOptions,
    TranscriptResult,
)
from whisprflow.protocol import decode_responses, encode_requests
from whisprflow.transport import GrpcTransport, Transport


class WisprClient:
    """Clean facade over Wispr Flow's reverse-engineered transcription protocol."""

    def __init__(
        self,
        *,
        auth: Callable[[], str],
        user_id: str | Callable[[], str],
        route: RuntimeRoute | Callable[[], RuntimeRoute] | None = None,
        transport: Transport | None = None,
        timeout: float = 90.0,
    ) -> None:
        self._auth = auth
        self._user_id_provider: Callable[[], str]
        if isinstance(user_id, str):
            self._user_id_provider = lambda: user_id
        else:
            self._user_id_provider = user_id
        resolved_route = route or RuntimeRoute()
        self._route_provider: Callable[[], RuntimeRoute]
        if isinstance(resolved_route, RuntimeRoute):
            self._route_provider = lambda: resolved_route
        else:
            self._route_provider = resolved_route
        self._transport = transport or GrpcTransport()
        self._timeout = timeout

    @classmethod
    def from_desktop(
        cls,
        *,
        session_path: Path | None = None,
        supabase_anon_key: str | None = None,
        publishable_key_resolver: PublishableKeyResolver | None = None,
        config_path: Path | None = None,
        auto_discover: bool = True,
        route: RuntimeRoute | None = None,
        transport: Transport | None = None,
        timeout: float = 90.0,
    ) -> "WisprClient":
        """Reuse the official desktop login without modifying the application.

        The edge proxy is the patch-free default. Supabase refresh configuration
        is resolved lazily from an explicit key, SDK config, environment, or the
        installed desktop application. Pass ``auto_discover=False`` to disable
        inspection of the desktop bundle.
        """
        store = DesktopSessionStore(session_path)
        if publishable_key_resolver is not None and (
            supabase_anon_key is not None or config_path is not None
        ):
            raise ValueError(
                "A custom 'publishable_key_resolver' cannot be combined with "
                "'supabase_anon_key' or 'config_path'."
            )
        resolver = publishable_key_resolver or DefaultPublishableKeyResolver(
            explicit_key=supabase_anon_key,
            config_path=config_path,
            auto_discover=auto_discover,
        )
        refresher = SupabaseTokenRefresher(
            project_ref=store.project_ref,
            key_resolver=resolver,
        )
        auth = DesktopAuth(store, refresher)
        return cls(
            auth=auth,
            user_id=lambda: auth.user_id,
            route=route or RuntimeRoute(),
            transport=transport,
            timeout=timeout,
        )

    def auth_status(self) -> AuthStatus:
        if not isinstance(self._auth, DesktopAuth):
            raise TypeError("Auth status is only available for desktop authentication.")
        return self._auth.status()

    def transcribe_bytes(
        self,
        audio: bytes,
        *,
        options: TranscriptionOptions | None = None,
        context: TranscriptionContext | None = None,
    ) -> TranscriptResult:
        """Transcribe an already-normalized mono 16 kHz PCM16 WAV payload."""
        if not audio:
            raise ValueError("'audio' must not be empty.")
        options = options or TranscriptionOptions()
        access_token = self._auth()
        user_id = self._user_id_provider()
        route = self._route_provider()
        requests = encode_requests(
            user_id=user_id,
            audio=audio,
            options=options,
            context=context,
        )
        responses = self._transport.stream(
            requests,
            route=route,
            access_token=access_token,
            timeout=self._timeout,
        )
        return decode_responses(responses, options)

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        options: TranscriptionOptions | None = None,
        context: TranscriptionContext | None = None,
    ) -> TranscriptResult:
        """Normalize an audio file and transcribe it."""
        with normalized_audio(audio_path) as audio:
            return self.transcribe_bytes(audio, options=options, context=context)

    def transcribe_input(
        self,
        source: AudioInput,
        *,
        options: TranscriptionOptions | None = None,
        context: TranscriptionContext | None = None,
    ) -> TranscriptResult:
        """Capture WAV audio from an input adapter and transcribe it."""
        return self.transcribe_bytes(source.capture(), options=options, context=context)
