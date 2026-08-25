import io
import threading
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from whisprflow.errors import AudioInputError, OptionalDependencyError


@runtime_checkable
class AudioInput(Protocol):
    """Port for anything that can produce an in-memory WAV recording."""

    def capture(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class InputDevice:
    index: int
    name: str
    host_api: str
    channels: int
    default_sample_rate: float


class SoundDeviceMicrophone:
    """PortAudio-backed microphone adapter provided by the `microphone` extra."""

    def __init__(
        self,
        *,
        device: int | str | None = None,
        sample_rate: int = 16_000,
        channels: int = 1,
        duration: float | None = None,
        prompt: Callable[[str], str] = input,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("'sample_rate' must be positive.")
        if channels <= 0:
            raise ValueError("'channels' must be positive.")
        if duration is not None and duration <= 0:
            raise ValueError("'duration' must be positive when supplied.")
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.duration = duration
        self._prompt = prompt

    @staticmethod
    def devices() -> list[InputDevice]:
        sounddevice = _sounddevice()
        host_apis = sounddevice.query_hostapis()
        devices: list[InputDevice] = []
        for index, raw in enumerate(sounddevice.query_devices()):
            channels = int(raw["max_input_channels"])
            if channels <= 0:
                continue
            host_index = int(raw["hostapi"])
            devices.append(
                InputDevice(
                    index=index,
                    name=str(raw["name"]),
                    host_api=str(host_apis[host_index]["name"]),
                    channels=channels,
                    default_sample_rate=float(raw["default_samplerate"]),
                )
            )
        return devices

    def capture(self) -> bytes:
        sounddevice = _sounddevice()
        chunks: list[bytes] = []
        callback_error: list[str] = []
        stopped = threading.Event()

        def callback(
            data: Any,
            frames: int,
            time_info: Any,
            status: Any,
        ) -> None:
            del frames, time_info
            if status:
                callback_error.append(str(status))
            chunks.append(bytes(data))

        try:
            with sounddevice.RawInputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                device=self.device,
                callback=callback,
            ):
                if self.duration is None:
                    self._prompt("Recording. Press Enter to stop... ")
                else:
                    stopped.wait(self.duration)
        except Exception as exc:
            raise AudioInputError(f"Microphone capture failed: {exc}") from None

        pcm = b"".join(chunks)
        if not pcm:
            raise AudioInputError("Microphone capture produced no audio.")
        if callback_error:
            raise AudioInputError(
                "Microphone reported a stream error: " + "; ".join(callback_error)
            )
        return _pcm16_wav(pcm, self.sample_rate, self.channels)


def _pcm16_wav(pcm: bytes, sample_rate: int, channels: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


def _sounddevice() -> Any:
    try:
        import sounddevice
    except ImportError:
        raise OptionalDependencyError(
            "Microphone capture requires the optional dependency: "
            "install with `uv sync --extra microphone` or "
            "`pip install wisprflow-re[microphone]`."
        ) from None
    return sounddevice
