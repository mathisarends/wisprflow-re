# Patch-free Wispr Flow SDK v1

Reference implementation:
https://github.com/ThisisShashwat/wisprflow-sdk

## Goal

Expose a stable transcription API while isolating all reverse-engineered
behavior behind auth, runtime, protocol, transport, and audio adapters. The
official desktop login is reused, but the desktop JavaScript bundle is never
patched.

## Public API

```python
client = WisprClient.from_desktop()
result = client.transcribe(path, options=options, context=context)
```

Advanced callers can inject a token provider, user-id provider, publishable-key
resolver, runtime route, and transport.

## Authentication

`DesktopSessionStore` discovers the single Supabase auth entry in Wispr's
`session.json`, independent of its project-specific key name. `DesktopAuth`
reloads the session for every request, checks expiry with a safety skew, and
serializes refreshes within the process. A publishable-key resolver checks an
explicit value, SDK configuration, the environment, and finally performs a
read-only scan of the installed desktop bundle. Rotated credentials are written
atomically while unknown fields are preserved. Discovery is lazy and can be
disabled.

## Runtime routing

The default route is the edge proxy observed in current desktop builds:
`inference.wisprflow.com:443`. It sends the user's bearer token and no embedded
private backend key. `RuntimeRoute` supports explicit model, environment, and
backend-key values as a compatibility fallback.

## Protocol

The implementation reproduces the observed raw gRPC stream:

1. Init metadata and preferences, followed by a non-final commit.
2. Optional cursor/application/screen context and non-final commit.
3. Normalized WAV data and final commit.

Responses are decoded into raw, formatted, plaintext, HTML, and status fields.
Local replacement and snippet processing produces `TranscriptResult.final`.

## Non-goals for v1

- Modifying or unpacking the installed `app.asar`
- Extracting or embedding private backend/API keys
- Implementing login UI or bypassing account limits
- Keyboard injection and command mode
- Cross-process refresh locking

## Optional audio input

`AudioInput` is the capture port accepted by `WisprClient.transcribe()`.
The `microphone` optional dependency provides `SoundDeviceMicrophone`, backed by
PortAudio through `sounddevice`. It enumerates input devices and captures PCM16
audio into an in-memory WAV, either for a fixed duration or until Enter is
pressed. No temporary recording is retained on disk.

## Compatibility boundary

The default edge route is an evidence-backed candidate, not an official API
contract. If it rejects the reconstructed gRPC method, use an explicit direct
route while the edge protocol is investigated. All network verification must
use the user's explicit opt-in; automated tests use synthetic credentials only.
