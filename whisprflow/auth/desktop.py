import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from whisprflow.auth.refresh import SupabaseTokenRefresher
from whisprflow.auth.session import DesktopSessionStore
from whisprflow.errors import CredentialsError
from whisprflow.models import AuthStatus, Credentials


class TokenRefresher(Protocol):
    def __call__(self, refresh_token: str, /) -> dict[str, Any]: ...


class DesktopAuth:
    """Callable access-token provider with refresh-on-demand semantics."""

    def __init__(
        self,
        store: DesktopSessionStore,
        refresher: TokenRefresher | None = None,
        *,
        refresh_skew_seconds: float = 120.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.refresher = refresher
        self.refresh_skew_seconds = refresh_skew_seconds
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def credentials(self) -> Credentials:
        return self.store.load()

    @property
    def user_id(self) -> str:
        return self.credentials.user_id

    def __call__(self) -> str:
        with self._lock:
            credentials = self.store.load()
            if credentials.is_fresh(
                now=self._clock(), skew_seconds=self.refresh_skew_seconds
            ):
                return credentials.access_token
            if not credentials.refresh_token:
                raise CredentialsError(
                    "Wispr access token expired and no refresh token is available."
                )
            if self.refresher is None:
                raise CredentialsError(
                    "Wispr access token expired. Supply 'supabase_anon_key' to "
                    "WisprClient.from_desktop() or sign in again with Wispr Flow."
                )
            payload = self.refresher(credentials.refresh_token)
            return self.store.save_refresh(payload).access_token

    def status(self) -> AuthStatus:
        credentials = self.store.load()
        now = self._clock()
        remaining = (
            None if credentials.expires_at is None else credentials.expires_at - now
        )
        if remaining is None or remaining > self.refresh_skew_seconds:
            status = "valid"
        elif remaining > 0:
            status = "near_expiry"
        else:
            status = "expired"
        refresh_available = bool(credentials.refresh_token and self.refresher)
        refresh_source = None
        if credentials.refresh_token and isinstance(
            self.refresher, SupabaseTokenRefresher
        ):
            refresh_available = self.refresher.resolve_key() is not None
            refresh_source = self.refresher.key_source
        return AuthStatus(
            status=status,
            expires_at=credentials.expires_at,
            seconds_remaining=remaining,
            refresh_available=refresh_available,
            refresh_source=refresh_source,
        )
