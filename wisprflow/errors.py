class WisprFlowError(Exception):
    """Base exception for the unofficial Wispr Flow client."""


class CredentialsError(WisprFlowError):
    """The desktop session is missing, malformed, or cannot be refreshed."""


class DesktopPreferencesError(WisprFlowError):
    """Desktop transcription preferences are missing or malformed."""


class RuntimeConfigurationError(WisprFlowError):
    """The selected backend route is incomplete."""


class ProtocolError(WisprFlowError):
    """A request or response does not match the reverse-engineered protocol."""


class AudioConversionError(WisprFlowError):
    """Audio could not be converted to Wispr's expected format."""


class AudioInputError(WisprFlowError):
    """Audio could not be captured from an input device."""


class OptionalDependencyError(WisprFlowError):
    """A requested adapter's optional dependency is not installed."""
