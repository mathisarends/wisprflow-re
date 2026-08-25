from collections.abc import Callable
from pathlib import Path
from typing import overload

from whisprflow.audio import normalized_audio
from whisprflow.audio_input import AudioInput
from whisprflow.auth import (
    DefaultPublishableKeyResolver,
    DesktopAuth,
    DesktopSessionStore,
    PublishableKeyResolver,
    SupabaseTokenRefresher,
)
from whisprflow.desktop_preferences import DesktopPreferencesStore
from whisprflow.models import (
    AppType,
    AuthStatus,
    RuntimeRoute,
    TranscriptionContext,
    TranscriptionOptions,
    TranscriptResult,
)
from whisprflow.protocol import decode_responses, encode_requests
from whisprflow.transport import GrpcTransport, Transport

type AudioSource = str | Path | bytes | AudioInput


class WisprClient:
    """Clean facade over Wispr Flow's reverse-engineered transcription protocol."""

    def __init__(
        self,
        *,
        auth: Callable[[], str],
        user_id: str | Callable[[], str],
        route: RuntimeRoute | Callable[[], RuntimeRoute] | None = None,
        options_provider: Callable[[AppType], TranscriptionOptions] | None = None,
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
        self._options_provider = options_provider
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
        use_desktop_preferences: bool = False,
        preferences_config_path: Path | None = None,
        preferences_database_path: Path | None = None,
        route: RuntimeRoute | None = None,
        transport: Transport | None = None,
        timeout: float = 90.0,
    ) -> "WisprClient":
        """Reuse the official desktop login without modifying the application.

        The edge proxy is the patch-free default. Supabase refresh configuration
        is resolved lazily from an explicit key, SDK config, environment, or the
        installed desktop application. Pass ``auto_discover=False`` to disable
        inspection of the desktop bundle. Pass ``use_desktop_preferences=True``
        to reload preferences from the official desktop files for requests that
        do not supply explicit options.
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
        options_provider = None
        if use_desktop_preferences:
            preferences = DesktopPreferencesStore(
                config_path=preferences_config_path,
                database_path=preferences_database_path,
            )
            options_provider = preferences.load
        return cls(
            auth=auth,
            user_id=lambda: auth.user_id,
            route=route or RuntimeRoute(),
            options_provider=options_provider,
            transport=transport,
            timeout=timeout,
        )

    def auth_status(self) -> AuthStatus:
        if not isinstance(self._auth, DesktopAuth):
            raise TypeError("Auth status is only available for desktop authentication.")
        return self._auth.status()

    @overload
    def transcribe(
        self,
        source: str | Path,
        *,
        options: TranscriptionOptions | None = None,
        context: TranscriptionContext | None = None,
    ) -> TranscriptResult: ...

    @overload
    def transcribe(
        self,
        source: bytes,
        *,
        options: TranscriptionOptions | None = None,
        context: TranscriptionContext | None = None,
    ) -> TranscriptResult: ...

    @overload
    def transcribe(
        self,
        source: AudioInput,
        *,
        options: TranscriptionOptions | None = None,
        context: TranscriptionContext | None = None,
    ) -> TranscriptResult: ...

    def transcribe(
        self,
        source: AudioSource,
        *,
        options: TranscriptionOptions | None = None,
        context: TranscriptionContext | None = None,
    ) -> TranscriptResult:
        """Transcribe an audio file, normalized WAV payload, or input adapter."""
        match source:
            case bytes():
                audio = source
            case str() | Path():
                with normalized_audio(source) as audio:
                    return self._transcribe_audio(
                        audio,
                        options=options,
                        context=context,
                    )
            case AudioInput():
                audio = source.capture()
            case _:
                raise TypeError(f"Unsupported audio source: {type(source)!r}")

        return self._transcribe_audio(
            audio,
            options=options,
            context=context,
        )

    def _transcribe_audio(
        self,
        audio: bytes,
        *,
        options: TranscriptionOptions | None,
        context: TranscriptionContext | None,
    ) -> TranscriptResult:
        if not audio:
            raise ValueError("'audio' must not be empty.")
        if options is None:
            app_type = context.app_type if context is not None else AppType.OTHER
            options = (
                self._options_provider(app_type)
                if self._options_provider is not None
                else TranscriptionOptions()
            )
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
