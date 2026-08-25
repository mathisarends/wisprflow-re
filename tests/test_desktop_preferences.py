import json
import sqlite3

import pytest

from whisprflow import (
    AppType,
    DesktopPreferencesError,
    DesktopPreferencesStore,
    EditingStrength,
    Language,
    WritingStyle,
)

_PERSONAL_DICTIONARY_ID = "00000000-0000-0000-0000-000000000000"


def _write_config(path, *, effective_languages="de"):
    path.write_text(
        json.dumps(
            {
                "prefs": {
                    "version": "1.7.42-beta.1",
                    "user": {
                        "firstName": "Ada",
                        "lastName": "Lovelace",
                        "email": "ada@example.test",
                        "effectiveLanguages": effective_languages,
                        "selectedLanguages": ["en", "de"],
                        "autoCleanup": {"level": "medium"},
                        "personalizationStyles": {"other": "casual"},
                        "userVoices": {
                            "email": {
                                "stylePreference": "formal",
                                "autoCleanupLevel": "light",
                            }
                        },
                    },
                },
                "futureField": {"preserved": True},
            }
        ),
        encoding="utf-8",
    )


def _write_database(path):
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
        connection.executemany(
            "INSERT INTO Dictionary VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("1", "OpenAI", None, _PERSONAL_DICTIONARY_ID, "1", 0, 0, 0),
                ("2", "Codex", None, _PERSONAL_DICTIONARY_ID, "2", 0, 0, 1),
                (
                    "3",
                    "dont",
                    "don't",
                    _PERSONAL_DICTIONARY_ID,
                    "3",
                    0,
                    0,
                    0,
                ),
                (
                    "4",
                    "signature",
                    "Kind regards",
                    _PERSONAL_DICTIONARY_ID,
                    "4",
                    0,
                    1,
                    0,
                ),
                ("5", "deleted", None, _PERSONAL_DICTIONARY_ID, "5", 1, 0, 0),
                ("6", "shared", "team", "team-1", "6", 0, 0, 0),
                (
                    "7",
                    "shared",
                    "personal",
                    _PERSONAL_DICTIONARY_ID,
                    "7",
                    0,
                    0,
                    0,
                ),
            ],
        )


def test_loads_desktop_transcription_preferences(tmp_path):
    config_path = tmp_path / "config.json"
    database_path = tmp_path / "flow.sqlite"
    _write_config(config_path)
    _write_database(database_path)

    options = DesktopPreferencesStore(
        config_path=config_path,
        database_path=database_path,
    ).load(AppType.EMAIL)

    assert options.languages == [Language.DE]
    assert options.style is WritingStyle.FORMAL
    assert options.cleanup is EditingStrength.LIGHT
    assert options.app_type is AppType.EMAIL
    assert options.first_name == "Ada"
    assert options.last_name == "Lovelace"
    assert options.email == "ada@example.test"
    assert options.dictionary == ["OpenAI"]
    assert options.starred_dictionary == ["Codex"]
    assert options.replacements == {"dont": "don't", "shared": "personal"}
    assert options.snippets == {"signature": "Kind regards"}
    assert options.client_version == (1, 7, 42)


def test_falls_back_to_selected_languages_and_global_preferences(tmp_path):
    config_path = tmp_path / "config.json"
    database_path = tmp_path / "flow.sqlite"
    _write_config(config_path, effective_languages=[])
    _write_database(database_path)

    options = DesktopPreferencesStore(
        config_path=config_path,
        database_path=database_path,
    ).load()

    assert options.languages == [Language.EN, Language.DE]
    assert options.style is WritingStyle.CASUAL
    assert options.cleanup is EditingStrength.MEDIUM


def test_rejects_unknown_desktop_language(tmp_path):
    config_path = tmp_path / "config.json"
    database_path = tmp_path / "flow.sqlite"
    _write_config(config_path, effective_languages="klingon")
    _write_database(database_path)

    store = DesktopPreferencesStore(
        config_path=config_path,
        database_path=database_path,
    )

    with pytest.raises(DesktopPreferencesError, match="klingon"):
        store.load()


def test_missing_dictionary_database_has_actionable_error(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    store = DesktopPreferencesStore(
        config_path=config_path,
        database_path=tmp_path / "missing.sqlite",
    )

    with pytest.raises(DesktopPreferencesError, match="dictionary"):
        store.load()
