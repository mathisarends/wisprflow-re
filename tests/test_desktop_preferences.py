import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from wisprflow import (
    AppType,
    DesktopPreferencesError,
    DesktopPreferencesStore,
    EditingStrength,
    Language,
    TranscriptionOptions,
    WritingStyle,
)

_PERSONAL_DICTIONARY_ID = "00000000-0000-0000-0000-000000000000"

_USER: dict[str, Any] = {
    "firstName": "Ada",
    "lastName": "Lovelace",
    "email": "ada@example.test",
    "effectiveLanguages": "de",
    "selectedLanguages": ["en", "de"],
    "autoCleanup": {"level": "medium"},
    "personalizationStyles": {"other": "casual"},
    "userVoices": {"email": {"stylePreference": "formal", "autoCleanupLevel": "light"}},
}


@pytest.fixture
def desktop(tmp_path: Path):
    """Build a store over a synthetic copy of the desktop's config and database."""

    def build(*, version: Any = "1.7.42-beta.1", **user_overrides: Any):
        user = {**_USER, **user_overrides}
        prefs: dict[str, Any] = {"user": user}
        if version is not None:
            prefs["version"] = version
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"prefs": prefs, "futureField": {"preserved": True}}),
            encoding="utf-8",
        )
        return DesktopPreferencesStore(
            config_path=config_path,
            database_path=_write_database(tmp_path / "flow.sqlite"),
        )

    return build


