import pytest

from whisprflow import ProtocolError, TranscriptionOptions
from whisprflow.protocol import _message, _read_varint, _string, decode_responses


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
