"""
Typed data models shared across the podcast pipeline.
===================================================

Keeping these in one dependency-free module prevents circular imports between
the ingestion, script, synthesis, audio and publishing layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from podcast.utils import estimate_speech_seconds, slugify


class SourceKind(str, Enum):
    """Kind of input the article was loaded from."""

    URL = "url"
    PDF = "pdf"
    RSS = "rss"


@dataclass
class Article:
    """Normalised content extracted from any supported input source."""

    text: str
    title: str = ""
    url: str = ""
    kind: SourceKind = SourceKind.URL
    author: str = ""
    published: str = ""
    truncated: bool = False

    @property
    def word_count(self) -> int:
        """Approximate word count of the extracted body text."""
        return len(self.text.split())

    @property
    def display_title(self) -> str:
        """Best available title, falling back to the URL or source kind."""
        if self.title.strip():
            return self.title.strip()
        if self.url:
            return self.url
        return f"{self.kind.value.upper()} document"


@dataclass
class Host:
    """A podcast speaker: display name, persona brief and ElevenLabs voice."""

    name: str
    voice_id: str
    persona: str = ""
    role: str = "host"


@dataclass
class DialogueSegment:
    """One spoken turn in a podcast script."""

    speaker: str
    text: str
    voice_id: str = ""


@dataclass
class PodcastScript:
    """A complete, narration-ready script (solo monologue or dialogue)."""

    segments: List[DialogueSegment] = field(default_factory=list)
    language: str = "en"
    style: str = "solo"

    @property
    def text(self) -> str:
        """Full script as plain text (used for display and word counts)."""
        if len(self.segments) == 1:
            return self.segments[0].text
        return "\n\n".join(f"{seg.speaker}: {seg.text}" for seg in self.segments)

    @property
    def narration_text(self) -> str:
        """Text without speaker labels, suitable for single-voice synthesis."""
        return " ".join(seg.text for seg in self.segments)

    @property
    def is_dialogue(self) -> bool:
        """True when the script features more than one distinct speaker."""
        return len({seg.speaker for seg in self.segments}) > 1

    @property
    def characters(self) -> int:
        """Total narration characters, used for TTS cost estimation."""
        return sum(len(seg.text) for seg in self.segments)

    @property
    def estimated_speech_seconds(self) -> int:
        """Rough narration length estimate based on the narration text."""
        return estimate_speech_seconds(self.narration_text)


@dataclass
class EpisodeMetadata:
    """Episode title, description and tags derived from the source article."""

    title: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    language: str = "en"

    @property
    def slug(self) -> str:
        """Filesystem-safe identifier derived from the title."""
        return slugify(self.title) or "podcast-episode"


@dataclass
class PublishResult:
    """Outcome of a single publishing attempt."""

    platform: str
    ok: bool
    message: str = ""
    url: str = ""
    location: str = ""


@dataclass
class EpisodeResult:
    """Everything produced by one pipeline run."""

    metadata: EpisodeMetadata
    script: PodcastScript
    article: Article
    audio_bytes: bytes = b""
    audio_filename: str = "podcast.mp3"
    audio_format: str = "audio/mpeg"
    duration_seconds: float = 0.0
    music_preset: str = "none"
    used_dialogue_tts: bool = False
    publish_results: List[PublishResult] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_audio(self) -> bool:
        """True when audio was successfully synthesised."""
        return bool(self.audio_bytes)

    @property
    def duration_label(self) -> str:
        """Human readable duration, e.g. ``3m 42s``."""
        total = int(round(self.duration_seconds))
        minutes, seconds = divmod(total, 60)
        return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"

    def as_dict(self) -> dict:
        """Serialisable summary, used for archive sidecar files."""
        return {
            "title": self.metadata.title,
            "description": self.metadata.description,
            "tags": self.metadata.tags,
            "language": self.metadata.language,
            "style": self.script.style,
            "source_url": self.article.url,
            "source_kind": self.article.kind.value,
            "source_title": self.article.display_title,
            "duration_seconds": round(self.duration_seconds, 1),
            "music_preset": self.music_preset,
            "audio_filename": self.audio_filename,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class FeedEntry:
    """A single item discovered in an RSS/Atom feed."""

    title: str
    link: str = ""
    guid: str = ""
    published: str = ""
    summary: str = ""

    def identity(self) -> str:
        """Stable identifier used for duplicate detection in the monitor state."""
        return self.guid or self.link or self.title


@dataclass
class PipelineOptions:
    """User-selected options controlling a single pipeline run."""

    style: str = "solo"
    language: str = "en"
    hosts: List[Host] = field(default_factory=list)
    voice_id: str = ""
    music_preset: str = "none"
    music_bytes: Optional[bytes] = None
    generate_metadata: bool = True
    max_words: int = 0