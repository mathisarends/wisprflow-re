import sys
import wave
from contextlib import AbstractContextManager
from io import BytesIO

import pytest

import whisprflow.audio_input as audio_input
from whisprflow import AudioInputError, OptionalDependencyError, SoundDeviceMicrophone


class FakeStream(AbstractContextManager):
    """A PortAudio stream that delivers a fixed set of callbacks on entry."""

    frames: list[bytes] = [b"\x01\x00\x02\x00"]
    status: object = None
    error: Exception | None = None
    opened_with: dict = {}

    def __init__(self, **kwargs):
        if type(self).error is not None:
            raise type(self).error
        type(self).opened_with = kwargs
        self.kwargs = kwargs

    def __enter__(self):
        for frame in type(self).frames:
            self.kwargs["callback"](frame, len(frame) // 2, None, type(self).status)
        return self

    def __exit__(self, *args):
        return False


class FakeSoundDevice:
    RawInputStream = FakeStream

    @staticmethod
    def query_hostapis():
        return [{"name": "Fake API"}]

    @staticmethod
    def query_devices():
        return [
            {
                "name": "Fake Mic",
                "hostapi": 0,
                "max_input_channels": 1,
                "default_samplerate": 16000,
            },
            {
                "name": "Output only",
                "hostapi": 0,
                "max_input_channels": 0,
                "default_samplerate": 48000,
            },
        ]


@pytest.fixture
def sounddevice(monkeypatch):
    monkeypatch.setattr(FakeStream, "frames", [b"\x01\x00\x02\x00"])
    monkeypatch.setattr(FakeStream, "status", None)
    monkeypatch.setattr(FakeStream, "error", None)
    monkeypatch.setattr(audio_input, "_sounddevice", lambda: FakeSoundDevice)
    return FakeStream


def test_capture_returns_a_wav_the_backend_accepts(sounddevice):
    microphone = SoundDeviceMicrophone(prompt=lambda message: "")

    recording = microphone.capture()

    with wave.open(BytesIO(recording), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(2) == b"\x01\x00\x02\x00"


def test_recording_stops_on_the_prompt_and_passes_the_device_through(sounddevice):
    prompts = []
    microphone = SoundDeviceMicrophone(
        device="Fake Mic", sample_rate=48_000, channels=2, prompt=prompts.append
    )

    microphone.capture()

    assert prompts == ["Recording. Press Enter to stop... "]
    assert sounddevice.opened_with["device"] == "Fake Mic"
    assert sounddevice.opened_with["samplerate"] == 48_000
    assert sounddevice.opened_with["channels"] == 2
    assert sounddevice.opened_with["dtype"] == "int16"


def test_a_fixed_duration_records_without_prompting(sounddevice):
    def fail(message):
        raise AssertionError("A timed recording must not wait for the user")

    microphone = SoundDeviceMicrophone(duration=0.01, prompt=fail)

    assert microphone.capture()


def test_silence_from_the_device_is_an_error_not_an_empty_wav(sounddevice, monkeypatch):
    monkeypatch.setattr(FakeStream, "frames", [])

    with pytest.raises(AudioInputError, match="no audio"):
        SoundDeviceMicrophone(prompt=lambda message: "").capture()


def test_a_reported_stream_error_is_not_silently_transcribed(sounddevice, monkeypatch):
    monkeypatch.setattr(FakeStream, "status", "input overflow")

    with pytest.raises(AudioInputError, match="input overflow"):
        SoundDeviceMicrophone(prompt=lambda message: "").capture()


def test_a_device_that_cannot_be_opened_is_reported(sounddevice, monkeypatch):
    monkeypatch.setattr(FakeStream, "error", RuntimeError("Invalid device"))

    with pytest.raises(AudioInputError, match="Invalid device"):
        SoundDeviceMicrophone(prompt=lambda message: "").capture()


def test_only_input_devices_are_offered(sounddevice):
    devices = SoundDeviceMicrophone.devices()

    assert len(devices) == 1
    assert devices[0].index == 0
    assert devices[0].name == "Fake Mic"
    assert devices[0].host_api == "Fake API"
    assert devices[0].channels == 1
    assert devices[0].default_sample_rate == 16000


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"sample_rate": 0}, "'sample_rate' must be positive"),
        ({"channels": 0}, "'channels' must be positive"),
        ({"duration": 0}, "'duration' must be positive"),
    ],
)
def test_impossible_recording_settings_are_rejected_up_front(settings, message):
    with pytest.raises(ValueError, match=message):
        SoundDeviceMicrophone(**settings)


def test_the_missing_microphone_extra_explains_how_to_install_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)

    with pytest.raises(OptionalDependencyError, match="microphone"):
        audio_input._sounddevice()
