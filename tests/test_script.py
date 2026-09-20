"""Tests for script writing: multilingual, dialogue and episode metadata."""

from __future__ import annotations

import pytest

from podcast import config
from podcast.config import resolve_hosts
from podcast.errors import ScriptGenerationError
from podcast.models import Article, Host, SourceKind
from podcast.script import (
    build_metadata_prompt,
    build_script_prompt,
    fallback_metadata,
    generate_metadata,
    generate_script,
    metadata_from_raw,
    parse_script,
)

HOSTS = [
    Host(name="Rachel", voice_id="voice-rachel"),
    Host(name="Adam", voice_id="voice-adam"),
]


def article(
    title: str = "How AI Changes Software Teams", kind: SourceKind = SourceKind.URL
) -> Article:
    """Sample article used across the script tests."""
    return Article(
        text="Artificial intelligence is reshaping how teams ship software. " * 10,
        title=title,
        url="https://example.com/ai-teams",
        kind=kind,
    )


class TestResolveHosts:
    """Host resolution guarantees distinct voices for dialogue styles."""

    def test_solo_style_yields_one_host(self):
        assert len(resolve_hosts("solo")) == 1

    def test_dialogue_style_yields_two_distinct_voices(self):
        hosts = resolve_hosts("dialogue")
        assert len(hosts) == 2
        assert hosts[0].voice_id != hosts[1].voice_id

    def test_supplied_hosts_are_kept(self):
        hosts = resolve_hosts("dialogue", HOSTS)
        assert [host.name for host in hosts] == ["Rachel", "Adam"]

    def test_solo_style_truncates_extra_hosts(self):
        assert len(resolve_hosts("solo", HOSTS)) == 1

    def test_missing_second_host_is_padded_with_distinct_voice(self):
        hosts = resolve_hosts("dialogue", [HOSTS[0]])
        assert len(hosts) == 2
        assert hosts[1].voice_id != hosts[0].voice_id

    def test_hosts_without_voice_ids_are_ignored(self):
        hosts = resolve_hosts("dialogue", [Host(name="Ghost", voice_id="")])
        assert all(host.voice_id for host in hosts)


class TestBuildScriptPrompt:
    """The prompt is where features 3 and 4 are enforced."""

    def test_language_is_requested(self):
        prompt = build_script_prompt(article(), language="es")
        assert "Spanish" in prompt
        assert "es" in prompt

    def test_dialogue_prompt_lists_hosts_and_format(self):
        prompt = build_script_prompt(article(), style_key="dialogue", hosts=HOSTS)
        assert "Rachel: <what Rachel says>" in prompt
        assert "Adam: <what Adam says>" in prompt
        assert "OUTPUT FORMAT (strict)" in prompt

    def test_solo_prompt_forbids_speaker_labels(self):
        prompt = build_script_prompt(article(), style_key="solo")
        assert "plain prose" in prompt
        assert "Rachel:" not in prompt

    def test_style_guidance_and_length_are_included(self):
        prompt = build_script_prompt(article(), style_key="news_brief", max_words=200)
        assert "news brief" in prompt.lower()
        assert "at most 200 words" in prompt

    def test_source_title_and_body_are_included(self):
        prompt = build_script_prompt(article())
        assert "How AI Changes Software Teams" in prompt
        assert "Artificial intelligence" in prompt

    def test_very_long_articles_are_truncated(self):
        long_article = Article(text="word " * 6000)
        prompt = build_script_prompt(long_article, max_words=300)
        assert " ..." in prompt
        assert len(prompt) < 30_000


# ─────────────────────────────────────────────
#  FEATURE 4: multi-host dialogue parsing
# ─────────────────────────────────────────────
DIALOGUE_RAW = """Rachel: Welcome back to the show.
We are looking at how AI changes software teams.

Adam: And it is a big shift, isn't it?
Rachel: It really is. Let's get into it.
Adam: First up, productivity gains.

Some trailing narration that continues Adam's point.
"""


