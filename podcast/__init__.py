"""
Blog to Podcast Agent - core package
====================================
Layered, testable implementation of the blog -> podcast pipeline.

Modules
-------
``models``     Typed data structures shared across the pipeline.
``config``     Central configuration (models, voices, languages, presets).
``errors``     Typed error taxonomy with actionable user messages.
``utils``      Retry/backoff, text chunking and JSON parsing helpers.
``ingestion``  Content acquisition: blog URLs, PDF documents and RSS feeds.
``script``     Podcast script writing: solo, multi-host dialogue and metadata.
``tts``        Text-to-speech synthesis (single voice and multi-speaker).
``audio``      Music beds: intro/outro/underlay mixing.
``publishing`` Episode publishing (local archive, RSS feed, webhook, YouTube).
``pipeline``   Orchestration of the end-to-end episode generation.

Author: Aniket Potabatti (@aniketpotabatti)
License: MIT License
"""

from podcast.errors import PodcastError
from podcast.models import Article, EpisodeResult, PodcastScript, SourceKind

__all__ = [
    "Article",
    "EpisodeResult",
    "PodcastError",
    "PodcastScript",
    "SourceKind",
]