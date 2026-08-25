# wisprflow-re

An unofficial Python client for transcribing audio with an existing Wispr Flow
desktop session. It works without modifying the desktop app and exposes a small,
typed API for files, WAV data, and microphone input.

> [!IMPORTANT]
> This project is not affiliated with or endorsed by Wispr Flow. It uses your own
> authenticated desktop session and does not bypass subscriptions, quotas, or
> feature entitlements.

## Requirements

- Python 3.12–3.14
- [uv](https://docs.astral.sh/uv/)
- A signed-in Wispr Flow desktop installation
- [FFmpeg](https://ffmpeg.org/) on `PATH` when transcribing audio files

## Installation

Clone the repository and install its dependencies:

```console
uv sync
```

For microphone support, install the optional dependency as well:

```console
uv sync --extra microphone
```

## Quick start

```python
from wisprflow import WisprClient

client = WisprClient.from_desktop()
result = client.transcribe("recording.mp3")

print(result.final)
```

`from_desktop()` finds the desktop session in its standard location. Audio files
are converted to the required format through FFmpeg before transcription.

You can also run the included command-line example:

```console
uv run python -m examples.try_desktop recording.wav
```

Run it with `--help` to see options for language, writing style, context, token
refresh overrides, and direct routing.

## Audio inputs

`transcribe()` accepts a file path, normalized WAV bytes, or an `AudioInput`
adapter:

```python
from pathlib import Path

client.transcribe("recording.mp3")
client.transcribe(Path("recording.wav"))
client.transcribe(wav_bytes)
```

Byte payloads and custom input adapters must provide 16 kHz mono PCM16 WAV
audio.

### Microphone

List available recording devices:

```console
uv run --extra microphone python -m examples.try_microphone --list-devices
```

Start recording, speak, and press Enter to stop and transcribe:

```console
uv run --extra microphone python -m examples.try_microphone
```

Programmatic usage:

```python
from wisprflow import SoundDeviceMicrophone, WisprClient

client = WisprClient.from_desktop()
result = client.transcribe(SoundDeviceMicrophone())
print(result.final)
```

Pass `device=<index or name>` to select a specific input device.

## Transcription options and context

Use `TranscriptionOptions` to control language and formatting. Context helps the
service adapt a transcript to the text and application around the cursor.

```python
from wisprflow import (
    EditingStrength,
    Language,
    TranscriptionContext,
    TranscriptionOptions,
    WisprClient,
    WritingStyle,
)

client = WisprClient.from_desktop()
result = client.transcribe(
    "recording.wav",
    options=TranscriptionOptions(
        languages=[Language.EN],
        style=WritingStyle.FORMAL,
        cleanup=EditingStrength.LIGHT,
        dictionary=["Codex"],
    ),
    context=TranscriptionContext(
        before_text="Dear team,",
        app_name="Outlook",
    ),
)
```

To reuse preferences and dictionary entries from the desktop app, opt in when
creating the client:

```python
client = WisprClient.from_desktop(use_desktop_preferences=True)
```

These files are read without being modified. Preferences are reloaded for each
transcription, and explicitly supplied `TranscriptionOptions` take precedence.

## Authentication

The client uses the current Wispr Flow desktop login and refreshes an expired
access token when possible. In the normal case, no authentication configuration
is required.

If automatic discovery is unavailable, provide the public Supabase key through
one of these sources, in priority order:

1. The `supabase_anon_key` argument to `WisprClient.from_desktop()`
2. `supabase_anon_keys["<project ref>"]` in the SDK config file
3. The `WISPRFLOW_SUPABASE_ANON_KEY` environment variable
4. Read-only discovery from the installed desktop bundle

The SDK config file is located at:

- Windows: `%APPDATA%/wisprflow-re/config.json`
- macOS: `~/Library/Application Support/wisprflow-re/config.json`
- Linux: `$XDG_CONFIG_HOME/wisprflow-re/config.json` or
  `~/.config/wisprflow-re/config.json`

Example:

```json
{
  "supabase_anon_keys": {
    "<SUPABASE_PROJECT_REF>": "<SUPABASE_PUBLISHABLE_KEY>"
  }
}
```

Set `auto_discover=False` to prevent inspection of the installed desktop bundle.
A custom session path can be passed as `session_path=Path(...)`.

## Advanced routing

The default route requires no private backend credentials. A direct backend can
be configured explicitly when needed:

```python
from wisprflow import RuntimeRoute, WisprClient

route = RuntimeRoute(
    host="model-<MODEL_ID>.grpc.api.baseten.co",
    model_id="<MODEL_ID>",
    environment="production",
    backend_key="<BASETEN_API_KEY>",
)
client = WisprClient.from_desktop(route=route)
```

Keep backend keys outside source control. The client does not ship with or infer
private backend credentials.

## Development

```console
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Project status

This client relies on a reverse-engineered desktop protocol, so compatibility can
break when Wispr Flow changes its application or service. The public client API
is intentionally small to keep those changes isolated.

Protocol behavior was informed by the MIT-licensed
[`ThisisShashwat/wisprflow-sdk`](https://github.com/ThisisShashwat/wisprflow-sdk)
and inspection of the installed client's non-secret routing behavior.
