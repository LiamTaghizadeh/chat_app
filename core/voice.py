"""
Voice capture & playback.

Uses PyAudio when available. Falls back to a no-op stub so the rest of the
application still works without a microphone.
"""

from __future__ import annotations

import io
import threading
import wave
from pathlib import Path
from typing import Callable, Optional

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False


class VoiceEngine:
    """Record short voice clips and play them back."""

    SAMPLE_RATE = 16000
    CHANNELS = 1
    SAMPLE_WIDTH = 2  # 16-bit
    CHUNK = 1024

    def __init__(self):
        self._pa = None
        self._recording = False
        self._frames: list = []
        self._stream = None
        self._record_thread: Optional[threading.Thread] = None
        self.enabled = HAS_PYAUDIO
        if HAS_PYAUDIO:
            try:
                self._pa = pyaudio.PyAudio()
            except Exception:
                self.enabled = False
                self._pa = None

    # ── Recording ─────────────────────────────────────────────

    def start_recording(self) -> bool:
        if not self.enabled or self._recording:
            return False
        self._frames = []
        self._recording = True

        def _worker():
            try:
                stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=self.CHANNELS,
                    rate=self.SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=self.CHUNK,
                )
                self._stream = stream
                while self._recording:
                    data = stream.read(self.CHUNK, exception_on_overflow=False)
                    self._frames.append(data)
            except Exception:
                self._recording = False
            finally:
                if self._stream:
                    try:
                        self._stream.stop_stream()
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None

        self._record_thread = threading.Thread(target=_worker, daemon=True)
        self._record_thread.start()
        return True

    def stop_recording(self) -> Optional[bytes]:
        """Stop and return WAV bytes (or None on failure)."""
        if not self._recording:
            return None
        self._recording = False
        if self._record_thread:
            self._record_thread.join(timeout=2.0)
            self._record_thread = None

        if not self._frames:
            return None

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.SAMPLE_WIDTH)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(b"".join(self._frames))
        self._frames = []
        return buf.getvalue()

    def is_recording(self) -> bool:
        return self._recording

    # ── Playback ──────────────────────────────────────────────

    def play_wav_bytes(self, data: bytes, on_done: Optional[Callable] = None) -> bool:
        if not self.enabled or not data:
            return False

        def _play():
            try:
                buf = io.BytesIO(data)
                with wave.open(buf, "rb") as wf:
                    stream = self._pa.open(
                        format=self._pa.get_format_from_width(wf.getsampwidth()),
                        channels=wf.getnchannels(),
                        rate=wf.getframerate(),
                        output=True,
                    )
                    chunk = wf.readframes(self.CHUNK)
                    while chunk:
                        stream.write(chunk)
                        chunk = wf.readframes(self.CHUNK)
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            finally:
                if on_done:
                    on_done()

        threading.Thread(target=_play, daemon=True).start()
        return True

    def play_file(self, path: str, on_done: Optional[Callable] = None) -> bool:
        try:
            data = Path(path).read_bytes()
            return self.play_wav_bytes(data, on_done)
        except Exception:
            return False

    def close(self) -> None:
        self._recording = False
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
