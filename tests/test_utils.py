"""Tests for podcast.utils helper functions."""

from __future__ import annotations

import pytest

from podcast.errors import InputError
from podcast.utils import (
    chunk_text,
    clean_text,
    coerce_str_list,
    estimate_speech_seconds,
    format_bytes,
    is_pdf_url,
    looks_like_pdf,
    parse_json_object,
    retry_call,
    sanitize_filename,
    slugify,
    truncate_text,
    truncate_words,
    validate_url,
)


class TestValidateUrl:
    """URL validation guards the pipeline from wasted API calls."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://example.com/post", "https://example.com/post"),
            ("http://example.com", "http://example.com"),
            ("example.com/post", "https://example.com/post"),
        ],
    )
    def test_accepts_valid_urls(self, raw, expected):
        assert validate_url(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["", "   ", "not a url at all", "ftp://example.com"]
    )
    def test_rejects_invalid_urls(self, raw):
        with pytest.raises(InputError):
            validate_url(raw)

    def test_hint_is_actionable(self):
        with pytest.raises(InputError) as exc:
            validate_url("")
        assert exc.value.hint


class TestPdfDetection:
    """PDF detection drives the ingestion strategy choice."""

    def test_is_pdf_url(self):
        assert is_pdf_url("https://arxiv.org/pdf/2401.00001.pdf")
        assert is_pdf_url("https://example.com/paper.pdf")
        assert not is_pdf_url("https://example.com/blog")

    def test_looks_like_pdf(self):
        assert looks_like_pdf(b"%PDF-1.7 body")
        assert not looks_like_pdf(b"<html>")


class TestTextHelpers:
    """Text helpers keep narration clean and within provider limits."""

    def test_clean_text_collapses_whitespace(self):
        assert clean_text("a  \t b\n\n\n\nc") == "a b\n\nc"

    def test_truncate_text_on_word_boundary(self):
        result = truncate_text("the quick brown fox jumps", 15)
        assert len(result) <= 15
        assert not result.endswith("jumps")

    def test_truncate_text_noop_when_short(self):
        assert truncate_text("short", 100) == "short"

    def test_truncate_words(self):
        assert truncate_words("one two three", 2) == "one two ..."
        assert truncate_words("one two", 0) == "one two"

    def test_estimate_speech_seconds(self):
        assert estimate_speech_seconds("word " * 150) == 60
        assert estimate_speech_seconds("") == 0

    def test_slugify_strips_accents_and_symbols(self):
        assert slugify("Hello, World! 2026 - AI") == "hello-world-2026-ai"
        assert slugify("") == ""

    def test_sanitize_filename(self):
        assert sanitize_filename("My Episode!.mp3", extension="mp3") == "my-episode.mp3"
        assert sanitize_filename("", fallback="ep", extension="mp3") == "ep.mp3"

    def test_format_bytes(self):
        assert format_bytes(512) == "512 B"
        assert format_bytes(2048) == "2.0 KB"

    def test_coerce_str_list(self):
        assert coerce_str_list("a, b; c\nd") == ["a", "b", "c", "d"]
        assert coerce_str_list([" x ", ""], limit=1) == ["x"]
        assert coerce_str_list(None) == []


class TestChunkText:
    """Chunking keeps individual TTS requests under provider limits."""

    def test_short_text_is_single_chunk(self):
        assert chunk_text("hello world", 100) == ["hello world"]

    def test_empty_text_yields_no_chunks(self):
        assert chunk_text("   ") == []

    def test_respects_max_chars(self):
        text = ". ".join(f"sentence number {i}" for i in range(40))
        chunks = chunk_text(text, 80)
        assert len(chunks) > 1
        assert all(len(chunk) <= 80 for chunk in chunks)

    def test_oversized_sentence_is_hard_split(self):
        assert [len(c) for c in chunk_text("x" * 250, 100)] == [100, 100, 50]

    def test_no_content_is_lost(self):
        text = "First sentence. Second sentence. Third sentence."
        joined = " ".join(chunk_text(text, 20))
        assert "First sentence." in joined and "Third sentence." in joined


class TestRetryCall:
    """Retry logic makes transient provider failures survivable."""

    def test_returns_first_success(self):
        assert retry_call(lambda: 42, sleep=lambda _: None) == 42

    def test_retries_then_succeeds(self):
        attempts = {"count": 0}
        delays = []

        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("transient")
            return "ok"

        result = retry_call(flaky, attempts=5, description="flaky", sleep=delays.append)
        assert result == "ok"
        assert attempts["count"] == 3
        assert len(delays) == 2  # Two retries occurred

    def test_raises_after_exhausting_attempts(self):
        def boom():
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            retry_call(boom, attempts=2, sleep=lambda _: None)

    def test_give_up_on_skips_retries(self):
        attempts = {"count": 0}

        def boom():
            attempts["count"] += 1
            raise ValueError("fatal")

        with pytest.raises(ValueError):
            retry_call(boom, attempts=4, give_up_on=(ValueError,), sleep=lambda _: None)
        assert attempts["count"] == 1


class TestParseJsonObject:
    """Robust JSON extraction keeps LLM output usable."""

    def test_plain_json(self):
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        raw = 'Sure!\n```json\n{"title": "Hi"}\n```\nHope that helps.'
        assert parse_json_object(raw) == {"title": "Hi"}

    def test_json_with_surrounding_prose(self):
        assert parse_json_object('before {"a": {"b": 2}} after') == {"a": {"b": 2}}

    def test_braces_inside_strings_do_not_break_parsing(self):
        raw = '{"text": "uses { and } inside"}'
        assert parse_json_object(raw)["text"] == "uses { and } inside"

    @pytest.mark.parametrize("raw", ["", "no json here", "[1, 2, 3]"])
    def test_unparseable_returns_empty_dict(self, raw):
        assert parse_json_object(raw) == {}


class TestJsonFiles:
    """Monitor state and sidecar files must survive bad input."""

    def test_read_write_roundtrip(self, tmp_path):
        from podcast.utils import read_json_file, write_json_file

        target = tmp_path / "nested" / "state.json"
        write_json_file(target, {"seen": ["a", "b"]})
        assert read_json_file(target) == {"seen": ["a", "b"]}

    def test_missing_file_returns_default(self, tmp_path):
        from podcast.utils import read_json_file

        assert read_json_file(tmp_path / "missing.json", {"fallback": True}) == {
            "fallback": True
        }

    def test_corrupt_file_returns_default(self, tmp_path):
        from podcast.utils import read_json_file

        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert read_json_file(broken) == {}
