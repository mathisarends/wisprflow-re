# wisprflow-re

An unofficial, patch-free Python client for Wispr Flow's desktop transcription
protocol. It provides a small public API while keeping desktop-session reuse,
token refresh, routing metadata, protobuf encoding, gRPC streaming, and audio
normalization behind adapters.

This project is not affiliated with or endorsed by Wispr Flow. It uses the
caller's own authenticated desktop session and does not bypass subscriptions,
quotas, or feature entitlements.

## v1 scope

- Reuse the official desktop `session.json`
- Refresh an expired Supabase session automatically
- Preserve unknown session fields and rotated refresh tokens
- Use `inference.wisprflow.com` as a patch-free edge-proxy route
- Support an explicit direct-backend route without embedding private keys
- Encode the observed protobuf stream without generated stubs
- Normalize audio through FFmpeg
- Inject cursor, application, and dynamic-vocabulary context

No JavaScript is injected and `app.asar` is never modified. The SDK may scan it
read-only for the public Supabase key when no configured key is available.

## Requirements

- Python 3.12–3.14
- [uv](https://docs.astral.sh/uv/)
- An existing Wispr Flow desktop install (for its `session.json`)
- [FFmpeg](https://ffmpeg.org/) on `PATH` for file-based transcription

## Install

```text
uv sync
```

## Quick start

```python
from whisprflow import WisprClient

client = WisprClient.from_desktop()
result = client.transcribe("recording.mp3")
print(result.final)
```

An executable smoke-test example is included:

```text
uv run python -m examples.try_desktop recording.wav
```

Refresh works automatically with a supported desktop installation. Add
`--refresh` only to override discovery by entering the Supabase publishable key
through a hidden prompt. Use `--direct --model-id <MODEL_ID>` only when testing
an explicit Baseten fallback route.

## Speak directly into a microphone

Microphone capture is an optional PortAudio-based adapter. The core SDK remains
installable without it:

```text
uv sync --extra microphone
uv run --extra microphone python -m examples.try_microphone --list-devices
uv run --extra microphone python -m examples.try_microphone
```

The final command starts recording immediately. Speak, then press Enter to stop
and transcribe. Select a port or use a fixed recording duration when needed:

```text
uv run --extra microphone python -m examples.try_microphone --device 2
uv run --extra microphone python -m examples.try_microphone --duration 10
```

Programmatic usage:

```python
from whisprflow import SoundDeviceMicrophone, WisprClient

client = WisprClient.from_desktop()
microphone = SoundDeviceMicrophone(device=None)
result = client.transcribe(microphone)
print(result.final)
```

The default also refreshes expired access tokens. Publishable-key resolution is
lazy and uses this priority: an explicit argument, the SDK config file,
`WISPRFLOW_SUPABASE_ANON_KEY`, then read-only discovery from the installed
desktop bundle.

The optional config file is `%APPDATA%/wisprflow-re/config.json` on Windows,
`~/Library/Application Support/wisprflow-re/config.json` on macOS, and
`$XDG_CONFIG_HOME/wisprflow-re/config.json` (or `~/.config/...`) on Linux:

```json
{
  "supabase_anon_keys": {
    "<SUPABASE_PROJECT_REF>": "<SUPABASE_PUBLISHABLE_KEY>"
  }
}
```

An explicit key remains available as the highest-priority override:

```python
client = WisprClient.from_desktop(
    supabase_anon_key="<SUPABASE_PUBLISHABLE_KEY>",
)
```

To prohibit desktop-bundle inspection, use
`WisprClient.from_desktop(auto_discover=False)`. Custom integrations can inject
a `PublishableKeyResolver` implementation.

Direct Baseten routing is an explicit fallback:

```python
from whisprflow import RuntimeRoute, WisprClient

route = RuntimeRoute(
    host="model-<MODEL_ID>.grpc.api.baseten.co",
    model_id="<MODEL_ID>",
    environment="production",
    backend_key="<BASETEN_API_KEY>",
)
client = WisprClient.from_desktop(route=route)
```

For tests and other credential sources, inject adapters directly:

```python
client = WisprClient(
    auth=my_token_provider,
    user_id=my_user_id_provider,
    route=my_route,
    transport=my_transport,
)
```

## Options and context

```python
from whisprflow import (
    EditingStrength,
    Language,
    TranscriptionContext,
    TranscriptionOptions,
    WritingStyle,
)

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

The same method accepts file paths, normalized WAV bytes, and `AudioInput`
adapters. These accepted inputs are also exported as the `AudioSource` type
alias:

```python
from pathlib import Path

from whisprflow import SoundDeviceMicrophone

client.transcribe("recording.mp3")
client.transcribe(Path("recording.wav"))
client.transcribe(wav_bytes)
client.transcribe(SoundDeviceMicrophone())
```

FFmpeg must be available on `PATH` for file transcription. Byte payloads and
input adapters must produce normalized 16 kHz mono PCM16 WAV audio.

## Development

```text
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Stability

The protocol is reverse engineered and can change when Wispr updates its
desktop client. In particular, the edge proxy, protobuf fields, client version,
and authentication flow are compatibility boundaries. The adapter structure is
intended to isolate those changes from application code.

Protocol behavior was derived from the MIT-licensed
[`ThisisShashwat/wisprflow-sdk`](https://github.com/ThisisShashwat/wisprflow-sdk)
and inspection of the installed client's non-secret routing logic.
