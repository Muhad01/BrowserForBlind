import json
import logging
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.agent.gemini_base import LLMUnavailable
from core.agent.model_pool import ModelPool
from core.agent.transcriber import (
    Transcriber,
    TranscriptHints,
    TranscriptionUnavailable,
    build_hint_text,
    validate_wav_header,
)


def make_wav(seconds=0.2, rate=16000, channels=1, bits=16) -> bytes:
    frames = int(seconds * rate)
    data = b"\x00\x00" * frames * channels
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        rate,
        rate * channels * bits // 8,
        channels * bits // 8,
        bits,
        b"data",
        len(data),
    )
    return header + data


class FakeModels:
    def __init__(self, payloads, delay=0.0):
        self.payloads = list(payloads)
        self.calls = []
        self.delay = delay

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        if not self.payloads:
            raise LLMUnavailable("empty")
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item if isinstance(item, str) else json.dumps(item))


class FakeClient:
    def __init__(self, payloads, delay=0.0):
        self.aio = SimpleNamespace(models=FakeModels(payloads, delay=delay))


SAMPLE = {
    "spoken_text": "open Wikipedia and search for Babar Azam",
    "language": "en",
    "english_command": "open Wikipedia and search for Babar Azam",
    "confidence": "high",
    "complete": True,
}


@pytest.mark.asyncio
async def test_transcriber_parses_schema_and_omits_page_body(caplog):
    client = FakeClient([SAMPLE])
    transcriber = Transcriber(client=client, pool=ModelPool(["gemini-3.5-flash-lite"]), timeout=1)
    hints = TranscriptHints(
        page_title="Wikipedia",
        page_host="wikipedia.org",
        last_commands=["open dawn"],
        preferred_language="en",
    )
    result = await transcriber.transcribe(make_wav(), hints=hints, preferred_language="en")
    assert result.english_command == SAMPLE["english_command"]
    assert result.model == "gemini-3.5-flash-lite"
    sent = client.aio.models.calls[0]["contents"]
    blob = json.dumps(str(sent))
    assert "PAGE TEXT" not in blob
    assert "password" not in blob.lower()
    hint = build_hint_text(hints)
    assert "Wikipedia" in hint
    assert "open dawn" in hint


@pytest.mark.asyncio
async def test_transcriber_falls_back_then_unavailable():
    ok = Transcriber(
        client=FakeClient([SAMPLE]),
        pool=ModelPool(["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]),
        timeout=1,
    )
    result = await ok.transcribe(make_wav())
    assert result.complete is True

    fallback = Transcriber(
        client=FakeClient([RuntimeError("down"), SAMPLE]),
        pool=ModelPool(["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]),
        timeout=1,
    )
    recovered = await fallback.transcribe(make_wav())
    assert recovered.english_command == SAMPLE["english_command"]

    dead = Transcriber(
        client=FakeClient([RuntimeError("down"), RuntimeError("down")]),
        pool=ModelPool(["a", "b"]),
        timeout=1,
    )
    with pytest.raises(TranscriptionUnavailable):
        await dead.transcribe(make_wav())


@pytest.mark.asyncio
async def test_transcriber_never_logs_or_saves_audio(caplog, tmp_path):
    caplog.set_level(logging.INFO)
    transcriber = Transcriber(client=FakeClient([SAMPLE]), pool=ModelPool(["m"]), timeout=1)
    wav = make_wav()
    with tempfile.TemporaryDirectory() as folder:
        await transcriber.transcribe(wav)
        assert list(Path(folder).iterdir()) == []
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "RIFF" not in joined
    assert str(wav[:12]) not in joined


def test_validate_wav_rejects_wrong_format():
    assert validate_wav_header(b"nope") == "too_short"
    stereo = make_wav()
    stereo = stereo[:22] + struct.pack("<H", 2) + stereo[24:]
    assert validate_wav_header(stereo) == "not_mono"
    rate = make_wav()
    rate = rate[:24] + struct.pack("<I", 44100) + rate[28:]
    assert validate_wav_header(rate) == "bad_rate"
    assert validate_wav_header(make_wav(seconds=21)) == "too_long"
