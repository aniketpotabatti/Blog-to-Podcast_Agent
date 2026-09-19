"""Tests for music beds and ffmpeg-free mixing (Feature 5)."""

from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf

from podcast import config
from podcast.audio import (
    AudioBuffer,
    apply_gain,
    apply_music_preset,
    build_music_bed,
    db_to_gain,
    decode_audio,
    duck_gain_for_overlay,
    encode_mp3,
    fade,
    loop_or_trim,
    mix_tracks,
    normalize_peak,
    peak_dbfs,
    resample,
    slice_seconds,
    to_mono,
)
from podcast.config import MusicPreset, get_music_preset
from podcast.errors import AudioProcessingError, ConfigurationError
from tests.conftest import make_mp3_bytes


def duration_of(data: bytes) -> float:
    """Decode audio bytes and return their duration in seconds."""
    buffer = decode_audio(data)
    return buffer.duration


class FakeMusic:
    """Records music composition calls."""

    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else make_mp3_bytes(2.0)
        self.error = error
        self.calls = []

    def compose(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return iter([self.payload])


class FakeMusicClient:
    """Minimal ElevenLabs client exposing the music namespace."""

    def __init__(self, music=None):
        self.music = music or FakeMusic()


class TestDecodeEncode:
    """MP3 decoding/encoding underpins every mixing operation."""

    def test_decodes_mp3_into_mono_float32(self):
        buffer = decode_audio(make_mp3_bytes(1.0))
        assert buffer.sample_rate > 0
        assert buffer.duration == pytest.approx(1.0, abs=0.1)
        assert buffer.samples.dtype == np.float32
        assert buffer.samples.ndim == 1

    def test_empty_payload_is_rejected(self):
        with pytest.raises(AudioProcessingError):
            decode_audio(b"")

    def test_garbage_payload_is_rejected(self):
        with pytest.raises(AudioProcessingError) as exc:
            decode_audio(b"this is not audio")
        assert exc.value.hint

    def test_encode_roundtrip_preserves_duration(self):
        samples = np.sin(np.linspace(0, 100, 22050)).astype("float32") * 0.3
        data = encode_mp3(AudioBuffer(samples=samples, sample_rate=22050))
        assert duration_of(data) == pytest.approx(1.0, abs=0.1)

    def test_encode_clips_out_of_range_samples(self):
        loud = np.array([5.0, -5.0, 0.0], dtype="float32")
        data = encode_mp3(AudioBuffer(samples=loud, sample_rate=22050))
        assert decode_audio(data).samples.size > 0

    def test_target_rate_resamples_on_decode(self):
        buffer = decode_audio(make_mp3_bytes(1.0, rate=44100), target_rate=22050)
        assert buffer.sample_rate == 22050


class TestDspHelpers:
    """Small DSP primitives used by the mixer."""

    def test_to_mono_averages_channels(self):
        stereo = np.array([[1.0, 0.0], [0.5, 0.5]], dtype="float32")
        assert np.allclose(to_mono(stereo), [0.5, 0.5])

    def test_to_mono_is_identity_for_1d(self):
        mono = np.array([1.0, 2.0], dtype="float32")
        assert np.allclose(to_mono(mono), mono)

    def test_resample_changes_length_proportionally(self):
        samples = np.zeros(1000, dtype="float32")
        assert resample(samples, 1000, 2000).size == 2000
        assert resample(samples, 2000, 1000).size == 500

    def test_resample_identity(self):
        samples = np.arange(10, dtype="float32")
        assert np.allclose(resample(samples, 44100, 44100), samples)

    def test_db_to_gain(self):
        assert db_to_gain(0) == pytest.approx(1.0)
        assert db_to_gain(-6) == pytest.approx(0.501, abs=0.01)

    def test_apply_gain_scales_samples(self):
        assert np.allclose(apply_gain(np.ones(4, dtype="float32"), -6), 0.501, atol=0.01)

    def test_peak_dbfs_of_silence(self):
        assert peak_dbfs(np.zeros(10, dtype="float32")) == float("-inf")

    def test_peak_dbfs_of_full_scale(self):
        assert peak_dbfs(np.ones(10, dtype="float32")) == pytest.approx(0.0, abs=0.01)

    def test_fade_in_starts_at_zero_and_keeps_middle(self):
        samples = np.ones(1000, dtype="float32")
        faded = fade(samples, 1000, fade_in=0.1)
        assert faded[0] == pytest.approx(0.0)
        assert faded[500] == pytest.approx(1.0)

    def test_fade_out_ends_at_zero(self):
        faded = fade(np.ones(1000, dtype="float32"), 1000, fade_out=0.1)
        assert faded[-1] == pytest.approx(0.0, abs=1e-6)

    def test_slice_seconds(self):
        samples = np.arange(1000, dtype="float32")
        assert slice_seconds(samples, 1000, 0.2, 0.3).size == 300

    def test_loop_or_trim_extends_short_buffers(self):
        samples = np.array([1.0, 2.0], dtype="float32")
        looped = loop_or_trim(samples, 1000, 0.01)
        assert looped.size == 10
        assert looped[0] == 1.0 and looped[1] == 2.0

    def test_loop_or_trim_shortens_long_buffers(self):
        assert loop_or_trim(np.ones(1000, dtype="float32"), 1000, 0.1).size == 100

    def test_mix_tracks_adds_overlay(self):
        base = np.ones(10, dtype="float32")
        mixed = mix_tracks(base, base, gain_db=-6)
        assert mixed[0] == pytest.approx(1.5, abs=0.02)

    def test_mix_tracks_keeps_longer_base(self):
        base = np.ones(10, dtype="float32")
        mixed = mix_tracks(base, np.ones(4, dtype="float32"))
        assert mixed.size == 10

    def test_duck_gain_is_clamped(self):
        assert duck_gain_for_overlay(-5) == -12.0
        assert duck_gain_for_overlay(-80) == -30.0
        assert duck_gain_for_overlay(-22) == -22.0

    def test_normalize_peak(self):
        loud = np.array([0.5, -0.25], dtype="float32")
        assert peak_dbfs(normalize_peak(loud, target_dbfs=-1.0)) == pytest.approx(-1.0, abs=0.01)

    def test_normalize_peak_ignores_silence(self):
        assert normalize_peak(np.zeros(4, dtype="float32")).size == 4


# ─────────────────────────────────────────────
#  FEATURE 5: music bed generation
# ─────────────────────────────────────────────
class TestBuildMusicBed:
    """Music beds are generated once per preset and then cached."""

    def test_no_music_preset_returns_none_without_a_client(self):
        assert build_music_bed(get_music_preset("none")) is None

    def test_generates_and_caches_the_bed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
        client = FakeMusicClient()
        audio = build_music_bed(get_music_preset("intro_outro"), client=client)

        assert audio
        assert len(client.music.calls) == 1
        assert (tmp_path / "intro_outro.mp3").exists()

    def test_second_call_uses_the_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
        client = FakeMusicClient()
        build_music_bed(get_music_preset("upbeat"), client=client)
        build_music_bed(get_music_preset("upbeat"), client=client)
        assert len(client.music.calls) == 1

    def test_cache_can_be_bypassed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
        client = FakeMusicClient()
        build_music_bed(get_music_preset("upbeat"), client=client)
        build_music_bed(get_music_preset("upbeat"), client=client, use_cache=False)
        assert len(client.music.calls) == 2

    def test_request_is_instrumental_within_limits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
        client = FakeMusicClient()
        build_music_bed(get_music_preset("lofi"), client=client, length_ms=999_000)

        call = client.music.calls[0]
        assert call["force_instrumental"] is True
        assert call["music_length_ms"] <= config.MUSIC_MAX_LENGTH_MS
        assert call["prompt"]

    def test_missing_api_key_raises_configuration_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
        with pytest.raises(ConfigurationError):
            build_music_bed(get_music_preset("cinematic"), api_key="")

    def test_provider_failure_is_typed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
        monkeypatch.setattr(config, "MAX_RETRIES", 1)
        client = FakeMusicClient(FakeMusic(error=RuntimeError("400 bad prompt")))
        with pytest.raises(AudioProcessingError):
            build_music_bed(get_music_preset("upbeat"), client=client)

    def test_empty_audio_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
        client = FakeMusicClient(FakeMusic(payload=b""))
        with pytest.raises(AudioProcessingError):
            build_music_bed(get_music_preset("upbeat"), client=client)


# ─────────────────────────────────────────────
#  FEATURE 5: mixing narration with music
# ─────────────────────────────────────────────
class TestApplyMusicPreset:
    """The mixer must always return usable audio."""

    NARRATION_SECONDS = 3.0

    @pytest.fixture
    def narration(self):
        return make_mp3_bytes(self.NARRATION_SECONDS, frequency=440.0)

    @pytest.fixture
    def music(self):
        return make_mp3_bytes(10.0, frequency=110.0)

    def test_no_music_preset_returns_narration_unchanged(self, narration):
        audio, report = apply_music_preset(narration, get_music_preset("none"))
        assert audio == narration
        assert report.applied is False

    def test_missing_music_returns_narration_unchanged(self, narration):
        audio, report = apply_music_preset(narration, get_music_preset("upbeat"))
        assert audio == narration
        assert report.applied is False
        assert "unavailable" in report.reason

    def test_intro_and_outro_extend_the_episode(self, narration, music):
        preset = MusicPreset(
            key="test_stings", label="Test", description="", prompt="x",
            intro_seconds=2.0, outro_seconds=2.0,
        )
        audio, report = apply_music_preset(narration, preset, music=music)
        assert report.applied is True
        assert report.intro_seconds == 2.0
        assert report.outro_seconds == 2.0
        assert duration_of(audio) == pytest.approx(
            self.NARRATION_SECONDS + 4.0, abs=0.35
        )

    def test_underlay_keeps_the_original_duration(self, narration, music):
        preset = MusicPreset(
            key="test_bed", label="Test", description="", prompt="x",
            underlay=True, underlay_gain_db=-24.0,
        )
        audio, report = apply_music_preset(narration, preset, music=music)
        assert report.applied is True
        assert report.underlay_seconds > 0
        assert report.gain_db == -24.0
        assert duration_of(audio) == pytest.approx(self.NARRATION_SECONDS, abs=0.35)

    def test_underlay_and_stings_combine(self, narration, music):
        preset = MusicPreset(
            key="test_full", label="Test", description="", prompt="x",
            intro_seconds=1.0, outro_seconds=1.0, underlay=True,
        )
        audio, report = apply_music_preset(narration, preset, music=music)
        assert report.applied is True
        assert duration_of(audio) == pytest.approx(self.NARRATION_SECONDS + 2.0, abs=0.4)

    def test_output_is_decodable_mp3(self, narration, music):
        audio, _ = apply_music_preset(narration, get_music_preset("upbeat"), music=music)
        decoded = decode_audio(audio)
        assert decoded.duration > self.NARRATION_SECONDS  # stings were added
        assert decoded.samples.size > 0

    def test_music_shorter_than_sting_is_handled(self, narration):
        preset = MusicPreset(
            key="test_short", label="Test", description="", prompt="x",
            intro_seconds=5.0, outro_seconds=5.0,
        )
        audio, report = apply_music_preset(
            narration, preset, music=make_mp3_bytes(0.2, frequency=200.0)
        )
        assert report.applied is True
        assert duration_of(audio) > 0

    def test_corrupt_narration_is_returned_untouched(self, music):
        broken = b"not audio at all"
        audio, report = apply_music_preset(broken, get_music_preset("upbeat"), music=music)
        assert audio == broken
        assert report.applied is False

    def test_corrupt_music_is_returned_untouched(self, narration):
        audio, report = apply_music_preset(
            narration, get_music_preset("upbeat"), music=b"broken music"
        )
        assert audio == narration
        assert report.applied is False

    def test_peak_is_normalized(self, narration, music):
        audio, _ = apply_music_preset(narration, get_music_preset("upbeat"), music=music)
        assert peak_dbfs(decode_audio(audio).samples) < 0.0