"""Try the patch-free Wispr Flow client with your existing desktop login.

Examples:
    uv run python -m examples.try_desktop recording.wav
    uv run python -m examples.try_desktop recording.mp3 --refresh

The default uses inference.wisprflow.com and the current access token from the
official desktop session. ``--refresh`` asks for the Supabase publishable/anon
key without echoing it. No token or key is printed.
"""

import argparse
import getpass
import sys
from datetime import UTC, datetime
from pathlib import Path

from whisprflow import (
    CredentialsError,
    RuntimeRoute,
    TranscriptionContext,
    TranscriptionOptions,
    WisprClient,
    WisprFlowError,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe one audio file through the Wispr desktop session."
    )
    parser.add_argument("audio", type=Path, help="Audio file accepted by FFmpeg")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Prompt for a Supabase publishable key to enable token refresh",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Use an explicit direct Baseten route instead of the edge proxy",
    )
    parser.add_argument("--model-id", help="Required with --direct")
    parser.add_argument(
        "--host", help="Direct host; derived from --model-id if omitted"
    )
    parser.add_argument("--language", action="append", dest="languages")
    parser.add_argument("--style", default="CASUAL")
    parser.add_argument("--cleanup", default="NONE")
    parser.add_argument(
        "--before", default="", help="Text immediately before the cursor"
    )
    parser.add_argument("--app", default="", help="Application name used as context")
    return parser.parse_args()


def build_route(args: argparse.Namespace) -> RuntimeRoute:
    if not args.direct:
        return RuntimeRoute()
    if not args.model_id:
        raise ValueError("--model-id is required with --direct")
    backend_key = getpass.getpass("Baseten API key (input hidden): ").strip()
    if not backend_key:
        raise ValueError("A backend key is required with --direct")
    return RuntimeRoute(
        host=args.host or f"model-{args.model_id}.grpc.api.baseten.co",
        model_id=args.model_id,
        environment="production",
        backend_key=backend_key,
    )


def main() -> int:
    args = parse_args()
    if not args.audio.is_file():
        print(f"Audio file not found: {args.audio}", file=sys.stderr)
        return 2

    publishable_key = None
    if args.refresh:
        publishable_key = getpass.getpass(
            "Supabase publishable/anon key (input hidden): "
        ).strip()
        if not publishable_key:
            print("No publishable key supplied.", file=sys.stderr)
            return 2

    try:
        client = WisprClient.from_desktop(
            supabase_anon_key=publishable_key,
            route=build_route(args),
        )
        status = client.auth_status()
        expires = (
            datetime.fromtimestamp(status.expires_at, UTC).isoformat()
            if status.expires_at is not None
            else "unknown"
        )
        print(
            f"Auth: {status.status}; expires: {expires}; "
            f"automatic refresh: {status.refresh_available}"
        )
        print("Route: direct Baseten" if args.direct else "Route: Wispr edge proxy")
        print("Transcribing...")

        result = client.transcribe(
            args.audio,
            options=TranscriptionOptions(
                languages=args.languages or ["en"],
                style=args.style,
                cleanup=args.cleanup,
            ),
            context=TranscriptionContext(
                before_text=args.before,
                app_name=args.app,
            ),
        )
    except CredentialsError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        return 3
    except (ValueError, WisprFlowError) as exc:
        print(f"Wispr request failed: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:
        # gRPC errors are intentionally rendered without credential material.
        print(
            f"Unexpected request failure: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        return 5

    print("\nTranscript:\n")
    print(result.final)
    if result.raw and result.raw != result.final:
        print("\nRaw transcript:\n")
        print(result.raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
