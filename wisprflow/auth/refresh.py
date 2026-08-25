import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from wisprflow.auth.keys import PublishableKeyResolver
from wisprflow.errors import CredentialsError


class SupabaseTokenRefresher:
    """Refresh a desktop Supabase session using a resolved public key."""

    def __init__(
        self,
        *,
        project_ref: str,
        anon_key: str | None = None,
        key_resolver: PublishableKeyResolver | None = None,
        timeout: float = 30.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not anon_key and key_resolver is None:
            raise ValueError("Either 'anon_key' or 'key_resolver' is required.")
        self.url = (
            f"https://{project_ref}.supabase.co/auth/v1/token?grant_type=refresh_token"
        )
        self.anon_key = anon_key
        self.project_ref = project_ref
        self.key_resolver = key_resolver
        self.key_source = "explicit" if anon_key else None
        self.timeout = timeout
        self._opener = opener

    def resolve_key(self) -> str | None:
        anon_key = self.anon_key
        if not anon_key and self.key_resolver is not None:
            resolved = self.key_resolver.resolve(self.project_ref)
            if resolved is not None:
                anon_key = resolved.value
                self.key_source = resolved.source
        return anon_key

    def __call__(self, refresh_token: str) -> dict[str, Any]:
        anon_key = self.resolve_key()
        if not anon_key:
            raise CredentialsError(
                "Wispr access token expired and no Supabase publishable key could "
                "be found. Set WISPRFLOW_SUPABASE_ANON_KEY, add it to the SDK "
                "config, or pass 'supabase_anon_key' explicitly."
            )
        request = urllib.request.Request(
            self.url,
            data=json.dumps({"refresh_token": refresh_token}).encode(),
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {anon_key}",
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
