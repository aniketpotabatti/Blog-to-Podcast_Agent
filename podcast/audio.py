"""
Music beds: generation, decoding and ffmpeg-free mixing.
======================================================

Feature 5 - Background music (intro / outro / underlay)
    * ``build_music_bed`` generates instrumental music with ElevenLabs and
      caches it on disk, so the same preset is never paid for twice.
    * ``apply_music_preset`` mixes an intro sting, an optional continuous
      underlay and an outro sting around the narration.

Mixing is done in pure Python with ``numpy`` + ``soundfile`` (libsndfile
1.2+ reads and writes MP3), so the feature works without an ``ffmpeg``
binary - important for Streamlit Cloud and minimal containers.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import numpy as np
import soundfile as sf

from podcast import config
from podcast.errors import AudioProcessingError, ConfigurationError, classify_exception
from podcast.utils import get_logger, retry_call

LOGGER = get_logger("audio")

MP3_FORMAT = "MP3"
# libsndfile names MP3 encoders by MPEG layer; Layer III is "mp3".
MP3_SUBTYPE = "MPEG_LAYER_III"


@dataclass
class AudioBuffer:
    """Decoded mono audio held as float32 samples."""

    samples: np.ndarray
    sample_rate: int

    @property
    def duration(self) -> float:
        """Length of the buffer in seconds."""
        if self.sample_rate <= 0:
            return 0.0
        return float(len(self.samples)) / float(self.sample_rate)


# ─────────────────────────────────────────────
#  Low-level DSP helpers
# ─────────────────────────────────────────────
def decode_audio(data: bytes, *, target_rate: int = 0) -> AudioBuffer:
    """Decode an MP3/WAV/OGG payload into mono float32 samples.

    Args:
        data: Encoded audio bytes.
        target_rate: When set, resample to this rate.

    Raises:
        AudioProcessingError: when the payload cannot be decoded.
    """
    if not data:
        raise AudioProcessingError(
            "There is no audio to process.",
            hint="Generate the narration before adding music.",
        )
    try:
        samples, sample_rate = sf.read(
            io.BytesIO(data), dtype="float32", always_2d=False
        )
    except Exception as exc:
        raise AudioProcessingError(
            f"Could not decode the audio ({exc}).",
            hint="Ensure the narration was produced as MP3 or WAV audio.",
        ) from exc

    if samples.size == 0:
        raise AudioProcessingError(
            "The audio decoded to zero samples.",
            hint="Regenerate the narration and try again.",
        )

    mono = to_mono(samples)
    if target_rate and sample_rate != target_rate:
        mono = resample(mono, sample_rate, target_rate)
        sample_rate = target_rate
    return AudioBuffer(samples=mono, sample_rate=sample_rate)


def encode_mp3(buffer: AudioBuffer, *, subtype: str = MP3_SUBTYPE) -> bytes:
    """Encode mono float32 samples back to MP3 bytes."""
    clipped = np.clip(buffer.samples, -1.0, 1.0).astype("float32")
    stream = io.BytesIO()
    try:
        sf.write(
            stream,
            clipped,
            buffer.sample_rate,
            format=MP3_FORMAT,
            subtype=subtype,
        )
    except Exception as exc:  # pragma: no cover - libsndfile error surface
        raise AudioProcessingError(
            f"Could not encode the mixed audio as MP3 ({exc}).",
            hint="Install a libsndfile build that supports MP3 export.",
        ) from exc
    return stream.getvalue()


def to_mono(samples: np.ndarray) -> np.ndarray:
    """Down-mix multi-channel audio to a single float32 channel."""
    array = np.asarray(samples, dtype="float32")
    if array.ndim == 1:
        return array
    if array.ndim == 2:
        return array.mean(axis=1).astype("float32")
    raise AudioProcessingError(
        f"Unsupported audio shape {array.shape}.",
        hint="Provide 1-D or 2-D audio samples.",
    )


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Linearly resample mono audio between sample rates.

    Linear interpolation is sufficient here because both the narration and the
    generated music are already band-limited music/speech, and it avoids a
    heavy DSP dependency.
    """
    if source_rate == target_rate or source_rate <= 0 or target_rate <= 0:
        return np.asarray(samples, dtype="float32")
    array = np.asarray(samples, dtype="float32")
    if array.size == 0:
        return array
    duration = array.size / float(source_rate)
    target_count = max(1, int(round(duration * target_rate)))
    source_positions = np.arange(array.size, dtype="float64")
    target_positions = np.linspace(0.0, array.size - 1, target_count)
    resampled = np.interp(target_positions, source_positions, array)
    return resampled.astype("float32")


