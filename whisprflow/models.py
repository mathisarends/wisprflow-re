from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Credentials:
    access_token: str
    refresh_token: str | None
    user_id: str
    expires_at: float | None
    session_path: Path

    def is_fresh(self, *, now: float, skew_seconds: float = 120.0) -> bool:
        return self.expires_at is None or now < self.expires_at - skew_seconds


@dataclass(frozen=True, slots=True)
class AuthStatus:
    status: str
    expires_at: float | None
    seconds_remaining: float | None
    refresh_available: bool

    @property
    def ok(self) -> bool:
        return self.status != "expired"


@dataclass(frozen=True, slots=True)
class RuntimeRoute:
    host: str = "inference.wisprflow.com"
    port: int = 443
    method: str = "/flow_api.v1.TranscriptionService/TranscribeStream"
    model_id: str | None = None
    environment: str | None = None
    backend_key: str | None = None

    def metadata(self, access_token: str) -> tuple[tuple[str, str], ...]:
        metadata: list[tuple[str, str]] = [
            ("authorization", f"Bearer {access_token}"),
            ("flow-debug", "false"),
            ("disable-formatting", "false"),
            ("content-type", "application/grpc"),
            ("te", "trailers"),
        ]
        if self.backend_key:
            key = self.backend_key
            if not key.lower().startswith("api-key "):
                key = f"Api-Key {key}"
            metadata.append(("baseten-authorization", key))
        if self.model_id:
            model = self.model_id
            if not model.startswith("model-"):
                model = f"model-{model}"
            metadata.append(("baseten-model-id", model))
        if self.environment:
            metadata.append(("x-baseten-environment", self.environment))
        return tuple(metadata)


@dataclass(slots=True)
class TranscriptionContext:
    before_text: str = ""
    after_text: str = ""
    selected_text: str = ""
    textbox_contents: str = ""
    content_text: str = ""
    content_html: str = ""
    app_name: str = ""
    bundle_id: str = ""
    url: str = ""
    app_type: str = "other"
    screen_ax: list[str] = field(default_factory=list)
    screen_ocr: list[str] = field(default_factory=list)
    variable_names: list[str] = field(default_factory=list)
    file_names: list[str] = field(default_factory=list)
    screenshot: bytes | None = None

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.before_text,
                self.after_text,
                self.selected_text,
                self.textbox_contents,
                self.content_text,
                self.content_html,
                self.app_name,
                self.bundle_id,
                self.url,
                self.screen_ax,
                self.screen_ocr,
                self.variable_names,
                self.file_names,
                self.screenshot,
            )
        )


@dataclass(slots=True)
class TranscriptionOptions:
    languages: list[str] = field(default_factory=lambda: ["en"])
    style: str = "CASUAL"
    cleanup: str = "NONE"
    app_type: str = "other"
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    dictionary: list[str] = field(default_factory=list)
    starred_dictionary: list[str] = field(default_factory=list)
    replacements: dict[str, str] = field(default_factory=dict)
    snippets: dict[str, str] = field(default_factory=dict)
    client_version: tuple[int, int, int] = (1, 6, 606)


@dataclass(slots=True)
class TranscriptResult:
    final: str = ""
    raw: str = ""
    formatted: str = ""
    plaintext: str = ""
    html: str = ""
    status: int = 0
    post_processing: list[dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        return self.final
