import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


def _encode_segment(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()


@pytest.fixture
def jwt() -> Callable[..., str]:
    """Build a signature-free JWT whose payload carries the given claims."""

    def build(**claims: Any) -> str:
        return f"{_encode_segment({'alg': 'HS256'})}.{_encode_segment(claims)}.sig"

    return build


@pytest.fixture
def write_session(tmp_path: Path, jwt: Callable[..., str]) -> Callable[..., Path]:
    """Write a desktop session file shaped like Supabase's local storage dump."""

    def write(
        *,
        access_token: str | None = None,
        refresh_token: str | None = "refresh-1",
        expires_at: float | None = 2000,
        user_id: str | None = "user-1",
        storage_key: str = "sb-project-auth-token",
        encoded: bool = True,
        name: str = "session.json",
    ) -> Path:
        auth: dict[str, Any] = {
            "access_token": access_token or jwt(sub=user_id, exp=expires_at),
            "future_field": {"preserved": True},
        }
        if refresh_token is not None:
            auth["refresh_token"] = refresh_token
        if expires_at is not None:
            auth["expires_at"] = expires_at
        if user_id is not None:
            auth["user"] = {"id": user_id}

        path = tmp_path / name
        path.write_text(
            json.dumps(
                {storage_key: json.dumps(auth) if encoded else auth, "outer": "keep"}
            ),
            encoding="utf-8",
        )
        return path

    return write
