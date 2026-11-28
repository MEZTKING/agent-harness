"""Made-up audio for the sound tests: real MP3 frames and WAV files, no service involved."""

import io
import math
import wave


def mp3(seconds: float = 1.0) -> bytes:
    """An MP3 of about ``seconds`` (MPEG-1 Layer III frames at 128 kbit/s, 44.1 kHz; silent frames)."""
    frame = b"\xff\xfb\x90\x00" + b"\x00" * (417 - 4)
    n = max(1, int(round(seconds * 44100 / 1152)))
    return b"ID3\x03\x00\x00\x00\x00\x00\x00" + frame * n


def wav(seconds: float = 1.0, loud: bool = True, rate: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        amp = 8000 if loud else 0
        w.writeframes(b"".join(int(amp * math.sin(i / 5)).to_bytes(2, "little", signed=True)
                               for i in range(int(seconds * rate))))
    return buf.getvalue()
