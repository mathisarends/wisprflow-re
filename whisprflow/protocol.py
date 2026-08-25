import re
import uuid
from collections.abc import Iterable, Iterator

from whisprflow.errors import ProtocolError
from whisprflow.models import (
    AppType,
    Language,
    TranscriptionContext,
    TranscriptionOptions,
    TranscriptResult,
)


def encode_requests(
    *,
    user_id: str,
    audio: bytes,
    options: TranscriptionOptions,
    context: TranscriptionContext | None = None,
) -> Iterator[bytes]:
    session_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    yield _init_request(user_id, session_id, request_id, options) + _commit(False)
    if context is not None and not context.is_empty:
        yield _context_request(context) + _commit(False)
    yield _audio_request(audio) + _commit(True)


def decode_responses(
    responses: Iterable[bytes], options: TranscriptionOptions
) -> TranscriptResult:
    best: dict[str, str | int] = {}
    for response in responses:
        if not response or response[0] == 0x22:
            continue
        parsed = _parse_response(response)
        for key, value in parsed.items():
            if value not in (None, "", 0):
                best[key] = value

    raw = _clean_text(str(best.get("raw", "")))
    formatted = _clean_text(str(best.get("formatted", "")))
    plaintext = _clean_text(str(best.get("plaintext", "")))
    html = _clean_text(str(best.get("html", "")))
    final = html or plaintext or formatted or raw
    final, fired = _apply_mapping(final, options.replacements, "replacement")
    final, snippet_fired = _apply_mapping(final, options.snippets, "snippet")
    return TranscriptResult(
        final=final,
        raw=raw,
        formatted=formatted,
        plaintext=plaintext,
        html=html,
        status=int(best.get("status", 0)),
        post_processing=fired + snippet_fired,
    )


def _varint(value: int) -> bytes:
    if value < 0:
        raise ProtocolError("Negative protobuf varints are not supported.")
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _field(number: int, wire_type: int, data: bytes) -> bytes:
    return _varint((number << 3) | wire_type) + data


def _bytes(number: int, value: bytes) -> bytes:
    return _field(number, 2, _varint(len(value)) + value)


def _string(number: int, value: str) -> bytes:
    return _bytes(number, value.encode())


def _integer(number: int, value: int) -> bytes:
    return _field(number, 0, _varint(value))


def _message(number: int, value: bytes) -> bytes:
    return _bytes(number, value)


def _version(version: tuple[int, int, int]) -> bytes:
    return b"".join(_integer(index, value) for index, value in enumerate(version, 1))


def _metadata(
    user_id: str,
    session_id: str,
    request_id: str,
    version: tuple[int, int, int],
) -> bytes:
    client = _string(1, "Wispr Flow") + _integer(2, 2) + _message(3, _version(version))
    return (
        _string(1, user_id)
        + _string(2, session_id)
        + _string(3, request_id)
        + _integer(4, 1)
        + _integer(5, 1)
        + _message(6, client)
    )


def _preferences(options: TranscriptionOptions) -> bytes:
    user = b""
    if options.first_name:
        user += _string(1, options.first_name)
    if options.last_name:
        user += _string(2, options.last_name)
    if options.email:
        user += _string(3, options.email)
    data = _message(1, user)

    languages = list(options.languages)
    if Language.HI_EN in languages and Language.EN not in languages:
        languages.insert(0, Language.EN)
    packed = b"".join(_varint(code) for code in languages)
    if packed:
        data += _bytes(2, packed)

    vocabulary = b"".join(_string(1, word) for word in options.dictionary)
    vocabulary += b"".join(_string(3, word) for word in options.starred_dictionary)
    if vocabulary:
        data += _message(3, vocabulary)

    replacements = b"".join(
        _message(1, _string(1, key) + _string(2, value))
        for key, value in options.replacements.items()
    )
    replacements += b"".join(
        _message(3, _string(1, key) + _string(2, value))
        for key, value in options.snippets.items()
    )
    if replacements:
        data += _message(4, replacements)

    style_value = options.style
    style_field = {
        AppType.PERSONAL_MESSAGING: 2,
        AppType.WORK_MESSAGING: 3,
        AppType.EMAIL: 4,
    }.get(options.app_type, 1)
    general_style = _integer(style_field, style_value) if style_value else b""
    style = _message(1, general_style) if general_style else b""
    style += _message(3, _integer(1, 0))
    style += _message(4, _integer(2, 0) + _integer(3, 0))
    style += _integer(5, options.cleanup)
    return data + _message(5, style)