def _write_database(path: Path) -> Path:
    if path.exists():
        return path
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE Dictionary (
                id TEXT PRIMARY KEY,
                phrase TEXT NOT NULL,
                replacement TEXT,
                teamDictionaryId TEXT NOT NULL,
                modifiedAt TEXT NOT NULL,
                isDeleted INTEGER NOT NULL,
                isSnippet INTEGER NOT NULL,
                isStarred INTEGER NOT NULL
            )
            """
        )
        personal = _PERSONAL_DICTIONARY_ID
        connection.executemany(
            "INSERT INTO Dictionary VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("1", "OpenAI", None, personal, "1", 0, 0, 0),
                ("2", "Codex", None, personal, "2", 0, 0, 1),
                ("3", "dont", "don't", personal, "3", 0, 0, 0),
                ("4", "signature", "Kind regards", personal, "4", 0, 1, 0),
                ("5", "deleted", None, personal, "5", 1, 0, 0),
                ("6", "shared", "team", "team-1", "6", 0, 0, 0),
                ("7", "shared", "personal", personal, "7", 0, 0, 0),
                ("8", "empty snippet", None, personal, "8", 0, 1, 0),
            ],
        )
    return path


def test_the_profile_of_the_active_app_wins_over_the_global_defaults(desktop):
    options = desktop().load(AppType.EMAIL)

    assert options.style is WritingStyle.FORMAL
    assert options.cleanup is EditingStrength.LIGHT
    assert options.app_type is AppType.EMAIL
    assert options.first_name == "Ada"
    assert options.last_name == "Lovelace"
    assert options.email == "ada@example.test"
    assert options.languages == [Language.DE]
    assert options.client_version == (1, 7, 42)


def test_global_preferences_apply_to_apps_without_a_profile(desktop):
    options = desktop(effectiveLanguages=[]).load()

    assert options.languages == [Language.EN, Language.DE]
    assert options.style is WritingStyle.CASUAL
    assert options.cleanup is EditingStrength.MEDIUM


def test_the_personal_dictionary_is_split_by_how_each_entry_is_used(desktop):
    options = desktop().load()

    assert options.dictionary == ["OpenAI"]
    assert options.starred_dictionary == ["Codex"]
    assert options.replacements == {"dont": "don't", "shared": "personal"}
    assert options.snippets == {"signature": "Kind regards"}


def test_duplicate_languages_are_collapsed_and_aliases_are_translated(desktop):
    options = desktop(effectiveLanguages=["en-GB", "auto", "zhcn", "EN_GB"]).load()

    assert options.languages == [
        Language.EN_GB,
        Language.UNDETERMINED,
        Language.ZH_CN,
    ]


def test_a_desktop_without_a_language_choice_falls_back_to_english(desktop):
    options = desktop(effectiveLanguages=None, selectedLanguages=None).load()

    assert options.languages == [Language.EN]


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("high", EditingStrength.HEAVY),
        ("none", EditingStrength.VERBATIM),
        ("off", EditingStrength.VERBATIM),
        ("Heavy", EditingStrength.HEAVY),
        ("", EditingStrength.VERBATIM),
    ],
)
def test_desktop_cleanup_levels_map_onto_the_wire_enum(desktop, level, expected):
    options = desktop(autoCleanup={"level": level}).load()

    assert options.cleanup is expected


@pytest.mark.parametrize("style", ["default", "", None])
def test_an_unset_writing_style_falls_back_to_casual(desktop, style):
    options = desktop(personalizationStyles={"other": style}).load()

    assert options.style is WritingStyle.CASUAL


def test_a_very_casual_style_survives_desktop_spelling(desktop):
    options = desktop(personalizationStyles={"other": "very casual"}).load()

    assert options.style is WritingStyle.VERY_CASUAL


def test_a_desktop_without_a_version_uses_the_built_in_client_version(desktop):
    options = desktop(version=None).load()

    assert options.client_version == TranscriptionOptions().client_version


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"effectiveLanguages": "klingon"}, "klingon"),
        ({"effectiveLanguages": 42}, "must be a string or a list"),
        ({"personalizationStyles": {"other": "shakespearean"}}, "shakespearean"),
        ({"personalizationStyles": {"other": 42}}, "style must be a string"),
        ({"autoCleanup": {"level": "aggressive"}}, "aggressive"),
        ({"autoCleanup": {"level": 42}}, "cleanup level must be a string"),
        ({"firstName": 42}, "'firstName' must be a string"),
        ({"version": "not.a.version"}, "not.a.version"),
        ({"version": 42}, "version must be a string"),
    ],
)
def test_unreadable_preferences_name_the_offending_setting(desktop, overrides, message):
    store = desktop(**overrides)

    with pytest.raises(DesktopPreferencesError, match=message):
        store.load()


def test_a_missing_config_points_at_the_desktop_installation(tmp_path):
    store = DesktopPreferencesStore(
        config_path=tmp_path / "missing.json",
        database_path=_write_database(tmp_path / "flow.sqlite"),
    )

    with pytest.raises(DesktopPreferencesError, match="preferences not found"):
        store.load()


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("{not json", "Cannot read"),
        ('["list"]', "Unexpected preferences format"),
        ('{"prefs": []}', "no 'prefs.user' object"),
        ("{}", "no 'prefs.user' object"),
    ],
)
def test_a_malformed_config_explains_what_is_wrong(tmp_path, document, message):
    config_path = tmp_path / "config.json"
    config_path.write_text(document, encoding="utf-8")
    store = DesktopPreferencesStore(
        config_path=config_path,
        database_path=_write_database(tmp_path / "flow.sqlite"),
    )

    with pytest.raises(DesktopPreferencesError, match=message):
        store.load()


def test_a_missing_dictionary_database_is_reported_with_its_path(tmp_path, desktop):
    store = desktop()
    store.database_path = tmp_path / "missing.sqlite"

    with pytest.raises(DesktopPreferencesError, match="dictionary"):
        store.load()


def test_an_unusable_dictionary_row_is_not_silently_dropped(tmp_path, desktop):
    store = desktop()
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "INSERT INTO Dictionary VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("9", "", None, _PERSONAL_DICTIONARY_ID, "9", 0, 0, 0),
        )

    with pytest.raises(DesktopPreferencesError, match="Unexpected dictionary entry"):
        store.load()
