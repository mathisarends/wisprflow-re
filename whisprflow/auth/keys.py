import base64
import json
import os
import re
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_LEGACY_ANON_KEY = re.compile(
    rb"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
)
_PUBLISHABLE_KEY = re.compile(rb"sb_publishable_[A-Za-z0-9_-]{16,}")
_SCAN_CHUNK_SIZE = 1024 * 1024
_SCAN_OVERLAP = 4096


@dataclass(frozen=True, slots=True)
class ResolvedPublishableKey:
    value: str
    source: str


class PublishableKeyResolver(Protocol):
    def resolve(self, project_ref: str) -> ResolvedPublishableKey | None: ...


class DefaultPublishableKeyResolver:
    """Resolve a Supabase public key without exposing token details to callers."""

    def __init__(
        self,
        *,
        explicit_key: str | None = None,
        config_path: Path | None = None,
        environment: Mapping[str, str] | None = None,
        desktop_archives: Sequence[Path] | None = None,
        auto_discover: bool = True,
    ) -> None:
        self.explicit_key = explicit_key
        self.config_path = config_path or _default_config_path()
        self.environment = environment if environment is not None else os.environ
        self.desktop_archives = desktop_archives
        self.auto_discover = auto_discover
        self._cache: dict[str, ResolvedPublishableKey | None] = {}
        self._lock = threading.Lock()

    def resolve(self, project_ref: str) -> ResolvedPublishableKey | None:
        with self._lock:
            if project_ref in self._cache:
                return self._cache[project_ref]
            resolved = self._resolve(project_ref)
            if resolved is not None:
                self._cache[project_ref] = resolved
            return resolved

    def _resolve(self, project_ref: str) -> ResolvedPublishableKey | None:
        if self.explicit_key:
            return ResolvedPublishableKey(self.explicit_key, "explicit")

        configured = _read_config_key(self.config_path, project_ref)
        if configured:
            return ResolvedPublishableKey(configured, str(self.config_path))

        environment_key = self.environment.get("WISPRFLOW_SUPABASE_ANON_KEY")
        if environment_key:
            return ResolvedPublishableKey(
                environment_key, "WISPRFLOW_SUPABASE_ANON_KEY"
            )

        if not self.auto_discover:
            return None
        archives = (
            list(self.desktop_archives)
            if self.desktop_archives is not None
            else _desktop_archives()
        )
        for archive in archives:
            key = _find_key_in_archive(archive, project_ref)
            if key:
                return ResolvedPublishableKey(key, f"desktop:{archive}")
        return None


def _default_config_path() -> Path:
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "wisprflow-re" / "config.json"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "wisprflow-re"
            / "config.json"
        )
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "wisprflow-re" / "config.json"


def _read_config_key(path: Path, project_ref: str) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    project_keys = payload.get("supabase_anon_keys")
    if isinstance(project_keys, dict):
        key = project_keys.get(project_ref)
        if isinstance(key, str) and key:
            return key
    key = payload.get("supabase_anon_key")
    return key if isinstance(key, str) and key else None


def _desktop_archives() -> list[Path]:
    candidates: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        root = Path(local_appdata) / "WisprFlow"
        candidates.extend(root.glob("app-*/resources/app.asar"))
    candidates.extend(
        [
            Path("/Applications/Wispr Flow.app/Contents/Resources/app.asar"),
            Path.home()
            / "Applications"
            / "Wispr Flow.app"
            / "Contents"
            / "Resources"
            / "app.asar",
            Path("/opt/Wispr Flow/resources/app.asar"),
            Path("/usr/lib/wispr-flow/resources/app.asar"),
        ]
    )
    existing = {path for path in candidates if path.is_file()}
    return sorted(existing, key=lambda path: path.stat().st_mtime, reverse=True)


def _find_key_in_archive(path: Path, project_ref: str) -> str | None:
    legacy: set[str] = set()
    publishable: set[str] = set()
    try:
        with path.open("rb") as archive:
            previous = b""
            while chunk := archive.read(_SCAN_CHUNK_SIZE):
                block = previous + chunk
                for match in _LEGACY_ANON_KEY.finditer(block):
                    candidate = match.group().decode("ascii")
                    if _legacy_key_matches(candidate, project_ref):
                        legacy.add(candidate)
                for match in _PUBLISHABLE_KEY.finditer(block):
                    publishable.add(match.group().decode("ascii"))
                previous = block[-_SCAN_OVERLAP:]
    except OSError:
        return None
    if len(legacy) == 1:
        return legacy.pop()
    if not legacy and len(publishable) == 1:
        return publishable.pop()
    return None


def _legacy_key_matches(key: str, project_ref: str) -> bool:
    try:
        encoded = key.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded))
    except (IndexError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("role") == "anon"
        and payload.get("ref") == project_ref
    )
