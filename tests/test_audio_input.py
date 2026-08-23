import wave
from contextlib import AbstractContextManager
from io import BytesIO

import whisprflow.audio_input as audio_input
from whisprflow import SoundDeviceMicrophone


class FakeStream(AbstractContextManager):
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]

    def __enter__(self):
        self.callback(b"\x01\x00\x02\x00", 2, None, None)
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


def test_microphone_capture_returns_valid_wav(monkeypatch):
    monkeypatch.setattr(audio_input, "_sounddevice", lambda: FakeSoundDevice)
    microphone = SoundDeviceMicrophone(prompt=lambda message: "")

    recording = microphone.capture()

    with wave.open(BytesIO(recording), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(2) == b"\x01\x00\x02\x00"


def test_devices_only_returns_audio_inputs(monkeypatch):
    monkeypatch.setattr(audio_input, "_sounddevice", lambda: FakeSoundDevice)

    devices = SoundDeviceMicrophone.devices()

    assert len(devices) == 1
    assert devices[0].index == 0
    assert devices[0].name == "Fake Mic"
