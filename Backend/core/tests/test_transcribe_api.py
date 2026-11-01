import struct

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from core.agent.transcriber import TranscriptionUnavailable, TranscriptResult

User = get_user_model()


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


def audio_file(data: bytes | None = None) -> SimpleUploadedFile:
    return SimpleUploadedFile("a.wav", data if data is not None else make_wav(), content_type="audio/wav")


@pytest.fixture
def auth_client(db):
    User.objects.create_user(username="voice", password="secretpassword123")
    client = Client()
    client.login(username="voice", password="secretpassword123")
    return client


def test_transcribe_requires_auth():
    client = Client()
    response = client.post("/api/voice/transcribe/")
    assert response.status_code == 401


def test_transcribe_rejects_bad_wav(auth_client):
    response = auth_client.post("/api/voice/transcribe/", data={"language": "en", "audio": audio_file(b"nope")})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_REQUEST"

    stereo = make_wav()
    stereo = stereo[:22] + struct.pack("<H", 2) + stereo[24:]
    response = auth_client.post("/api/voice/transcribe/", {"language": "en", "audio": audio_file(stereo)})
    assert response.status_code == 400


@pytest.mark.django_db
def test_transcribe_success_and_rate_limit(auth_client, monkeypatch):
    async def fake_transcribe(self, wav_bytes, hints=None, preferred_language="auto"):
        return TranscriptResult(
            spoken_text="open Wikipedia",
            language="en",
            english_command="open Wikipedia",
            confidence="high",
            complete=True,
            model="gemini-3.5-flash-lite",
        )

    monkeypatch.setattr("core.api.views.Transcriber.transcribe", fake_transcribe)
    cache.clear()
    response = auth_client.post("/api/voice/transcribe/", {"language": "en", "audio": audio_file()})
    assert response.status_code == 200
    body = response.json()
    assert body["english_command"] == "open Wikipedia"
    assert body["model"] == "gemini-3.5-flash-lite"
    cache.set(f"transcribe_rate:{auth_client.session['_auth_user_id']}", 30, 60)
    limited = auth_client.post("/api/voice/transcribe/", {"language": "en", "audio": audio_file()})
    assert limited.status_code == 429


@pytest.mark.django_db
def test_transcribe_unavailable(auth_client, monkeypatch):
    async def boom(self, *args, **kwargs):
        raise TranscriptionUnavailable("down")

    monkeypatch.setattr("core.api.views.Transcriber.transcribe", boom)
    cache.clear()
    response = auth_client.post("/api/voice/transcribe/", {"language": "en", "audio": audio_file()})
    assert response.status_code == 503
    assert response.json()["error_code"] == "TRANSCRIPTION_UNAVAILABLE"


def test_transcribe_csrf_required(db):
    User.objects.create_user(username="csrfuser", password="secretpassword123")
    client = Client(enforce_csrf_checks=True)
    client.login(username="csrfuser", password="secretpassword123")
    response = client.post("/api/voice/transcribe/", {"language": "en", "audio": audio_file()})
    assert response.status_code == 403