def db_to_gain(db: float) -> float:
    """Convert a decibel value into a linear gain factor."""
    return float(10.0 ** (db / 20.0))


def apply_gain(samples: np.ndarray, db: float) -> np.ndarray:
    """Scale samples by ``db`` decibels."""
    return (np.asarray(samples, dtype="float32") * db_to_gain(db)).astype("float32")


def peak_dbfs(samples: np.ndarray) -> float:
    """Peak level of the samples in dBFS (``-inf`` for silence)."""
    array = np.asarray(samples, dtype="float32")
    if array.size == 0:
        return float("-inf")
    peak = float(np.max(np.abs(array)))
    if peak <= 0.0:
        return float("-inf")
    return 20.0 * float(np.log10(peak))


def fade(
    samples: np.ndarray,
    sample_rate: int,
    *,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
) -> np.ndarray:
    """Apply linear fade-in and fade-out ramps to a buffer."""
    array = np.array(samples, dtype="float32", copy=True)
    total = array.size
    if total == 0 or sample_rate <= 0:
        return array

    in_samples = min(total, max(0, int(round(fade_in * sample_rate))))
    if in_samples > 1:
        array[:in_samples] *= np.linspace(0.0, 1.0, in_samples, dtype="float32")

    out_samples = min(total, max(0, int(round(fade_out * sample_rate))))
    if out_samples > 1:
        array[-out_samples:] *= np.linspace(1.0, 0.0, out_samples, dtype="float32")
    return array


def slice_seconds(
    samples: np.ndarray, sample_rate: int, start: float, length: float
) -> np.ndarray:
    """Take ``length`` seconds from ``start`` (clamped to the buffer)."""
    array = np.asarray(samples, dtype="float32")
    if sample_rate <= 0 or array.size == 0 or length <= 0:
        return np.zeros(0, dtype="float32")
    begin = max(0, int(round(start * sample_rate)))
    count = max(0, int(round(length * sample_rate)))
    return array[begin : begin + count]


def loop_or_trim(
    samples: np.ndarray, sample_rate: int, target_seconds: float
) -> np.ndarray:
    """Repeat or trim a buffer so it lasts exactly ``target_seconds``."""
    if sample_rate <= 0 or target_seconds <= 0:
        return np.zeros(0, dtype="float32")
    target = max(1, int(round(target_seconds * sample_rate)))
    array = np.asarray(samples, dtype="float32")
    if array.size == 0:
        return np.zeros(target, dtype="float32")
    if array.size >= target:
        return array[:target]
    repeats = int(np.ceil(target / array.size))
    return np.tile(array, repeats)[:target]


def mix_tracks(
    base: np.ndarray, overlay: np.ndarray, *, gain_db: float = 0.0
) -> np.ndarray:
    """Mix an overlay track onto a base track of the same length."""
    first = np.asarray(base, dtype="float32")
    second = np.asarray(overlay, dtype="float32")
    if first.size == 0:
        return second
    if second.size == 0:
        return first
    length = min(first.size, second.size)
    mixed = first[:length] + apply_gain(second[:length], gain_db)
    if first.size > length:
        mixed = np.concatenate([mixed, first[length:]])
    return mixed.astype("float32")


