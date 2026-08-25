import base64
import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from whisprflow.errors import CredentialsError
from whisprflow.models import Credentials


def _default_session_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Wispr Flow" / "session.json"
    return Path.home() / ".config" / "Wispr Flow" / "session.json"


@dataclass(slots=True)
class _SessionAuth:
    values: dict[str, Any]
    access_token: str
    refresh_token: str | None
    user_id: str
    expires_at: float | None

    @classmethod
    def parse(cls, values: dict[str, Any], *, path: Path) -> "_SessionAuth":
        access_token = values.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise CredentialsError(f"No access token found in {path}.")

        refresh_token = values.get("refresh_token")
        raw_user = values.get("user")
        user = raw_user if isinstance(raw_user, dict) else {}
        user_id = user.get("id") or _jwt_claim(access_token, "sub")
        if not isinstance(user_id, str) or not user_id:
            raise CredentialsError(f"No user id found in {path}.")

        expires_at = values.get("expires_at")
        if not isinstance(expires_at, (int, float)):
            expires_at = _jwt_claim(access_token, "exp")

        return cls(
            values=values,
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            user_id=user_id,
            expires_at=(
                float(expires_at) if isinstance(expires_at, (int, float)) else None
            ),
        )

    def with_refresh(self, payload: dict[str, Any], *, path: Path) -> "_SessionAuth":
        values = self.values.copy()
        for key in (
            "access_token",
            "refresh_token",
            "expires_at",
            "expires_in",
            "token_type",
            "user",
        ):
            if key in payload:
                values[key] = payload[key]
        if "expires_at" not in payload and isinstance(
            payload.get("expires_in"), (int, float)
        ):
            values["expires_at"] = int(time.time() + payload["expires_in"])
        return self.parse(values, path=path)

    def credentials(self, *, path: Path) -> Credentials:
        return Credentials(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            user_id=self.user_id,
            expires_at=self.expires_at,
            session_path=path,
        )


@dataclass(slots=True)
class _SessionDocument:
    outer: dict[str, Any]
    storage_key: str
    auth: _SessionAuth
    auth_was_json_string: bool

    @classmethod
    def parse(cls, text: str, *, path: Path) -> "_SessionDocument":
        try:
            outer = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CredentialsError(f"Cannot read {path}: {exc}") from None
        if not isinstance(outer, dict):
            raise CredentialsError(f"Unexpected session format in {path}.")

        keys = [
            key
            for key in outer
            if key.startswith("sb-") and key.endswith("-auth-token")
        ]
        if len(keys) != 1:
            raise CredentialsError(
                f"Expected one Supabase auth entry in {path}, found {len(keys)}."
            )

        storage_key = keys[0]
        raw_auth = outer[storage_key]
        try:
            auth_values = (
                json.loads(raw_auth) if isinstance(raw_auth, str) else raw_auth
            )
        except json.JSONDecodeError as exc:
            raise CredentialsError(f"Malformed auth entry in {path}: {exc}") from None
        if not isinstance(auth_values, dict):
            raise CredentialsError(f"Unexpected auth entry in {path}.")

        return cls(
            outer=outer,
            storage_key=storage_key,
            auth=_SessionAuth.parse(auth_values, path=path),
            auth_was_json_string=isinstance(raw_auth, str),
        )

    @property
    def project_ref(self) -> str:
        return _project_ref(self.storage_key)

    def with_refresh(
        self, payload: dict[str, Any], *, path: Path
    ) -> "_SessionDocument":
        return replace(self, auth=self.auth.with_refresh(payload, path=path))

    def to_json(self) -> str:
        outer = self.outer.copy()
        auth: str | dict[str, Any] = self.auth.values
        if self.auth_was_json_string:
            auth = json.dumps(auth)
        outer[self.storage_key] = auth
        return json.dumps(outer, indent=2)


class DesktopSessionStore:
    """Read and update the session owned by the official desktop client."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else _default_session_path()

    def load(self) -> Credentials:
        return self._read().auth.credentials(path=self.path)

    @property
    def project_ref(self) -> str:
        return self._read().project_ref

    def save_refresh(self, payload: dict[str, Any]) -> Credentials:
        document = self._read().with_refresh(payload, path=self.path)
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(document.to_json(), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise CredentialsError(f"Cannot update {self.path}: {exc}") from None
        return self.load()

    def _read(self) -> _SessionDocument:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise CredentialsError(
                f"Wispr Flow session not found at {self.path}. Sign in first."
            ) from None
        except OSError as exc:
            raise CredentialsError(f"Cannot read {self.path}: {exc}") from None
        return _SessionDocument.parse(text, path=self.path)


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
