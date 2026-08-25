import pytest

from wisprflow import (
    AppType,
    EditingStrength,
    Language,
    ProtocolError,
    TranscriptionContext,
    TranscriptionOptions,
    WritingStyle,
)
from wisprflow.protocol import (
    _bytes,
    _fields,
    _integer,
    _message,
    _preferences,
    _read_varint,
    _string,
    _varint,
    decode_responses,
    encode_requests,
)


def values(data: bytes, number: int) -> list[bytes | int]:
    """Every value carried by a field number, in wire order."""
    return [value for field, _, value in _fields(data) if field == number]


def value(data: bytes, *path: int) -> bytes | int:
    """The single value at a nested field path, e.g. ``value(packet, 1, 2)``."""
    for number in path:
        found = values(data, number)
        assert len(found) == 1, f"expected exactly one field {number}, got {found}"
        data = found[0]
    return data


def encoded(
    *,
    audio: bytes = b"RIFF wav",
    options: TranscriptionOptions | None = None,
    context: TranscriptionContext | None = None,
) -> list[bytes]:
    return list(
        encode_requests(
            user_id="user-1",
            audio=audio,
            options=options or TranscriptionOptions(),
            context=context,
        )
    )


def test_a_request_is_an_init_frame_followed_by_a_final_audio_frame():
    init, audio = encoded(audio=b"RIFF payload")

    assert value(init, 1, 1, 1) == b"user-1"
    assert value(init, 4) == 2, "the init frame must not close the stream"
    assert value(audio, 3, 2, 1) == b"RIFF payload"
    assert value(audio, 4) == 1, "the audio frame closes the stream"


def test_the_session_and_request_ids_are_distinct_per_request():
    init, _ = encoded()
    metadata = value(init, 1, 1)

    session_id = value(metadata, 2)
    request_id = value(metadata, 3)

    assert session_id != request_id
    assert len(session_id) == len(request_id) == 36
    assert value(encoded()[0], 1, 1, 2) != session_id


def test_the_client_version_travels_with_the_metadata():
    init, _ = encoded(options=TranscriptionOptions(client_version=(1, 7, 42)))

    client = value(init, 1, 1, 6)

    assert value(client, 1) == b"Wispr Flow"
    assert [value(value(client, 3), part) for part in (1, 2, 3)] == [1, 7, 42]


def test_a_populated_context_is_sent_as_its_own_frame():
    init, context, audio = encoded(
        context=TranscriptionContext(
            before_text="Dear Ada,",
            after_text="Kind regards",
            app_name="Mail",
            url="https://mail.example",
            app_type=AppType.EMAIL,
            screen_ocr=["Subject"],
            content_text="body",
            screenshot=b"png-bytes",
        )
    )
    body = value(context, 2)

    assert value(body, 1, 1) == b"Mail"
    assert value(body, 1, 3) == b"https://mail.example"
    assert value(body, 1, 4) == AppType.EMAIL
    assert value(body, 2, 2) == b"Dear Ada,"
    assert value(body, 2, 4) == b"Kind regards"
    assert value(body, 3, 2) == b"Subject"
    assert value(body, 5) == b"body"
    assert value(body, 8) == b"png-bytes"
    assert value(context, 4) == 2
    assert init and audio


def test_an_empty_context_is_not_sent():
    assert len(encoded(context=TranscriptionContext())) == 2
    assert len(encoded(context=TranscriptionContext(app_type=AppType.EMAIL))) == 2


def test_screen_capture_lists_are_truncated_to_what_the_desktop_sends():
    init, context, audio = encoded(
        context=TranscriptionContext(screen_ax=[f"line-{index}" for index in range(60)])
    )

    assert len(values(value(context, 2, 3), 1)) == 50
    assert init and audio


def test_hinglish_implies_english_for_the_backend():
    preferences = _preferences(TranscriptionOptions(languages=[Language.HI_EN]))

    assert value(preferences, 2) == bytes([Language.EN, Language.HI_EN])


def test_languages_are_packed_in_the_order_they_were_chosen():
    preferences = _preferences(
        TranscriptionOptions(languages=[Language.DE, Language.EN])
    )

    assert value(preferences, 2) == bytes([Language.DE, Language.EN])


@pytest.mark.parametrize(
    ("app_type", "style_field"),
    [
        (AppType.OTHER, 1),
        (AppType.PERSONAL_MESSAGING, 2),
        (AppType.WORK_MESSAGING, 3),
        (AppType.EMAIL, 4),
    ],
)
def test_the_writing_style_is_stored_per_app_profile(app_type, style_field):
    preferences = _preferences(
        TranscriptionOptions(
            app_type=app_type,
            style=WritingStyle.FORMAL,
            cleanup=EditingStrength.HEAVY,
        )
    )
    style = value(preferences, 5)

    assert value(style, 1, style_field) == WritingStyle.FORMAL
    assert value(style, 5) == EditingStrength.HEAVY


