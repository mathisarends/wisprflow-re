import pytest

from whisprflow import (
    AppType,
    EditingStrength,
    Language,
    ProtocolError,
    TranscriptionContext,
    TranscriptionOptions,
    WritingStyle,
)
from whisprflow.protocol import (
    _fields,
    _message,
    _preferences,
    _read_varint,
    _string,
    decode_responses,
)


def test_varint_rejects_truncated_input():
    with pytest.raises(ProtocolError):
        _read_varint(b"\x80", 0)


def test_response_selection_prefers_plaintext_over_formatted():
    result = _message(1, _string(2, "Plain"))
    state = _message(3, _string(1, "Formatted"))
    response = _message(1, result) + _message(2, state)

    output = decode_responses([b"\x22heartbeat", response], TranscriptionOptions())

    assert output.final == "Plain"
    assert output.plaintext == "Plain"
    assert output.formatted == "Formatted"


def test_options_use_wire_enums():
    options = TranscriptionOptions(
        languages=[Language.EN, Language.HI],
        style=WritingStyle.FORMAL,
        cleanup=EditingStrength.LIGHT,
        app_type=AppType.EMAIL,
    )
    context = TranscriptionContext(app_type=AppType.DEVELOPER)

    assert options.languages == [Language.EN, Language.HI]
    assert options.style is WritingStyle.FORMAL
    assert options.cleanup is EditingStrength.LIGHT
    assert options.app_type is AppType.EMAIL
    assert context.app_type is AppType.DEVELOPER


def test_wire_enums_match_desktop_protocol():
    assert [language.value for language in Language] == list(range(107))
    assert Language.DE == 5
    assert Language.DE_CH == 104
    assert Language.UNDETERMINED == 106
    assert EditingStrength.VERBATIM == 1
    assert EditingStrength.HEAVY == 4


def test_german_language_uses_desktop_wire_value():
    preferences = _preferences(TranscriptionOptions(languages=[Language.DE]))

    language_fields = [
        value
        for number, wire_type, value in _fields(preferences)
        if number == 2 and wire_type == 2
    ]
    assert language_fields == [b"\x05"]