def duck_gain_for_overlay(gain_db: float) -> float:
    """Gain to apply to the music when it sits under speech.

    Values passed in are already negative; the clamp keeps the bed audible but
    never louder than -12 dB so speech stays intelligible.
    """
    return float(min(-12.0, max(-30.0, gain_db)))


def normalize_peak(samples: np.ndarray, *, target_dbfs: float = -1.0) -> np.ndarray:
    """Scale a buffer so its peak sits at ``target_dbfs`` (no-op if silent)."""
    array = np.asarray(samples, dtype="float32")
    current = peak_dbfs(array)
    if current == float("-inf"):
        return array
    return apply_gain(array, target_dbfs - current)


@dataclass
class MusicMixReport:
    """Summary of what the music mixer did, used for logging and the UI."""

    applied: bool
    preset_key: str = "none"
    intro_seconds: float = 0.0
    outro_seconds: float = 0.0
    underlay_seconds: float = 0.0
    gain_db: float = 0.0
    reason: str = ""


# ─────────────────────────────────────────────
#  FEATURE 5: music bed generation
# ─────────────────────────────────────────────
def music_cache_path(preset_key: str) -> Any:
    """Where the generated bed for a preset is cached."""
    return config.MUSIC_DIR / f"{preset_key}.mp3"


def build_elevenlabs_music_client(api_key: str = "") -> Any:
    """Create an ElevenLabs client for music generation."""
    if not api_key:
        raise ConfigurationError(
            "An ElevenLabs API key is required to generate background music.",
            hint="Add the key in the sidebar or upload your own music file instead.",
        )
    try:
        from elevenlabs import ElevenLabs
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ConfigurationError(
            "The 'elevenlabs' package is required for music generation.",
            hint="Install it with: pip install elevenlabs",
        ) from exc
    return ElevenLabs(api_key=api_key)


def build_music_bed(
    preset: Any,
    *,
    client: Any = None,
    api_key: str = "",
    length_ms: int = config.MUSIC_DEFAULT_LENGTH_MS,
    use_cache: bool = True,
    attempts: Optional[int] = None,
) -> Optional[bytes]:
    """Generate (or load from cache) the instrumental bed for a preset.

    Args:
        preset: A :class:`podcast.config.MusicPreset`.
        client: Injected ElevenLabs client.
        api_key: Key used when ``client`` is not given.
        length_ms: Requested music length in milliseconds.
        use_cache: Reuse a previously generated bed for the same preset.

    Returns:
        MP3 bytes, or ``None`` when the preset requests no music.
    """
    if not preset or preset.key == "none" or not preset.prompt:
        return None

    cache_file = music_cache_path(preset.key)
    if use_cache and cache_file.exists():
        cached = cache_file.read_bytes()
        if cached:
            LOGGER.info("Using cached music bed for preset '%s'", preset.key)
            return cached

    eleven = client or build_elevenlabs_music_client(api_key)
    requested_ms = max(5_000, min(int(length_ms), config.MUSIC_MAX_LENGTH_MS))

    def _compose() -> Any:
        return eleven.music.compose(
            prompt=preset.prompt,
            music_length_ms=requested_ms,
            model_id="music_v1",
            force_instrumental=True,
        )

    try:
        stream = retry_call(
            _compose,
            attempts=attempts if attempts and attempts > 0 else config.MAX_RETRIES,
            description=f"music bed ({preset.key})",
            logger=LOGGER,
        )
        if isinstance(stream, (bytes, bytearray)):
            audio = bytes(stream)
        else:
            audio = b"".join(chunk for chunk in stream if chunk)
    except Exception as exc:
        raise classify_exception(exc, stage="audio") from exc

    if not audio:
        raise AudioProcessingError(
            f"The music service returned no audio for '{preset.label}'.",
            hint="Try another music preset, or upload your own music file.",
        )

    if use_cache:
        try:
            config.MUSIC_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(audio)
            LOGGER.info("Cached music bed for preset '%s'", preset.key)
        except OSError as exc:  # pragma: no cover - read-only filesystem
            LOGGER.warning("Could not cache music bed: %s", exc)

    LOGGER.info(
        "Generated music bed for preset '%s' (%d bytes)", preset.key, len(audio)
    )
    return audio


