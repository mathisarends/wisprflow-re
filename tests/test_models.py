from pathlib import Path

import pytest

from whisprflow import (
    AppType,
    AuthStatus,
    Credentials,
    EditingStrength,
    Language,
    RuntimeRoute,
    TranscriptionContext,
    TranscriptResult,
    WritingStyle,
)


def test_wire_enums_match_the_desktop_protocol():
    assert [language.value for language in Language] == list(range(107))
    assert Language.DE == 5
    assert Language.DE_CH == 104
    assert Language.UNDETERMINED == 106
    assert EditingStrength.VERBATIM == 1
    assert EditingStrength.HEAVY == 4
    assert WritingStyle.CASUAL == 2


def _credentials(expires_at: float | None) -> Credentials:
    return Credentials(
        access_token="token",
        refresh_token="refresh",
        user_id="user-1",
        expires_at=expires_at,
        session_path=Path("session.json"),
    )


@pytest.mark.parametrize(
    ("expires_at", "fresh"),
    [(None, True), (2000, True), (1100, False), (900, False)],
)
def test_credentials_expire_a_skew_window_early(expires_at, fresh):
    assert _credentials(expires_at).is_fresh(now=1000, skew_seconds=120) is fresh


def test_only_an_expired_status_is_not_ok():
    assert AuthStatus("valid", None, None, True).ok is True
    assert AuthStatus("near_expiry", None, None, True).ok is True
    assert AuthStatus("expired", None, None, True).ok is False


def test_the_edge_route_needs_no_private_backend_credentials():
    metadata = dict(RuntimeRoute().metadata("token"))

    assert metadata["authorization"] == "Bearer token"
    assert metadata["content-type"] == "application/grpc"
    assert "baseten-authorization" not in metadata
    assert "baseten-model-id" not in metadata
    assert "x-baseten-environment" not in metadata


def test_a_direct_route_formats_the_backend_headers():
    route = RuntimeRoute(
        host="model.example",
        model_id="abc",
        environment="production",
        backend_key="placeholder",
    )

    metadata = dict(route.metadata("token"))

    assert metadata["baseten-authorization"] == "Api-Key placeholder"
    assert metadata["baseten-model-id"] == "model-abc"
    assert metadata["x-baseten-environment"] == "production"


def test_already_formatted_backend_values_are_left_alone():
    route = RuntimeRoute(backend_key="api-key placeholder", model_id="model-abc")

    metadata = dict(route.metadata("token"))

    assert metadata["baseten-authorization"] == "api-key placeholder"
    assert metadata["baseten-model-id"] == "model-abc"


def test_a_context_without_content_is_empty():
    assert TranscriptionContext().is_empty is True
    assert TranscriptionContext(app_type=AppType.EMAIL).is_empty is True


@pytest.mark.parametrize(
    "context",
    [
        TranscriptionContext(before_text="Hi"),
        TranscriptionContext(app_name="Mail"),
        TranscriptionContext(screen_ocr=["Subject"]),
        TranscriptionContext(screenshot=b"png"),
    ],
)
def test_any_captured_content_makes_a_context_worth_sending(context):
    assert context.is_empty is False


def test_a_result_reads_as_its_final_text():
    assert str(TranscriptResult(final="Hello world", raw="hello world")) == (
        "Hello world"
    )
