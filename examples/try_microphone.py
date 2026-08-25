"""Record from a microphone and transcribe through the Wispr desktop session.

Install and run:
    uv sync --extra microphone
    uv run --extra microphone python -m examples.try_microphone --list-devices
    uv run --extra microphone python -m examples.try_microphone
"""

import argparse
import getpass
import sys

from whisprflow import (
    EditingStrength,
    Language,
    SoundDeviceMicrophone,
    TranscriptionContext,
    TranscriptionOptions,
    WisprClient,
    WisprFlowError,
    WritingStyle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record speech from an input device and transcribe it."
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available microphone/input ports and exit",
    )
    parser.add_argument(
        "--device",
        help="Input-device index or name; uses the system default when omitted",
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="Record this many seconds; otherwise press Enter to stop",
    )
    parser.add_argument("--sample-rate", type=int, default=16_000)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--language", action="append", dest="languages")
    parser.add_argument("--style", default="CASUAL")
    parser.add_argument("--cleanup", default="VERBATIM")
    parser.add_argument("--before", default="")
    parser.add_argument("--app", default="Terminal")
    return parser.parse_args()


def device_value(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def print_devices() -> None:
    devices = SoundDeviceMicrophone.devices()
    if not devices:
        print("No input devices found.")
        return
    for device in devices:
        print(
            f"[{device.index}] {device.name} | {device.host_api} | "
            f"channels={device.channels} | "
            f"default_rate={device.default_sample_rate:g}"
        )


def main() -> int:
    args = parse_args()
    try:
        if args.list_devices:
            print_devices()
            return 0

        publishable_key = None
        if args.refresh:
            publishable_key = getpass.getpass(
                "Supabase publishable/anon key (input hidden): "
            ).strip()
            if not publishable_key:
                print("No publishable key supplied.", file=sys.stderr)
                return 2

        microphone = SoundDeviceMicrophone(
            device=device_value(args.device),
            sample_rate=args.sample_rate,
            duration=args.duration,
        )
        client = WisprClient.from_desktop(supabase_anon_key=publishable_key)
        status = client.auth_status()
        print(f"Auth: {status.status}; automatic refresh: {status.refresh_available}")
        result = client.transcribe_input(
            microphone,
            options=TranscriptionOptions(
                languages=(
                    [
                        Language[value.upper().replace("-", "_")]
                        for value in args.languages
                    ]
                    if args.languages
                    else [Language.DE]
                ),
                style=WritingStyle[args.style.upper()],
                cleanup=EditingStrength[args.cleanup.upper()],
            ),
            context=TranscriptionContext(
                before_text=args.before,
                app_name=args.app,
            ),
        )
    except (KeyError, ValueError, WisprFlowError) as exc:
        print(f"Microphone transcription failed: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(
            f"Unexpected request failure: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        return 4

    print("\nTranscript:\n")
    print(result.final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
