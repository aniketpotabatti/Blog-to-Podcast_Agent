"""Shared pytest fixtures for the Blog-to-Podcast test suite."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def make_mp3_bytes(seconds: float = 1.0, frequency: float = 440.0, rate: int = 44100) -> bytes:
    """Build a small mono MP3 payload for audio tests."""
    samples = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    wave = 0.2 * np.sin(2 * np.pi * frequency * samples)
    buffer = io.BytesIO()
    sf.write(buffer, wave.astype("float32"), rate, format="MP3")
    return buffer.getvalue()


@pytest.fixture
def silence_mp3() -> bytes:
    """One second of quiet audio encoded as MP3."""
    return make_mp3_bytes(seconds=1.0, frequency=330.0)


@pytest.fixture
def music_mp3() -> bytes:
    """Three seconds of musical tone used as a music bed."""
    return make_mp3_bytes(seconds=3.0, frequency=220.0)


@pytest.fixture
def sample_article():
    """A short Article instance for script/pipeline tests."""
    from podcast.models import Article, SourceKind

    return Article(
        text="Artificial intelligence is reshaping how teams ship software. " * 20,
        title="How AI Changes Software Teams",
        url="https://example.com/ai-teams",
        kind=SourceKind.URL,
        author="Jane Doe",
    )