def test_an_unspecified_style_is_omitted_rather_than_sent_as_zero():
    style = value(_preferences(TranscriptionOptions(style=WritingStyle.UNSPECIFIED)), 5)

    assert values(style, 1) == []
    assert value(style, 5) == EditingStrength.VERBATIM


def test_the_personal_dictionary_separates_words_from_rewrites():
    preferences = _preferences(
        TranscriptionOptions(
            first_name="Ada",
            email="ada@example.test",
            dictionary=["OpenAI"],
            starred_dictionary=["Codex"],
            replacements={"dont": "don't"},
            snippets={"signature": "Kind regards"},
        )
    )

    assert value(preferences, 1, 1) == b"Ada"
    assert value(preferences, 1, 3) == b"ada@example.test"
    assert value(preferences, 3, 1) == b"OpenAI"
    assert value(preferences, 3, 3) == b"Codex"
    assert value(value(preferences, 4, 1), 1) == b"dont"
    assert value(value(preferences, 4, 1), 2) == b"don't"
    assert value(value(preferences, 4, 3), 1) == b"signature"


def test_an_empty_profile_sends_no_vocabulary_fields():
    preferences = _preferences(TranscriptionOptions())

    assert values(preferences, 3) == []
    assert values(preferences, 4) == []
    assert value(preferences, 1) == b""


def test_the_final_text_prefers_the_richest_representation():
    result = _message(1, _string(1, "<p>Rich</p>") + _string(2, "Plain"))
    state = _message(2, _string(1, "raw")) + _message(3, _string(1, "Formatted"))

    output = decode_responses(
        [b"", b"\x22heartbeat", _message(1, result) + _message(2, state)],
        TranscriptionOptions(),
    )

    assert output.final == "<p>Rich</p>"
    assert output.html == "<p>Rich</p>"
    assert output.plaintext == "Plain"
    assert output.raw == "raw"
    assert output.formatted == "Formatted"


def test_plaintext_wins_when_no_html_arrives():
    result = _message(1, _string(2, "Plain"))
    state = _message(3, _string(1, "Formatted"))

    output = decode_responses(
        [_message(1, result) + _message(2, state)], TranscriptionOptions()
    )

    assert output.final == "Plain"


def test_later_empty_frames_do_not_erase_a_transcript():
    filled = _message(1, _message(1, _string(2, "Plain"))) + _message(1, _integer(5, 3))
    empty = _message(1, _message(1, _string(2, "")))

    output = decode_responses([filled, empty], TranscriptionOptions())

    assert output.plaintext == "Plain"
    assert output.status == 3


def test_partial_utf8_and_trailing_control_bytes_are_trimmed():
    text = "�  Hello world \x00garbage"
    response = _message(1, _message(1, _string(2, text)))

    output = decode_responses([response], TranscriptionOptions())

    assert output.final == "Hello world"


def test_replacements_and_snippets_are_applied_and_reported():
    response = _message(1, _message(1, _string(2, "Dont ship without a signature")))
    options = TranscriptionOptions(
        replacements={"dont": "don't", "ship": "deploy"},
        snippets={"signature": "Kind regards, Ada"},
    )

    output = decode_responses([response], options)

    assert output.final == "don't deploy without a Kind regards, Ada"
    assert output.plaintext == "Dont ship without a signature"
    assert output.post_processing == [
        {"kind": "replacement", "from": "dont", "to": "don't"},
        {"kind": "replacement", "from": "ship", "to": "deploy"},
        {"kind": "snippet", "from": "signature", "to": "Kind regards, Ada"},
    ]


def test_replacements_respect_word_boundaries():
    response = _message(1, _message(1, _string(2, "shipping the ship")))

    output = decode_responses(
        [response], TranscriptionOptions(replacements={"ship": "deploy"})
    )

    assert output.final == "shipping the deploy"


def test_the_longest_replacement_is_applied_first():
    response = _message(1, _message(1, _string(2, "new york city")))
    options = TranscriptionOptions(
        replacements={"new york": "NYC", "new york city": "NYC Metro"}
    )

    output = decode_responses([response], options)

    assert output.final == "NYC Metro"
    assert [entry["from"] for entry in output.post_processing] == ["new york city"]


def test_negative_varints_are_not_representable():
    with pytest.raises(ProtocolError, match="Negative"):
        _varint(-1)


def test_a_truncated_varint_is_rejected():
    with pytest.raises(ProtocolError, match="varint"):
        _read_varint(b"\x80", 0)


def test_an_overlong_varint_is_rejected():
    with pytest.raises(ProtocolError, match="varint"):
        _read_varint(b"\x80" * 12, 0)


def test_a_truncated_length_delimited_field_is_rejected():
    with pytest.raises(ProtocolError, match="Truncated"):
        list(_fields(_bytes(1, b"payload")[:-3]))


def test_an_unsupported_wire_type_is_rejected():
    with pytest.raises(ProtocolError, match="wire type"):
        list(_fields(b"\x0b"))
