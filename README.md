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
- Refresh an expired Supabase session when a publishable key is supplied
- Preserve unknown session fields and rotated refresh tokens
- Use `inference.wisprflow.com` as a patch-free edge-proxy route
- Support an explicit direct-backend route without embedding private keys
- Encode the observed protobuf stream without generated stubs
- Normalize audio through FFmpeg
- Inject cursor, application, and dynamic-vocabulary context

No JavaScript is injected and `app.asar` is never modified or inspected.

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

Add `--refresh` to enter the Supabase publishable key through a hidden prompt.
Use `--direct --model-id <MODEL_ID>` only when testing an explicit Baseten
fallback route.

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
result = client.transcribe_input(microphone)
print(result.final)
```

The default works while the access token in the desktop session is fresh. To
allow refresh, pass the Supabase **publishable/anon** key explicitly. The SDK
does not read it from `.env`, environment variables, or the desktop bundle.

```python
client = WisprClient.from_desktop(
    supabase_anon_key="<SUPABASE_PUBLISHABLE_KEY>",
)
```

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

FFmpeg must be available on `PATH` for file transcription. If audio is already
a normalized 16 kHz mono PCM16 WAV payload, use `transcribe_bytes()`.

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