class TestParseScriptDialogue:
    """Dialogue parsing must bind every turn to the right host voice."""

    def test_parses_turns_and_assigns_voices(self):
        script = parse_script(DIALOGUE_RAW, HOSTS, style_key="dialogue")
        assert script.is_dialogue is True
        assert script.segments[0].speaker == "Rachel"
        assert script.segments[0].voice_id == "voice-rachel"
        assert script.segments[1].speaker == "Adam"
        assert script.segments[1].voice_id == "voice-adam"

    def test_continuation_lines_are_merged(self):
        script = parse_script(DIALOGUE_RAW, HOSTS, style_key="dialogue")
        assert "Welcome back to the show. We are looking at" in script.segments[0].text
        assert script.segments[-1].text.endswith("continues Adam's point.")

    def test_bold_labels_are_supported(self):
        raw = "**Rachel:** Hello there.\n**Adam:** Hi Rachel."
        script = parse_script(raw, HOSTS, style_key="dialogue")
        assert [segment.speaker for segment in script.segments] == ["Rachel", "Adam"]

    def test_first_name_labels_are_matched(self):
        raw = "Adam Smith: One point.\nRachel Jones: Another point."
        script = parse_script(raw, HOSTS, style_key="dialogue")
        assert [segment.speaker for segment in script.segments] == ["Adam", "Rachel"]

    def test_unlabelled_text_degrades_to_single_speaker(self):
        script = parse_script(
            "Just some narration without labels.", HOSTS, style_key="dialogue"
        )
        assert script.is_dialogue is False
        assert len(script.segments) == 1

    def test_unknown_speaker_is_appended_not_dropped(self):
        raw = "Rachel: Hello.\nNarrator: Meanwhile, things changed."
        script = parse_script(raw, HOSTS, style_key="dialogue")
        assert len(script.segments) == 1
        assert "Meanwhile, things changed." in script.segments[0].text

    def test_script_text_renders_speakers(self):
        script = parse_script(DIALOGUE_RAW, HOSTS, style_key="dialogue")
        assert "Rachel: Welcome back" in script.text

    def test_characters_and_duration_are_computed(self):
        script = parse_script(DIALOGUE_RAW, HOSTS, style_key="dialogue")
        assert script.characters > 0
        assert script.estimated_speech_seconds >= 1


class TestParseScriptSolo:
    """Solo narration keeps the text verbatim and strips stray labels."""

    def test_single_narrator_returns_one_segment(self):
        script = parse_script("This is the narration.", HOSTS[:1], style_key="solo")
        assert len(script.segments) == 1
        assert script.is_dialogue is False
        assert script.segments[0].voice_id == "voice-rachel"

    def test_leading_speaker_label_is_stripped(self):
        script = parse_script(
            "George: Welcome to the show.", HOSTS[:1], style_key="solo"
        )
        assert script.segments[0].text == "Welcome to the show."

    def test_language_and_style_are_recorded(self):
        script = parse_script("Text.", HOSTS[:1], language="fr", style_key="solo")
        assert script.language == "fr"
        assert script.style == "solo"

    def test_empty_output_raises(self):
        with pytest.raises(ScriptGenerationError):
            parse_script("   ", HOSTS[:1], style_key="solo")

    def test_default_hosts_used_when_none_supplied(self):
        script = parse_script("Text.", [], style_key="solo")
        assert script.segments[0].voice_id == "21m00Tcm4TlvDq8ikWAM"


# ─────────────────────────────────────────────
#  Script generation with an injected LLM
# ─────────────────────────────────────────────
class TestGenerateScript:
    """The generator is injected, so no API key is needed to test the flow."""

    def test_dialogue_script_is_generated(self):
        script = generate_script(
            article(),
            style_key="dialogue",
            hosts=HOSTS,
            generator=lambda prompt: DIALOGUE_RAW,
        )
        assert script.style == "dialogue"
        assert script.is_dialogue is True

    def test_language_is_propagated_to_the_script(self):
        script = generate_script(
            article(),
            style_key="solo",
            language="de",
            generator=lambda prompt: "Ein kurzer Monolog.",
        )
        assert script.language == "de"

    def test_prompt_is_passed_to_the_generator(self):
        captured = {}

        def generator(prompt):
            captured["prompt"] = prompt
            return "Narration."

        generate_script(article(), language="ja", generator=generator)
        assert "Japanese" in captured["prompt"]

    def test_empty_model_output_raises(self):
        with pytest.raises(ScriptGenerationError):
            generate_script(article(), generator=lambda prompt: "   ", attempts=1)

    def test_generator_failure_is_wrapped(self, monkeypatch):
        monkeypatch.setattr(config, "MAX_RETRIES", 1)

        def boom(prompt):
            raise RuntimeError("model overloaded")

        with pytest.raises(ScriptGenerationError):
            generate_script(article(), generator=boom)

    def test_missing_credentials_raise_configuration_error(self, monkeypatch):
        from podcast.errors import ConfigurationError

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(ConfigurationError):
            generate_script(article(), api_key="")


