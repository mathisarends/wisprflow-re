import subprocess
from pathlib import Path

import pytest

import whisprflow.audio as audio
from whisprflow import AudioConversionError
from whisprflow.audio import normalized_audio


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    source = tmp_path / "recording.m4a"
    source.write_bytes(b"not really an m4a")
    return source


@pytest.fixture
def ffmpeg(monkeypatch) -> list[list[str]]:
    """Pretend FFmpeg is installed and record the command lines it receives."""
    monkeypatch.setattr(audio.shutil, "which", lambda name: f"/usr/bin/{name}")
    invocations: list[list[str]] = []

    def run(command, *, check, capture_output):
        invocations.append(command)
        Path(command[-1]).write_bytes(b"RIFF converted wav")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(audio.subprocess, "run", run)
    return invocations


def test_audio_is_converted_to_the_format_wispr_expects(recording, ffmpeg):
    with normalized_audio(recording) as converted:
        assert converted == b"RIFF converted wav"

    command = ffmpeg[0]
    assert command[0] == "ffmpeg"
    assert command[command.index("-i") + 1] == str(recording)
    assert command[command.index("-ar") + 1] == "16000"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-sample_fmt") + 1] == "s16"


def test_the_temporary_conversion_is_cleaned_up(recording, ffmpeg):
    with normalized_audio(str(recording)):
        output = Path(ffmpeg[0][-1])
        assert output.is_file()

    assert not output.parent.exists()


def test_a_missing_source_is_reported_before_ffmpeg_runs(tmp_path, ffmpeg):
    with pytest.raises(AudioConversionError, match="does not exist"):
        with normalized_audio(tmp_path / "missing.wav"):
            pass

    assert ffmpeg == []


def test_a_missing_ffmpeg_is_reported_as_a_setup_problem(recording, monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda name: None)

    with pytest.raises(AudioConversionError, match="FFmpeg is required"):
        with normalized_audio(recording):
            pass


def test_a_failed_conversion_surfaces_the_ffmpeg_diagnostics(recording, monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    def run(command, *, check, capture_output):
        raise subprocess.CalledProcessError(
            1, command, stderr=b"Invalid data found when processing input"
        )

    monkeypatch.setattr(audio.subprocess, "run", run)

    with pytest.raises(AudioConversionError, match="Invalid data found"):
        with normalized_audio(recording):
            pass
