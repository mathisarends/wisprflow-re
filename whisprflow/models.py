from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any


class WritingStyle(IntEnum):
    UNSPECIFIED = 0
    FORMAL = 1
    CASUAL = 2
    VERY_CASUAL = 3
    EXCITED = 4
    GENZ = 5


class EditingStrength(IntEnum):
    UNSPECIFIED = 0
    VERBATIM = 1
    LIGHT = 2
    MEDIUM = 3
    HEAVY = 4


class Language(IntEnum):
    UNSPECIFIED = 0
    EN = 1
    EN_GB = 2
    ZH_CN = 3
    ZH = 4
    DE = 5
    ES = 6
    RU = 7
    KO = 8
    FR = 9
    JA = 10
    PT = 11
    TR = 12
    PL = 13
    CA = 14
    NL = 15
    AR = 16
    SV = 17
    IT = 18
    ID = 19
    HI = 20
    HI_EN = 21
    FI = 22
    VI = 23
    HE = 24
    UK = 25
    EL = 26
    MS = 27
    CS = 28
    RO = 29
    DA = 30
    HU = 31
    TA = 32
    NO = 33
    TH = 34
    UR = 35
    HR = 36
    BG = 37
    LT = 38
    LA = 39
    MI = 40
    ML = 41
    CY = 42
    SK = 43
    TE = 44
    FA = 45
    LV = 46
    BN = 47
    SR = 48
    AZ = 49
    SL = 50
    KN = 51
    ET = 52
    MK = 53
    BR = 54
    EU = 55
    IS = 56
    HY = 57
    NE = 58
    MN = 59
    BS = 60
    KK = 61
    SQ = 62
    SW = 63
    GL = 64
    MR = 65
    PA = 66
    SI = 67
    KM = 68
    SN = 69
    YO = 70
    SO = 71
    AF = 72
    OC = 73
    KA = 74
    BE = 75
    TG = 76
    SD = 77
    GU = 78
    AM = 79
    YI = 80
    LO = 81
    UZ = 82
    FO = 83
    HT = 84
    PS = 85
    TK = 86
    NN = 87
    MT = 88
    SA = 89
    LB = 90
    MY = 91
    BO = 92
    TL = 93
    MG = 94
    AS = 95
    TT = 96
    HAW = 97
    LN = 98
    HA = 99
    BA = 100
    JV = 101
    SU = 102
    YUE = 103
    DE_CH = 104
    EN_CA = 105
    UNDETERMINED = 106


class AppType(IntEnum):
    UNSPECIFIED = 0
    OTHER = 1
    BROWSER = 2
    PERSONAL_MESSAGING = 3
    WORK_MESSAGING = 4
    EMAIL = 5
    CHATBOT = 6
    DEVELOPER = 7


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
    app_type: AppType = AppType.OTHER
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
    languages: list[Language] = field(default_factory=lambda: [Language.EN])
    style: WritingStyle = WritingStyle.CASUAL
    cleanup: EditingStrength = EditingStrength.VERBATIM
    app_type: AppType = AppType.OTHER
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
