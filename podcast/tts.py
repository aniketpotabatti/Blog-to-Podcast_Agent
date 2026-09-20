"""
Text-to-speech synthesis: single narrator and multi-speaker dialogue.
===================================================================

Feature 3 - Multilingual support
    ``language_code`` is forwarded to ElevenLabs and the model is switched to
    ``eleven_multilingual_v2`` for non-English episodes.

Feature 4 - Multi-host dialogue
    Dialogue scripts are rendered with ElevenLabs' native ``text_to_dialogue``
    endpoint so each host keeps their own voice. If that endpoint is
    unavailable (plan/permissions), synthesis falls back to rendering each
    segment separately and concatenating the audio.

Long scripts are chunked on sentence boundaries and the resulting MP3 parts
are concatenated, which keeps every request inside provider limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from podcast import config
from podcast.errors import (
    ConfigurationError,
    SpeechSynthesisError,
    classify_exception,
)
from podcast.models import DialogueSegment, PodcastScript
from podcast.utils import chunk_text, get_logger, retry_call

LOGGER = get_logger("tts")

# ElevenLabs limits per dialogue request (kept conservative on purpose).
DIALOGUE_MAX_CHARS = 1900
DIALOGUE_MAX_SPEAKERS = 10


@dataclass
class SynthesisResult:
    """Audio produced for one script, plus how it was produced."""

    audio: bytes
    model_id: str
    chunks: int = 1
    used_dialogue_api: bool = False
    fallback_reason: str = ""
    segment_count: int = 0


def build_elevenlabs_client(api_key: str) -> Any:
    """Create an ElevenLabs client, validating that a key was supplied."""
    if not api_key:
        raise ConfigurationError(
            "An ElevenLabs API key is required for voice synthesis.",
            hint="Add the key in the sidebar or set ELEVENLABS_API_KEY.",
        )
    try:
        from elevenlabs import ElevenLabs
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ConfigurationError(
            "The 'elevenlabs' package is required for voice synthesis.",
            hint="Install it with: pip install elevenlabs",
        ) from exc
    return ElevenLabs(api_key=api_key)


def _to_bytes(stream: Any) -> bytes:
    """Normalise an SDK response (iterator or bytes) into raw bytes."""
    if stream is None:
        return b""
    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream)
    try:
        return b"".join(chunk for chunk in stream if chunk)
    except TypeError as exc:  # pragma: no cover - unexpected payload type
        raise SpeechSynthesisError(
            "Unexpected audio payload returned by the provider.",
            hint="Check the ElevenLabs SDK version (>=1.0) is installed.",
        ) from exc


def _call_with_retries(
    func: Any,
    *,
    label: str,
    attempts: Optional[int] = None,
) -> bytes:
    """Run a synthesis call with retries, mapping failures to typed errors."""
    try:
        # We still use retry_call directly here because we need to wrap the
        # SDK response normalization in the same retry loop.
        stream = retry_call(
            func,
            attempts=attempts if attempts and attempts > 0 else config.TTS_MAX_RETRIES,
            description=label,
            logger=LOGGER,
        )
    except ConfigurationError:
        raise
    except Exception as exc:
        raise classify_exception(exc, stage="speech") from exc

    audio = _to_bytes(stream)
    if not audio:
        raise SpeechSynthesisError(
            f"The provider returned empty audio for {label}.",
            hint="Try again, or shorten the script if the problem repeats.",
        )
    return audio


# ─────────────────────────────────────────────
#  Single-voice synthesis (solo narration)
# ─────────────────────────────────────────────
def synthesize_solo(
    text: str,
    *,
    voice_id: str = config.DEFAULT_VOICE_ID,
    client: Any = None,
    api_key: str = "",
    model_id: str = config.TTS_MODEL_DEFAULT,
    output_format: str = config.TTS_OUTPUT_FORMAT,
    language_code: str = "",
    attempts: Optional[int] = None,
) -> bytes:
    """Synthesise narration with one voice, chunking long text.

    Args:
        text: Narration to speak.
        voice_id: ElevenLabs voice id.
        client: Injected ElevenLabs client (created from ``api_key`` if omitted).
        language_code: ISO-639-1 code forwarded to the provider (Feature 3).
        attempts: Optional retry budget override.

    Returns:
        Concatenated MP3 bytes.
    """
    if not (text or "").strip():
        raise SpeechSynthesisError(
            "There is no narration text to synthesize.",
            hint="Generate a script before requesting audio.",
        )

    eleven = client or build_elevenlabs_client(api_key)
    chunks = chunk_text(text, config.TTS_CHUNK_CHARS)
    parts: List[bytes] = []

    for index, chunk in enumerate(chunks, start=1):
        label = f"tts chunk {index}/{len(chunks)}"

        def _convert(chunk_text_value: str = chunk) -> Any:
            return eleven.text_to_speech.convert(
                voice_id=voice_id,
                text=chunk_text_value,
                model_id=model_id,
                output_format=output_format,
                language_code=language_code or None,
            )

        parts.append(_call_with_retries(_convert, label=label, attempts=attempts))

    LOGGER.info(
        "Synthesized narration: voice=%s, %d chunk(s), %d bytes",
        voice_id,
        len(chunks),
        sum(len(part) for part in parts),
    )
    return b"".join(parts)


# ─────────────────────────────────────────────
#  FEATURE 4: multi-speaker dialogue synthesis
# ─────────────────────────────────────────────
def plan_dialogue_batches(
    segments: Sequence[DialogueSegment],
    *,
    max_chars: int = DIALOGUE_MAX_CHARS,
    max_speakers: int = DIALOGUE_MAX_SPEAKERS,
) -> List[List[DialogueSegment]]:
    """Split dialogue segments into batches that respect provider limits.

    Batches keep consecutive turns together so the conversation still flows.
    """
    batches: List[List[DialogueSegment]] = []
    current: List[DialogueSegment] = []
    current_chars = 0
    current_speakers: set = set()

    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        segment_chars = len(text)
        speakers = current_speakers | {segment.voice_id}
        too_long = current and (current_chars + segment_chars > max_chars)
        too_many = current and len(speakers) > max_speakers
        if too_long or too_many:
            batches.append(current)
            current, current_chars, current_speakers = [], 0, set()
        current.append(segment)
        current_chars += segment_chars
        current_speakers.add(segment.voice_id)

    if current:
        batches.append(current)
    return batches


def synthesize_dialogue(
    segments: Sequence[DialogueSegment],
    *,
    client: Any = None,
    api_key: str = "",
    model_id: str = config.TTS_MODEL_MULTILINGUAL,
    output_format: str = config.TTS_OUTPUT_FORMAT,
    language_code: str = "",
    attempts: Optional[int] = None,
) -> bytes:
    """Synthesize a dialogue with a distinct voice per speaker.

    Uses ElevenLabs' native multi-speaker endpoint, batching long conversations
    so every request stays within the provider's limits.
    """
    eleven = client or build_elevenlabs_client(api_key)
    batches = plan_dialogue_batches(segments)
    if not batches:
        raise SpeechSynthesisError(
            "There are no dialogue lines to synthesize.",
            hint="Generate a script before requesting audio.",
        )

    from elevenlabs.types.dialogue_input import DialogueInput

    parts: List[bytes] = []
    for index, batch in enumerate(batches, start=1):
        inputs = [
            DialogueInput(text=segment.text.strip(), voice_id=segment.voice_id)
            for segment in batch
        ]
        label = f"dialogue batch {index}/{len(batches)}"

        def _convert(_inputs: List[Any] = inputs, _label: str = label) -> Any:
            return eleven.text_to_dialogue.convert(
                inputs=_inputs,
                model_id=model_id,
                output_format=output_format,
                language_code=language_code or None,
            )

        parts.append(_call_with_retries(_convert, label=label, attempts=attempts))

    LOGGER.info(
        "Synthesized dialogue: %d segment(s) in %d batch(es)",
        len(segments),
        len(batches),
    )
    return b"".join(parts)


def synthesize_segments_individually(
    segments: Sequence[DialogueSegment],
    *,
    client: Any = None,
    api_key: str = "",
    model_id: str = config.TTS_MODEL_MULTILINGUAL,
    output_format: str = config.TTS_OUTPUT_FORMAT,
    language_code: str = "",
    attempts: Optional[int] = None,
) -> bytes:
    """Fallback: render each turn with its own voice and concatenate.

    Used when the multi-speaker endpoint is unavailable on the account tier.
    """
    eleven = client or build_elevenlabs_client(api_key)
    parts: List[bytes] = []
    for index, segment in enumerate(segments, start=1):
        if not (segment.text or "").strip():
            continue
        label = f"segment {index}/{len(segments)}"

        def _convert(_segment: DialogueSegment = segment, _label: str = label) -> Any:
            return eleven.text_to_speech.convert(
                voice_id=_segment.voice_id,
                text=_segment.text.strip(),
                model_id=model_id,
                output_format=output_format,
                language_code=language_code or None,
            )

        parts.append(_call_with_retries(_convert, label=label, attempts=attempts))

    if not parts:
        raise SpeechSynthesisError(
            "There was no dialogue audio to synthesize.",
            hint="Generate a script before requesting audio.",
        )
    LOGGER.info("Synthesized %d segment(s) with the per-segment fallback", len(parts))
    return b"".join(parts)


def synthesize(
    script: PodcastScript,
    *,
    client: Any = None,
    api_key: str = "",
    voice_id: str = config.DEFAULT_VOICE_ID,
    language_code: str = "",
    use_dialogue_api: bool = True,
    attempts: Optional[int] = None,
) -> SynthesisResult:
    """Synthesize a whole script, choosing the right strategy automatically.

    * Solo scripts (or scripts that collapsed to one speaker) use one voice.
    * Multi-speaker scripts use the native dialogue endpoint, falling back to
      per-segment synthesis when that call fails for a non-authentication
      reason.

    Args:
        script: Parsed podcast script.
        client: Injected ElevenLabs client.
        api_key: API key used when ``client`` is not supplied.
        voice_id: Voice for solo narration.
        language_code: ISO-639-1 narration language (Feature 3).
        use_dialogue_api: Set to ``False`` to force per-segment synthesis.
        attempts: Optional retry budget override.

    Returns:
        A :class:`SynthesisResult` carrying the audio and provenance details.
    """
    lang_code = language_code or script.language or "en"
    model_id = config.resolve_tts_model(lang_code)
    eleven = client or build_elevenlabs_client(api_key)
    segments = [segment for segment in script.segments if (segment.text or "").strip()]

    if not segments:
        raise SpeechSynthesisError(
            "The script has no spoken content to synthesize.",
            hint="Regenerate the script and try again.",
        )

    if not script.is_dialogue:
        text = segments[0].text if len(segments) == 1 else script.narration_text
        resolved_voice = segments[0].voice_id or voice_id
        audio = synthesize_solo(
            text,
            voice_id=resolved_voice,
            client=eleven,
            model_id=model_id,
            language_code=lang_code,
            attempts=attempts,
        )
        return SynthesisResult(
            audio=audio,
            model_id=model_id,
            chunks=len(chunk_text(text, config.TTS_CHUNK_CHARS)),
            segment_count=len(segments),
        )

    if use_dialogue_api:
        try:
            audio = synthesize_dialogue(
                segments,
                client=eleven,
                model_id=model_id,
                language_code=lang_code,
                attempts=attempts,
            )
            return SynthesisResult(
                audio=audio,
                model_id=model_id,
                chunks=len(plan_dialogue_batches(segments)),
                used_dialogue_api=True,
                segment_count=len(segments),
            )
        except SpeechSynthesisError as exc:
            from podcast.errors import AuthenticationError

            if isinstance(exc, AuthenticationError):
                raise
            LOGGER.warning(
                "Multi-speaker endpoint unavailable (%s); using per-segment synthesis.",
                exc.message,
            )
            fallback_reason = exc.message
    else:
        fallback_reason = "multi-speaker synthesis disabled by configuration"

    audio = synthesize_segments_individually(
        segments,
        client=eleven,
        model_id=model_id,
        language_code=lang_code,
        attempts=attempts,
    )
    return SynthesisResult(
        audio=audio,
        model_id=model_id,
        chunks=len(segments),
        used_dialogue_api=False,
        fallback_reason=fallback_reason,
        segment_count=len(segments),
    )
