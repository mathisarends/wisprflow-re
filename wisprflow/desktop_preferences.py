import json
import os
import sqlite3
import sys
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wisprflow.errors import DesktopPreferencesError
from wisprflow.models import (
    AppType,
    EditingStrength,
    Language,
    TranscriptionOptions,
    WritingStyle,
)

_PERSONAL_DICTIONARY_ID = "00000000-0000-0000-0000-000000000000"


def _default_desktop_data_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Wispr Flow"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Wispr Flow"
    config_home = os.environ.get("XDG_CONFIG_HOME")
    return (
        Path(config_home) / "Wispr Flow"
        if config_home
        else Path.home() / ".config" / "Wispr Flow"
    )


@dataclass(slots=True)
class _DesktopDictionary:
    words: list[str] = field(default_factory=list)
    starred_words: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)
    snippets: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _DictionaryEntry:
    phrase: str
    replacement: str | None
    is_snippet: bool
    is_starred: bool


class DesktopPreferencesStore:
    """Read transcription preferences from the official desktop client."""

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        database_path: Path | None = None,
        sqlite_timeout: float = 1.0,
    ) -> None:
        desktop_data = _default_desktop_data_path()
        self.config_path = (
            config_path if config_path is not None else desktop_data / "config.json"
        )
        self.database_path = (
            database_path if database_path is not None else desktop_data / "flow.sqlite"
        )
        self.sqlite_timeout = sqlite_timeout

    def load(self, app_type: AppType = AppType.OTHER) -> TranscriptionOptions:
        """Return a fresh snapshot of the desktop transcription preferences."""
        config = self._read_config()
        user = _required_mapping(config, "prefs", "user")
        dictionary = self._read_dictionary()

        return TranscriptionOptions(
            languages=_languages(user),
            style=_style(user, app_type),
            cleanup=_cleanup(user, app_type),
            app_type=app_type,
            first_name=_optional_string(user, "firstName"),
            last_name=_optional_string(user, "lastName"),
            email=_optional_string(user, "email"),
            dictionary=dictionary.words,
            starred_dictionary=dictionary.starred_words,
            replacements=dictionary.replacements,
            snippets=dictionary.snippets,
            client_version=_client_version(config),
        )

    def _read_config(self) -> dict[str, Any]:
        try:
            raw = self.config_path.read_text(encoding="utf-8")
            config = json.loads(raw)
        except FileNotFoundError:
            raise DesktopPreferencesError(
                f"Wispr Flow preferences not found at {self.config_path}."
            ) from None
        except (OSError, json.JSONDecodeError) as exc:
            raise DesktopPreferencesError(
                f"Cannot read Wispr Flow preferences at {self.config_path}: {exc}"
            ) from None
        if not isinstance(config, dict):
            raise DesktopPreferencesError(
                f"Unexpected preferences format in {self.config_path}."
            )
        return config

    def _read_dictionary(self) -> _DesktopDictionary:
        uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
        try:
            connection = sqlite3.connect(
                uri,
                uri=True,
                timeout=self.sqlite_timeout,
            )
            with closing(connection):
                connection.execute("PRAGMA query_only = ON")
                rows = connection.execute(
                    """
                    SELECT phrase, replacement, isSnippet, isStarred
                    FROM Dictionary
                    WHERE isDeleted = 0
                    ORDER BY
                        CASE WHEN teamDictionaryId = ? THEN 1 ELSE 0 END,
                        modifiedAt,
                        id
                    """,
                    (_PERSONAL_DICTIONARY_ID,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise DesktopPreferencesError(
                f"Cannot read Wispr Flow dictionary at {self.database_path}: {exc}"
            ) from None

        entries: dict[str, _DictionaryEntry] = {}
        for phrase, replacement, is_snippet, is_starred in rows:
            if not isinstance(phrase, str) or not phrase:
                raise DesktopPreferencesError(
                    f"Unexpected dictionary entry in {self.database_path}."
                )
            normalized_replacement = (
                replacement if isinstance(replacement, str) and replacement else None
            )
            entries[phrase] = _DictionaryEntry(
                phrase=phrase,
                replacement=normalized_replacement,
                is_snippet=bool(is_snippet),
                is_starred=bool(is_starred),
            )

        result = _DesktopDictionary()
        for entry in entries.values():
            if entry.is_snippet:
                if entry.replacement is not None:
                    result.snippets[entry.phrase] = entry.replacement
            elif entry.replacement is not None:
                result.replacements[entry.phrase] = entry.replacement
            elif entry.is_starred:
                result.starred_words.append(entry.phrase)
            else:
                result.words.append(entry.phrase)
        return result


def _required_mapping(root: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    value: Any = root
    for key in path:
        if not isinstance(value, Mapping):
            break
        value = value.get(key)
    if not isinstance(value, Mapping):
        location = ".".join(path)
        raise DesktopPreferencesError(
            f"Wispr Flow preferences contain no '{location}' object."
        )
    return value


def _optional_mapping(root: Mapping[str, Any], *path: str) -> Mapping[str, Any] | None:
    value: Any = root
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value if isinstance(value, Mapping) else None


def _optional_string(values: Mapping[str, Any], key: str) -> str:
    value = values.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DesktopPreferencesError(
            f"Wispr Flow preference '{key}' must be a string."
        )
    return value


def _languages(user: Mapping[str, Any]) -> list[Language]:
    raw_languages = user.get("effectiveLanguages") or user.get("selectedLanguages")
    if isinstance(raw_languages, str):
        codes = [raw_languages]
    elif isinstance(raw_languages, list) and all(
        isinstance(code, str) for code in raw_languages
    ):
        codes = raw_languages
    elif raw_languages is None:
        return [Language.EN]
    else:
        raise DesktopPreferencesError(
            "Wispr Flow languages must be a string or a list of strings."
        )

    languages: list[Language] = []
    for code in codes:
        language = _language(code)
        if language not in languages:
            languages.append(language)
    return languages or [Language.EN]


def _language(code: str) -> Language:
    normalized = code.strip().upper().replace("-", "_")
    aliases = {
        "AUTO": "UNDETERMINED",
        "DECH": "DE_CH",
        "ENCA": "EN_CA",
        "ENGB": "EN_GB",
        "HIEN": "HI_EN",
        "JP": "JA",
        "ZHCN": "ZH_CN",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return Language[normalized]
    except KeyError:
        raise DesktopPreferencesError(
            f"Unsupported Wispr Flow language code: {code!r}."
        ) from None


def _profile_name(app_type: AppType) -> str:
    return {
        AppType.PERSONAL_MESSAGING: "personal",
        AppType.WORK_MESSAGING: "work",
        AppType.EMAIL: "email",
    }.get(app_type, "other")


def _profile_value(user: Mapping[str, Any], app_type: AppType, key: str) -> Any:
    voices = _optional_mapping(user, "userVoices")
    if voices is None:
        return None
    profile = voices.get(_profile_name(app_type))
    return profile.get(key) if isinstance(profile, Mapping) else None


def _style(user: Mapping[str, Any], app_type: AppType) -> WritingStyle:
    raw_style = _profile_value(user, app_type, "stylePreference")
    if raw_style is None:
        styles = _optional_mapping(user, "personalizationStyles")
        if styles is not None:
            raw_style = styles.get(_profile_name(app_type))
    if raw_style in (None, "", "default"):
        return WritingStyle.CASUAL
    if not isinstance(raw_style, str):
        raise DesktopPreferencesError("Wispr Flow writing style must be a string.")
    normalized = raw_style.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return WritingStyle[normalized]
    except KeyError:
        raise DesktopPreferencesError(
            f"Unsupported Wispr Flow writing style: {raw_style!r}."
        ) from None


def _cleanup(user: Mapping[str, Any], app_type: AppType) -> EditingStrength:
    raw_cleanup = _profile_value(user, app_type, "autoCleanupLevel")
    if raw_cleanup is None:
        cleanup = _optional_mapping(user, "autoCleanup")
        raw_cleanup = cleanup.get("level") if cleanup is not None else None
    if raw_cleanup in (None, ""):
        return EditingStrength.VERBATIM
    if not isinstance(raw_cleanup, str):
        raise DesktopPreferencesError("Wispr Flow cleanup level must be a string.")
    normalized = raw_cleanup.strip().upper().replace("-", "_").replace(" ", "_")
    normalized = {
        "HIGH": "HEAVY",
        "NONE": "VERBATIM",
        "OFF": "VERBATIM",
    }.get(normalized, normalized)
    try:
        return EditingStrength[normalized]
    except KeyError:
        raise DesktopPreferencesError(
            f"Unsupported Wispr Flow cleanup level: {raw_cleanup!r}."
        ) from None


def _client_version(config: Mapping[str, Any]) -> tuple[int, int, int]:
    prefs = _required_mapping(config, "prefs")
    raw_version = prefs.get("version")
    if raw_version is None:
        return TranscriptionOptions().client_version
    if not isinstance(raw_version, str):
        raise DesktopPreferencesError("Wispr Flow version must be a string.")
    try:
        parts = raw_version.split("-", 1)[0].split(".")
        major, minor, patch = (int(part) for part in parts[:3])
    except (ValueError, TypeError):
        raise DesktopPreferencesError(
            f"Unsupported Wispr Flow version: {raw_version!r}."
        ) from None
    return major, minor, patch