# ─────────────────────────────────────────────
#  FEATURE 6: automatic episode titles and descriptions
# ─────────────────────────────────────────────
class TestMetadataParsing:
    """Episode metadata must be produced even when the model misbehaves."""

    def test_fenced_json_is_parsed(self):
        raw = (
            "Here you go:\n```json\n"
            '{"title": "AI Reshapes Teams", "description": "A short look at AI.", '
            '"tags": ["ai", "teams", "software"]}\n```'
        )
        metadata = metadata_from_raw(raw, article())
        assert metadata.title == "AI Reshapes Teams"
        assert metadata.description == "A short look at AI."
        assert metadata.tags == ["ai", "teams", "software"]

    def test_tags_are_cleaned_and_capped(self):
        payload = (
            '{"title": "T", "description": "D", '
            '"tags": ["#AI ", "AI", "b", "c", "d", "e", "f", "g"]}'
        )
        metadata = metadata_from_raw(payload, article())
        assert "#" not in "".join(metadata.tags)
        assert metadata.tags[0] == "ai"
        assert len(metadata.tags) <= config.METADATA_MAX_TAGS

    def test_title_is_truncated_to_70_characters(self):
        payload = '{"title": "' + "x" * 120 + '", "description": "d", "tags": []}'
        assert len(metadata_from_raw(payload, article()).title) <= 70

    def test_description_is_truncated(self):
        payload = '{"title": "t", "description": "' + "y" * 500 + '", "tags": []}'
        assert len(metadata_from_raw(payload, article()).description) <= 350

    def test_unparseable_output_falls_back_to_article_title(self):
        metadata = metadata_from_raw("not json at all", article("Fallback Title"))
        assert metadata.title == "Fallback Title"
        assert metadata.description

    def test_missing_fields_fall_back_individually(self):
        metadata = metadata_from_raw('{"title": "Only Title"}', article("Source"))
        assert metadata.title == "Only Title"
        assert metadata.description  # generated from the article title

    def test_language_is_recorded(self):
        assert (
            metadata_from_raw('{"title": "t"}', article(), language="pt").language
            == "pt"
        )


class TestFallbackMetadata:
    """Fallbacks must always yield a publishable title."""

    def test_uses_article_title(self):
        assert fallback_metadata(article("My Article")).title == "My Article"

    def test_pdf_source_is_described_differently(self):
        pdf_meta = fallback_metadata(article("Paper", kind=SourceKind.PDF))
        url_meta = fallback_metadata(article("Post", kind=SourceKind.URL))
        assert "based on" in pdf_meta.description
        assert "AI-narrated" in url_meta.description

    def test_untitled_article_still_produces_a_title(self):
        assert fallback_metadata(Article(text="body")).title == "URL document"


class TestGenerateMetadata:
    """Metadata generation degrades gracefully instead of failing the run."""

    def test_generates_from_model_json(self, sample_article):
        script = parse_script("Narration text.", HOSTS[:1], style_key="solo")
        metadata = generate_metadata(
            sample_article,
            script,
            generator=lambda prompt: (
                '{"title": "T", "description": "D", "tags": ["x"]}'
            ),
        )
        assert metadata.title == "T"
        assert metadata.tags == ["x"]

    def test_prompt_requests_the_language(self, sample_article):
        script = parse_script("Narration.", HOSTS[:1], style_key="solo")
        prompt = build_metadata_prompt(sample_article, script, language="it")
        assert "Italian" in prompt

    def test_model_failure_falls_back_without_raising(
        self, sample_article, monkeypatch
    ):
        monkeypatch.setattr(config, "MAX_RETRIES", 1)
        script = parse_script("Narration.", HOSTS[:1], style_key="solo")

        def boom(prompt):
            raise RuntimeError("503 unavailable")

        metadata = generate_metadata(sample_article, script, generator=boom)
        assert metadata.title == sample_article.title
