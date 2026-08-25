import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from whisprflow.errors import CredentialsError
from whisprflow.models import AuthStatus, Credentials


class TokenRefresher(Protocol):
    def __call__(self, refresh_token: str, /) -> dict[str, Any]: ...


def _default_session_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Wispr Flow" / "session.json"
    return Path.home() / ".config" / "Wispr Flow" / "session.json"


class DesktopSessionStore:
    """Read and update the session owned by the official desktop client."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_session_path()

    def load(self) -> Credentials:
        outer, storage_key, auth = self._read()
        del outer
        access_token = auth.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise CredentialsError(f"No access token found in {self.path}.")
        refresh_token = auth.get("refresh_token")
        raw_user = auth.get("user")
        user: dict[str, Any] = raw_user if isinstance(raw_user, dict) else {}
        user_id = user.get("id") or _jwt_claim(access_token, "sub")
        if not isinstance(user_id, str) or not user_id:
            raise CredentialsError(f"No user id found in {self.path}.")
        expires_at = auth.get("expires_at")
        if not isinstance(expires_at, (int, float)):
            expires_at = _jwt_claim(access_token, "exp")
        project_ref = _project_ref(storage_key)
        self._project_ref = project_ref
        return Credentials(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            user_id=user_id,
            expires_at=float(expires_at)
            if isinstance(expires_at, (int, float))
            else None,
            session_path=self.path,
        )

    @property
    def project_ref(self) -> str:
        if not hasattr(self, "_project_ref"):
            self.load()
        return self._project_ref

    def save_refresh(self, payload: dict[str, Any]) -> Credentials:
        outer, storage_key, auth = self._read()
        for key in (
            "access_token",
            "refresh_token",
            "expires_at",
            "expires_in",
            "token_type",
            "user",
        ):
            if key in payload:
                auth[key] = payload[key]
        if "expires_at" not in payload and isinstance(
            payload.get("expires_in"), (int, float)
        ):
            auth["expires_at"] = int(time.time() + payload["expires_in"])

        original = outer[storage_key]
        outer[storage_key] = json.dumps(auth) if isinstance(original, str) else auth
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(outer, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise CredentialsError(f"Cannot update {self.path}: {exc}") from None
        return self.load()

    def _read(self) -> tuple[dict[str, Any], str, dict[str, Any]]:
        try:
            outer = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise CredentialsError(
                f"Wispr Flow session not found at {self.path}. Sign in first."
            ) from None
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialsError(f"Cannot read {self.path}: {exc}") from None
        if not isinstance(outer, dict):
            raise CredentialsError(f"Unexpected session format in {self.path}.")
        keys = [
            key
            for key in outer
            if key.startswith("sb-") and key.endswith("-auth-token")
        ]
        if len(keys) != 1:
            raise CredentialsError(
                f"Expected one Supabase auth entry in {self.path}, found {len(keys)}."
            )
        storage_key = keys[0]
        raw_auth = outer[storage_key]
        try:
            auth = json.loads(raw_auth) if isinstance(raw_auth, str) else raw_auth
        except json.JSONDecodeError as exc:
            raise CredentialsError(
                f"Malformed auth entry in {self.path}: {exc}"
            ) from None
        if not isinstance(auth, dict):
            raise CredentialsError(f"Unexpected auth entry in {self.path}.")
        return outer, storage_key, auth


class SupabaseTokenRefresher:
    """Refresh a desktop Supabase session using an explicitly supplied public key."""

    def __init__(
        self,
        *,
        project_ref: str,
        anon_key: str,
        timeout: float = 30.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not anon_key:
            raise ValueError("'anon_key' must not be empty.")
        self.url = (
            f"https://{project_ref}.supabase.co/auth/v1/token?grant_type=refresh_token"
        )
        self.anon_key = anon_key
        self.timeout = timeout
        self._opener = opener

    def __call__(self, refresh_token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            self.url,
            data=json.dumps({"refresh_token": refresh_token}).encode(),
            headers={
                "apikey": self.anon_key,
                "Authorization": f"Bearer {self.anon_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise CredentialsError(
                f"Wispr session refresh failed (HTTP {exc.code}): {detail}"
            ) from None
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialsError(f"Wispr session refresh failed: {exc}") from None
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise CredentialsError("Wispr session refresh returned no access token.")
        return payload


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
        return AuthStatus(
            status=status,
            expires_at=credentials.expires_at,
            seconds_remaining=remaining,
            refresh_available=bool(credentials.refresh_token and self.refresher),
        )


def _project_ref(storage_key: str) -> str:
    return storage_key.removeprefix("sb-").removesuffix("-auth-token")


def _jwt_claim(token: str, claim: str) -> Any:
    try:
        encoded = token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded))
    except (IndexError, ValueError, json.JSONDecodeError):
        return None
    return payload.get(claim)
