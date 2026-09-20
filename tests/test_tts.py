"""Tests for text-to-speech synthesis (Features 3 and 4)."""

from __future__ import annotations

import pytest

from podcast import config
from podcast.errors import (
    AuthenticationError,
    ConfigurationError,
    SpeechSynthesisError,
)
from podcast.models import DialogueSegment, Host, PodcastScript
from podcast.script import parse_script
from podcast.tts import (
    DIALOGUE_MAX_CHARS,
    SynthesisResult,
    plan_dialogue_batches,
    synthesize,
    synthesize_dialogue,
    synthesize_segments_individually,
    synthesize_solo,
)

HOSTS = [
    Host(name="Rachel", voice_id="voice-rachel"),
    Host(name="Adam", voice_id="voice-adam"),
]
DIALOGUE_RAW = (
    "Rachel: Welcome back to the show.\n"
    "Adam: Thanks for having me.\n"
    "Rachel: Let's dig into the article.\n"
    "Adam: Absolutely, there is a lot here.\n"
)


class FakeSpeech:
    """Records single-voice synthesis calls."""

    def __init__(self, payload: bytes = b"MP3-CHUNK", error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def convert(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return iter([self.payload])


class FakeDialogue:
    """Records multi-speaker synthesis calls."""

    def __init__(self, payload: bytes = b"MP3-DIALOGUE", error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def convert(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return iter([self.payload])


class FakeElevenLabs:
    """Minimal ElevenLabs client exposing both synthesis endpoints."""

    def __init__(self, speech=None, dialogue=None):
        self.text_to_speech = speech or FakeSpeech()
        self.text_to_dialogue = dialogue or FakeDialogue()


def solo_script(text: str = "This is the narration.") -> PodcastScript:
    """Build a single-speaker script."""
    return parse_script(text, HOSTS[:1], style_key="solo")


def dialogue_script() -> PodcastScript:
    """Build a two-speaker script."""
    return parse_script(DIALOGUE_RAW, HOSTS, style_key="dialogue")


class TestBuildClient:
    """Key validation must fail loudly, before any network call."""

    def test_missing_key_raises_configuration_error(self):
        from podcast.tts import build_elevenlabs_client

        with pytest.raises(ConfigurationError) as exc:
            build_elevenlabs_client("")
        assert exc.value.hint

    def test_client_is_created_from_a_key(self):
        from podcast.tts import build_elevenlabs_client

        client = build_elevenlabs_client("sk_test_key")
        assert client is not None


class TestSynthesizeSolo:
    """Solo narration, including long-text chunking."""

    def test_single_chunk_request(self):
        client = FakeElevenLabs()
        audio = synthesize_solo("Short narration.", client=client)
        assert audio == b"MP3-CHUNK"
        assert len(client.text_to_speech.calls) == 1
        call = client.text_to_speech.calls[0]
        assert call["text"] == "Short narration."
        assert call["voice_id"] == config.DEFAULT_VOICE_ID
        assert call["model_id"] == config.TTS_MODEL_DEFAULT

    def test_long_text_is_chunked_and_concatenated(self, monkeypatch):
        monkeypatch.setattr(config, "TTS_CHUNK_CHARS", 20)
        client = FakeElevenLabs()
        long_text = "First sentence here. Second sentence here. Third sentence here."
        audio = synthesize_solo(long_text, client=client)
        assert len(client.text_to_speech.calls) > 1
        assert audio == b"MP3-CHUNK" * len(client.text_to_speech.calls)

    def test_language_code_is_forwarded(self):
        client = FakeElevenLabs()
        synthesize_solo("Hola mundo.", client=client, language_code="es")
        assert client.text_to_speech.calls[0]["language_code"] == "es"

    def test_empty_language_code_becomes_none(self):
        client = FakeElevenLabs()
        synthesize_solo("Hello.", client=client, language_code="")
        assert client.text_to_speech.calls[0]["language_code"] is None

    def test_empty_text_is_rejected(self):
        with pytest.raises(SpeechSynthesisError):
            synthesize_solo("   ", client=FakeElevenLabs())

    def test_provider_failure_is_typed(self, monkeypatch):
        monkeypatch.setattr(config, "TTS_MAX_RETRIES", 1)
        client = FakeElevenLabs(speech=FakeSpeech(error=RuntimeError("500 boom")))
        with pytest.raises(SpeechSynthesisError):
            synthesize_solo("Text.", client=client)

    def test_auth_failure_is_classified(self, monkeypatch):
        monkeypatch.setattr(config, "TTS_MAX_RETRIES", 1)
        client = FakeElevenLabs(
            speech=FakeSpeech(error=RuntimeError("401 unauthorized"))
        )
        with pytest.raises(AuthenticationError):
            synthesize_solo("Text.", client=client)

    def test_empty_audio_payload_is_rejected(self):
        client = FakeElevenLabs(speech=FakeSpeech(payload=b""))
        with pytest.raises(SpeechSynthesisError):
            synthesize_solo("Text.", client=client)


# ─────────────────────────────────────────────
#  FEATURE 4: multi-speaker dialogue synthesis
# ─────────────────────────────────────────────
class TestPlanDialogueBatches:
    """Batching keeps every provider request inside its documented limits."""

    def segments(self, texts):
        return [
            DialogueSegment(speaker="R", text=text, voice_id="v1") for text in texts
        ]

    def test_short_dialogue_is_one_batch(self):
        batches = plan_dialogue_batches(self.segments(["a", "b", "c"]))
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_char_limit_splits_batches(self):
        long_text = "x" * 1000
        batches = plan_dialogue_batches(
            self.segments([long_text, long_text, long_text])
        )
        assert len(batches) == 3
        assert all(
            sum(len(seg.text) for seg in batch) <= DIALOGUE_MAX_CHARS
            for batch in batches
        )

    def test_speaker_limit_splits_batches(self):
        segments = [
            DialogueSegment(speaker=f"S{index}", text="hi", voice_id=f"v{index}")
            for index in range(12)
        ]
        batches = plan_dialogue_batches(segments)
        assert len(batches) == 2
        assert len({seg.voice_id for seg in batches[0]}) <= 10

    def test_blank_segments_are_skipped(self):
        batches = plan_dialogue_batches(self.segments(["a", "   ", "b"]))
        assert len(batches[0]) == 2

    def test_empty_input_yields_no_batches(self):
        assert plan_dialogue_batches([]) == []


class TestSynthesizeDialogue:
    """Native multi-speaker synthesis (Feature 4)."""

    def test_sends_dialogue_inputs_with_voice_ids(self):
        client = FakeElevenLabs()
        audio = synthesize_dialogue(dialogue_script().segments, client=client)

        assert audio == b"MP3-DIALOGUE"
        inputs = client.text_to_dialogue.calls[0]["inputs"]
        assert len(inputs) == 4
        assert inputs[0].voice_id == "voice-rachel"
        assert inputs[1].voice_id == "voice-adam"
        assert inputs[1].text == "Thanks for having me."

    def test_language_code_and_model_are_forwarded(self):
        client = FakeElevenLabs()
        synthesize_dialogue(
            dialogue_script().segments, client=client, language_code="es", model_id="m1"
        )
        call = client.text_to_dialogue.calls[0]
        assert call["language_code"] == "es"
        assert call["model_id"] == "m1"

    def test_empty_segments_are_rejected(self):
        with pytest.raises(SpeechSynthesisError):
            synthesize_dialogue([], client=FakeElevenLabs())


class TestSynthesizeSegmentsIndividually:
    """Fallback path used when multi-speaker synthesis is unavailable."""

    def test_each_turn_uses_its_own_voice(self):
        client = FakeElevenLabs()
        synthesize_segments_individually(dialogue_script().segments, client=client)

        voices = [call["voice_id"] for call in client.text_to_speech.calls]
        assert voices == ["voice-rachel", "voice-adam", "voice-rachel", "voice-adam"]

    def test_audio_is_concatenated(self):
        client = FakeElevenLabs()
        audio = synthesize_segments_individually(
            dialogue_script().segments, client=client
        )
        assert audio == b"MP3-CHUNK" * 4

    def test_no_usable_segments_raises(self):
        with pytest.raises(SpeechSynthesisError):
            synthesize_segments_individually([], client=FakeElevenLabs())


class TestSynthesizeDispatcher:
    """The dispatcher picks the right strategy for the script shape."""

    def test_solo_script_uses_one_voice(self):
        client = FakeElevenLabs()
        result = synthesize(solo_script(), client=client)
        assert isinstance(result, SynthesisResult)
        assert result.used_dialogue_api is False
        assert result.fallback_reason == ""
        assert client.text_to_speech.calls[0]["voice_id"] == "voice-rachel"

    def test_english_solo_uses_turbo_model(self):
        client = FakeElevenLabs()
        result = synthesize(solo_script(), client=client, language_code="en")
        assert result.model_id == config.TTS_MODEL_DEFAULT

    def test_non_english_uses_multilingual_model(self):
        client = FakeElevenLabs()
        result = synthesize(solo_script(), client=client, language_code="es")
        assert result.model_id == config.TTS_MODEL_MULTILINGUAL
        assert client.text_to_speech.calls[0]["language_code"] == "es"

    def test_language_defaults_to_script_language(self):
        client = FakeElevenLabs()
        script = parse_script("Narration.", HOSTS[:1], language="fr", style_key="solo")
        result = synthesize(script, client=client)
        assert result.model_id == config.TTS_MODEL_MULTILINGUAL

    def test_dialogue_script_uses_dialogue_endpoint(self):
        client = FakeElevenLabs()
        result = synthesize(dialogue_script(), client=client)
        assert result.used_dialogue_api is True
        assert result.segment_count == 4
        assert len(client.text_to_dialogue.calls) == 1
        assert client.text_to_speech.calls == []

    def test_dialogue_falls_back_when_endpoint_fails(self, monkeypatch):
        monkeypatch.setattr(config, "TTS_MAX_RETRIES", 1)
        client = FakeElevenLabs(
            dialogue=FakeDialogue(error=RuntimeError("400 dialogue not enabled"))
        )
        result = synthesize(dialogue_script(), client=client)
        assert result.used_dialogue_api is False
        assert "dialogue not enabled" in result.fallback_reason
        assert len(client.text_to_speech.calls) == 4

    def test_dialogue_auth_error_is_not_swallowed(self, monkeypatch):
        monkeypatch.setattr(config, "TTS_MAX_RETRIES", 1)
        client = FakeElevenLabs(
            dialogue=FakeDialogue(error=RuntimeError("401 invalid_api_key"))
        )
        with pytest.raises(AuthenticationError):
            synthesize(dialogue_script(), client=client)

    def test_dialogue_api_can_be_disabled_explicitly(self):
        client = FakeElevenLabs()
        result = synthesize(dialogue_script(), client=client, use_dialogue_api=False)
        assert result.used_dialogue_api is False
        assert "disabled" in result.fallback_reason
        assert client.text_to_dialogue.calls == []

    def test_solo_script_without_segments_is_rejected(self):
        with pytest.raises(SpeechSynthesisError):
            synthesize(PodcastScript(segments=[]), client=FakeElevenLabs())
