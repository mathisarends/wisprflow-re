import shutil
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from wisprflow.errors import AudioConversionError


@contextmanager
def normalized_audio(path: str | Path) -> Generator[bytes, None, None]:
    source = Path(path)
    if not source.is_file():
        raise AudioConversionError(f"Audio file does not exist: {source}")
    if shutil.which("ffmpeg") is None:
        raise AudioConversionError("FFmpeg is required but was not found on PATH.")
    with tempfile.TemporaryDirectory(prefix="wisprflow-") as directory:
        output = Path(directory) / "audio.wav"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-sample_fmt",
                    "s16",
                    str(output),
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors="replace")[:500]
            raise AudioConversionError(f"FFmpeg conversion failed: {detail}") from None
        yield output.read_bytes()
