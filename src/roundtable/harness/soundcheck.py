"""Is a bought sound real audio of the asked kind? (wave 9)

Standard library only, no decoder: an MP3 is known by its ID3 tag or a frame header (and its length worked out
from the frames' bit rate); a WAV is read with :mod:`wave`, its length exact and its loudness measured, so a
silent WAV is caught. A sound may be at most twice the asked length (and a little over, for rounding).

:func:`check` answers ``(ok, why)``: ``why`` is one plain sentence when it isn't.
"""

from __future__ import annotations

import array
import io
import sys
import wave

_BITRATES = {  # MPEG-1 Layer III and MPEG-2/2.5 Layer III, kbit/s by index
    1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
SLACK = 1.0  # seconds over twice the asked length still allowed


def _skip_id3(data: bytes) -> int:
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    size = (data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F)
    return 10 + size


def _frame(data: bytes, i: int) -> tuple[int, float] | None:
    """(frame length in bytes, its seconds) for an MP3 frame header at ``i``, else None."""
    if i + 4 > len(data) or data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
        return None
    version = (data[i + 1] >> 3) & 3  # 3: MPEG-1, 2: MPEG-2, 0: MPEG-2.5
    layer = (data[i + 1] >> 1) & 3  # 1: Layer III
    if version == 1 or layer != 1:
        return None
    br_i, sr_i, pad = (data[i + 2] >> 4) & 15, (data[i + 2] >> 2) & 3, (data[i + 2] >> 1) & 1
    if sr_i == 3:
        return None
    kbps = _BITRATES[1 if version == 3 else 2][br_i]
    if not kbps:
        return None
    rate = _RATES[version][sr_i]
    samples = 1152 if version == 3 else 576
    length = (144 if version == 3 else 72) * kbps * 1000 // rate + pad
    return (length, samples / rate) if length > 4 else None


def mp3_seconds(data: bytes) -> float | None:
    """The length of an MP3 from its frames, or None when no frame is found."""
    i = _skip_id3(data)
    start = None
    for j in range(i, min(len(data) - 4, i + 4096)):  # the first frame, near the start
        if _frame(data, j):
            start = j
            break
    if start is None:
        return None
    total, frames, j = 0.0, 0, start
    while j < len(data):
        f = _frame(data, j)
        if not f:
            break
        total += f[1]
        frames += 1
        j += f[0]
    return total if frames else None


def wav_facts(data: bytes) -> tuple[float, int] | None:
    """(seconds, the loudest sample's size 0 to 32767 for 16-bit) of a WAV, or None when it isn't one."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            n, rate, width = w.getnframes(), w.getframerate(), w.getsampwidth()
            frames = w.readframes(n)
    except (wave.Error, EOFError, ValueError):
        return None
    if not rate:
        return None
    peak = 0
    if width == 2 and frames:
        a = array.array("h")
        a.frombytes(frames[: len(frames) // 2 * 2])
        if sys.byteorder == "big":
            a.byteswap()
        peak = max((abs(x) for x in a), default=0)
    elif width == 1 and frames:
        peak = max(abs(b - 128) for b in frames) * 256
    else:
        peak = 1 if any(frames) else 0
    return n / rate, peak


def check(data: bytes, ext: str, kind: str, seconds: float | None) -> tuple[bool, str]:
    """Is ``data`` a real sound of about the asked length? ``(True, "")`` or ``(False, why)``."""
    if not data or len(data) < 64:
        return False, "The service sent back an empty file."
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        facts = wav_facts(data)
        if not facts:
            return False, "The file says it's a WAV but can't be read."
        length, peak = facts
        if length <= 0:
            return False, "The sound has no length."
        if peak < 33:  # below about -60 dB: silence
            return False, "The sound is silent."
    else:
        length = mp3_seconds(data)
        if length is None:
            return False, "The file isn't an MP3 or a WAV."
    if seconds and length > 2 * float(seconds) + SLACK:
        return False, f"The sound is {length:.1f} seconds long; {float(seconds):g} were asked for."
    return True, ""