# ─────────────────────────────────────────────
#  FEATURE 5: mix narration + music
# ─────────────────────────────────────────────
def apply_music_preset(
    narration: bytes,
    preset: Any,
    *,
    music: Optional[bytes] = None,
    sample_rate: int = config.MIX_SAMPLE_RATE,
) -> Tuple[bytes, MusicMixReport]:
    """Wrap narration with the intro, underlay and outro of a music preset.

    Args:
        narration: Narration MP3 bytes.
        preset: A :class:`podcast.config.MusicPreset`.
        music: Music bed bytes. When omitted and the preset needs music, the
            narration is returned untouched with an explanatory report.
        sample_rate: Working sample rate for the mix.

    Returns:
        ``(audio_bytes, report)`` - the audio is always usable, even when the
        music could not be applied.
    """
    if not preset or preset.key == "none":
        return narration, MusicMixReport(applied=False, reason="no music requested")
    if not music:
        return narration, MusicMixReport(
            applied=False, reason="music bed unavailable; narration left untouched"
        )

    try:
        speech = decode_audio(narration, target_rate=sample_rate)
        bed = decode_audio(music, target_rate=sample_rate)
    except AudioProcessingError as exc:
        LOGGER.warning("Music mixing skipped: %s", exc.message)
        return narration, MusicMixReport(applied=False, reason=exc.message)

    intro_seconds = max(0.0, float(preset.intro_seconds))
    outro_seconds = max(0.0, float(preset.outro_seconds))
    fade_seconds = max(0.05, float(preset.fade_seconds))
    gain_db = duck_gain_for_overlay(preset.underlay_gain_db)

    speech_samples = speech.samples
    bed_samples = bed.samples

    if preset.underlay:
        underlay = loop_or_trim(bed_samples, sample_rate, speech.duration)
        underlay = fade(
            underlay, sample_rate, fade_in=min(fade_seconds, speech.duration / 2)
        )
        speech_samples = mix_tracks(speech_samples, underlay, gain_db=gain_db)

    segments = []
    if intro_seconds > 0:
        intro = slice_seconds(bed_samples, sample_rate, 0.0, intro_seconds)
        segments.append(fade(intro, sample_rate, fade_out=fade_seconds))
    segments.append(speech_samples)
    if outro_seconds > 0:
        start = max(0.0, bed.duration - outro_seconds)
        outro = slice_seconds(bed_samples, sample_rate, start, outro_seconds)
        segments.append(fade(outro, sample_rate, fade_in=fade_seconds))

    combined = (
        np.concatenate([segment for segment in segments if segment.size])
        if segments
        else speech_samples
    )
    combined = normalize_peak(combined, target_dbfs=-1.0)

    try:
        audio = encode_mp3(AudioBuffer(samples=combined, sample_rate=sample_rate))
    except AudioProcessingError as exc:
        LOGGER.warning("Music mixing failed at encode step: %s", exc.message)
        return narration, MusicMixReport(applied=False, reason=exc.message)

    report = MusicMixReport(
        applied=True,
        intro_seconds=intro_seconds if intro_seconds > 0 else 0.0,
        outro_seconds=outro_seconds if outro_seconds > 0 else 0.0,
        underlay_seconds=speech.duration if preset.underlay else 0.0,
        gain_db=gain_db if preset.underlay else 0.0,
        reason=f"{preset.label} applied",
    )
    LOGGER.info(
        "Music applied (%s): intro=%.1fs outro=%.1fs underlay=%.1fs",
        preset.underlay and "with underlay" or "stings only",
        report.intro_seconds,
        report.outro_seconds,
        report.underlay_seconds,
    )
    return audio, report