def _init_request(
    user_id: str,
    session_id: str,
    request_id: str,
    options: TranscriptionOptions,
) -> bytes:
    init = _message(
        1, _metadata(user_id, session_id, request_id, options.client_version)
    ) + _message(2, _preferences(options))
    return _message(1, init)


def _context_request(context: TranscriptionContext) -> bytes:
    body = b""
    app = b""
    if context.app_name:
        app += _string(1, context.app_name)
    if context.bundle_id:
        app += _string(2, context.bundle_id)
    if context.url:
        app += _string(3, context.url)
    app += _integer(4, context.app_type)
    if app:
        body += _message(1, app)

    textbox = b""
    for field, value in (
        (1, context.textbox_contents),
        (2, context.before_text),
        (3, context.selected_text),
        (4, context.after_text),
    ):
        if value:
            textbox += _string(field, value)
    if textbox:
        body += _message(2, textbox)

    dynamic = b""
    for field, values in (
        (1, context.screen_ax),
        (2, context.screen_ocr),
        (3, context.variable_names),
        (4, context.file_names),
    ):
        dynamic += b"".join(_string(field, value) for value in values[:50])
    if dynamic:
        body += _message(3, dynamic)
    if context.content_text:
        body += _string(5, context.content_text)
    if context.content_html:
        body += _string(6, context.content_html)
    if context.screenshot:
        body += _bytes(8, context.screenshot)
    return _message(2, body)


def _audio_request(audio: bytes) -> bytes:
    return _message(3, _message(2, _bytes(1, audio)))


def _commit(final: bool) -> bytes:
    return _integer(4, 1 if final else 2)


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while position < len(data):
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
        shift += 7
        if shift > 63:
            break
    raise ProtocolError("Malformed protobuf varint.")


def _fields(data: bytes) -> Iterator[tuple[int, int, bytes | int]]:
    position = 0
    while position < len(data):
        tag, position = _read_varint(data, position)
        number, wire_type = tag >> 3, tag & 7
        if wire_type == 0:
            value, position = _read_varint(data, position)
            yield number, wire_type, value
        elif wire_type == 2:
            length, position = _read_varint(data, position)
            end = position + length
            if end > len(data):
                raise ProtocolError("Truncated protobuf field.")
            yield number, wire_type, data[position:end]
            position = end
        elif wire_type == 5:
            position += 4
        elif wire_type == 1:
            position += 8
        else:
            raise ProtocolError(f"Unsupported protobuf wire type: {wire_type}.")


def _text_message(data: bytes) -> str:
    for number, wire_type, value in _fields(data):
        if number == 1 and wire_type == 2 and isinstance(value, bytes):
            return value.decode(errors="replace")
    return ""


def _parse_response(data: bytes) -> dict[str, str | int]:
    output: dict[str, str | int] = {}
    for number, wire_type, value in _fields(data):
        if wire_type != 2 or not isinstance(value, bytes):
            continue
        if number == 1:
            for result_number, result_type, result_value in _fields(value):
                if (
                    result_number == 1
                    and result_type == 2
                    and isinstance(result_value, bytes)
                ):
                    for text_number, text_type, text_value in _fields(result_value):
                        if text_type == 2 and isinstance(text_value, bytes):
                            if text_number == 1:
                                output["html"] = text_value.decode(errors="replace")
                            elif text_number == 2:
                                output["plaintext"] = text_value.decode(
                                    errors="replace"
                                )
                elif result_number == 5 and result_type == 0:
                    output["status"] = int(result_value)
        elif number == 2:
            for state_number, state_type, state_value in _fields(value):
                if state_type == 2 and isinstance(state_value, bytes):
                    if state_number == 2:
                        output["raw"] = _text_message(state_value)
                    elif state_number == 3:
                        output["formatted"] = _text_message(state_value)
    return output


def _clean_text(text: str) -> str:
    text = text.lstrip("\ufffd").strip()
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+.*$", "", text).strip()


def _apply_mapping(
    text: str, mapping: dict[str, str], kind: str
) -> tuple[str, list[dict[str, str]]]:
    fired: list[dict[str, str]] = []
    for source, target in sorted(mapping.items(), key=lambda item: -len(item[0])):
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(target, text)
            fired.append({"kind": kind, "from": source, "to": target})
    return text, fired
