"""
End-to-end orchestration of an episode generation run.
====================================================

The pipeline is the only module the UI talks to. It owns the ordering of the
seven capabilities and converts every failure into a typed
:class:`podcast.errors.PodcastError` with an actionable hint.

Client objects can be injected, which keeps the whole flow testable without
any API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

import threading

from podcast import audio, config, ingestion, publishing, script as script_mod, tts
from podcast.errors import PodcastError
from podcast.models import (
    Article,
    EpisodeResult,
    FeedEntry,
    Host,
    PipelineOptions,
    PublishResult,
)
from podcast.utils import get_logger

LOGGER = get_logger("pipeline")

# Called as ``progress("Writing the script", "solo, English")``.
ProgressCallback = Callable[[str, str], None]


@dataclass
class PipelineClients:
    """Injectable third-party clients (all optional in production)."""

    firecrawl: Any = None
    elevenlabs: Any = None
    generator: Optional[Callable[[str], str]] = None
    youtube: Any = None


def _noop_progress(stage: str, detail: str = "") -> None:
    """Default progress sink that simply logs."""

    LOGGER.debug("progress: %s (%s)", stage, detail)


class PodcastPipeline:
    """Generates podcast episodes from URLs, PDFs and RSS feeds.

    Args:
        gemini_api_key: Google Gemini key used to write scripts and metadata.
        firecrawl_api_key: Firecrawl key used to scrape articles.
        elevenlabs_api_key: ElevenLabs key used for speech and music.
        clients: Optional injected clients (tests, notebooks, batch jobs).
        progress: Callback invoked with ``(stage, detail)`` as work proceeds.
    """

    def __init__(
        self,
        *,
        gemini_api_key: str = "",
        firecrawl_api_key: str = "",
        elevenlabs_api_key: str = "",
        clients: Optional[PipelineClients] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        self.gemini_api_key = gemini_api_key or ""
        self.firecrawl_api_key = firecrawl_api_key or ""
        self.elevenlabs_api_key = elevenlabs_api_key or ""
        self.clients = clients or PipelineClients()
        self.progress = progress or _noop_progress

        self._firecrawl = self.clients.firecrawl
        self._elevenlabs = self.clients.elevenlabs
        self._lock = threading.Lock()

    # ── lazy client accessors ──────────────────────────────
    @property
    def firecrawl(self) -> Any:
        """Firecrawl client, created on first use."""
        with self._lock:
            if self._firecrawl is None:
                self._firecrawl = ingestion.build_firecrawl_client(self.firecrawl_api_key)
            return self._firecrawl

    @property
    def elevenlabs(self) -> Any:
        """ElevenLabs client, created on first use."""
        with self._lock:
            if self._elevenlabs is None:
                self._elevenlabs = tts.build_elevenlabs_client(self.elevenlabs_api_key)
            return self._elevenlabs

    @property
    def monitor(self) -> ingestion.FeedMonitor:
        """Feed monitor bound to the persisted state file."""
        return ingestion.FeedMonitor()

    # ── source loading ─────────────────────────────────────
    def load_from_url(self, url: str) -> Article:
        """Load an article from a blog URL or a direct PDF link."""
        self.progress("Fetching source", url)
        return ingestion.load_article_from_url(
            url,
            client=self.firecrawl if self.clients.firecrawl else None,
            api_key=self.firecrawl_api_key,
        )

    def load_from_pdf(self, data: bytes, filename: str = "document.pdf") -> Article:
        """Load an article from uploaded PDF bytes."""
        self.progress("Reading PDF", filename)
        return ingestion.load_article_from_pdf_bytes(data, filename=filename)

    def load_from_feed_entry(self, entry: FeedEntry) -> Article:
        """Load an article from one RSS feed entry."""
        self.progress("Reading feed item", entry.title or entry.link)
        return ingestion.load_article_from_feed_entry(
            entry,
            client=self.firecrawl if self.clients.firecrawl else None,
            api_key=self.firecrawl_api_key,
        )

    def list_feed_entries(
        self, feed_url: str, limit: int = config.RSS_DEFAULT_LIMIT
    ) -> List[FeedEntry]:
        """List the newest entries of a feed (newest first)."""
        self.progress("Checking feed", feed_url)
        return ingestion.fetch_feed_entries(feed_url, limit=limit)

    def new_feed_entries(
        self, feed_url: str, limit: int = config.RSS_DEFAULT_LIMIT
    ) -> List[FeedEntry]:
        """List only the feed entries that have not been processed yet."""
        entries = self.list_feed_entries(feed_url, limit=limit)
        return self.monitor.new_entries(feed_url, entries)

    # ── episode generation ─────────────────────────────────
    def generate(self, article: Article, options: PipelineOptions) -> EpisodeResult:
        """Run the full pipeline for one article.

        Steps: write the script, generate metadata, synthesize speech, mix the
        music bed, then return the finished episode.
        """
        language = config.get_language(options.language)
        style = config.get_style(options.style)
        hosts = script_mod.resolve_hosts(style.key, options.hosts)

        # 1. Script (features 3 and 4)
        script = self._prepare_script(article, options, style, language, hosts)

        # 2. Episode metadata (feature 6)
        metadata = self._prepare_metadata(article, script, options, language)

        # 3. Speech synthesis (features 3 and 4)
        voice_id = options.voice_id or hosts[0].voice_id or config.DEFAULT_VOICE_ID
        synthesis = self._prepare_audio(script, voice_id, language)

        # 4. Music bed (feature 5)
        audio_bytes, mix_report = self._prepare_music(
            synthesis.audio, options, language
        )

        result = EpisodeResult(
            metadata=metadata,
            script=script,
            article=article,
            audio_bytes=audio_bytes,
            audio_filename=f"{metadata.slug}.mp3",
            duration_seconds=self._measure_duration(audio_bytes, script),
            music_preset=mix_report.preset_key if mix_report.applied else "none",
            used_dialogue_tts=synthesis.used_dialogue_api,
        )
        LOGGER.info(
            "Episode ready: '%s' (%s, %d bytes)",
            metadata.title,
            result.duration_label,
            len(audio_bytes),
        )
        return result

    def _prepare_script(
        self,
        article: Article,
        options: PipelineOptions,
        style: config.StylePreset,
        language: config.Language,
        hosts: List[Host],
    ) -> script_mod.PodcastScript:
        self.progress("Writing the script", f"{style.label} · {language.label}")
        return script_mod.generate_script(
            article,
            style_key=style.key,
            language=language.code,
            hosts=hosts,
            generator=self.clients.generator,
            api_key=self.gemini_api_key,
            max_words=options.max_words or config.SCRIPT_MAX_WORDS,
        )

    def _prepare_metadata(
        self,
        article: Article,
        script: script_mod.PodcastScript,
        options: PipelineOptions,
        language: config.Language,
    ) -> script_mod.EpisodeMetadata:
        if not options.generate_metadata:
            return script_mod.fallback_metadata(article, language=language.code)

        self.progress("Naming the episode", "title, description, tags")
        return script_mod.generate_metadata(
            article,
            script,
            generator=self.clients.generator,
            api_key=self.gemini_api_key,
            language=language.code,
        )

    def _prepare_audio(
        self,
        script: script_mod.PodcastScript,
        voice_id: str,
        language: config.Language,
    ) -> tts.SynthesisResult:
        detail = "multi-speaker dialogue" if script.is_dialogue else "single narrator"
        self.progress("Synthesizing speech", detail)
        return tts.synthesize(
            script,
            client=self.elevenlabs,
            api_key=self.elevenlabs_api_key,
            voice_id=voice_id,
            language_code=language.code,
        )

    def _prepare_music(
        self,
        narration_bytes: bytes,
        options: PipelineOptions,
        language: config.Language,
    ) -> Tuple[bytes, audio.MusicMixReport]:
        preset = config.get_music_preset(options.music_preset)
        if preset.key == "none":
            return narration_bytes, audio.MusicMixReport(
                applied=False, reason="no music requested", preset_key="none"
            )

        self.progress("Adding music", preset.label)
        music = options.music_bytes or audio.build_music_bed(
            preset,
            client=self.elevenlabs,
            api_key=self.elevenlabs_api_key,
        )
        audio_bytes, report = audio.apply_music_preset(
            narration_bytes, preset, music=music
        )
        if not report.applied:
            LOGGER.warning("Music not applied: %s", report.reason)
        return audio_bytes, report

    @staticmethod
    def _measure_duration(audio_bytes: bytes, script: Any) -> float:
        """Real audio duration, falling back to a word-count estimate."""
        try:
            return audio.decode_audio(audio_bytes).duration
        except PodcastError:
            return float(script.estimated_speech_seconds)

    # ─ publishing (feature 7) ─────────────────────────────
    def publish(
        self,
        episode: EpisodeResult,
        platforms: Any,
        *,
        webhook_url: str = "",
        feed_base_url: str = "",
        youtube_privacy: str = config.YOUTUBE_PRIVACY_STATUS,
        directory: Any = None,
    ) -> List[PublishResult]:
        """Publish an episode and attach the results to it."""
        keys = [platforms] if isinstance(platforms, str) else list(platforms or [])
        if not keys:
            return []
        self.progress("Publishing", ", ".join(str(key) for key in keys))
        results = publishing.publish_episode(
            episode,
            keys,
            webhook_url=webhook_url,
            base_url=feed_base_url,
            directory=directory,
            youtube_client=self.clients.youtube,
            youtube_privacy=youtube_privacy,
        )
        episode.publish_results.extend(results)
        return results

    # ── RSS batch generation (feature 2) ───────────────────
    def generate_from_feed(
        self,
        feed_url: str,
        options: PipelineOptions,
        *,
        limit: int = 1,
        platforms: Any = None,
        webhook_url: str = "",
        feed_base_url: str = "",
        mark_seen: bool = True,
    ) -> List[EpisodeResult]:
        """Generate episodes for the newest unprocessed feed entries.

        Args:
            feed_url: RSS/Atom feed URL.
            options: Pipeline options applied to every episode.
            limit: Maximum number of episodes to generate in this run.
            platforms: Optional publish destinations.
            mark_seen: Record entries as processed only after they succeed.

        Returns:
            The episodes generated in this run (possibly empty).
        """
        entries = self.new_feed_entries(
            feed_url, limit=max(limit, config.RSS_DEFAULT_LIMIT)
        )
        if limit > 0:
            entries = entries[:limit]

        episodes: List[EpisodeResult] = []
        for entry in entries:
            try:
                article = self.load_from_feed_entry(entry)
                episode = self.generate(article, options)
                if platforms:
                    self.publish(
                        episode,
                        platforms,
                        webhook_url=webhook_url,
                        feed_base_url=feed_base_url,
                    )
                episodes.append(episode)
                if mark_seen:
                    self.monitor.mark_entries_seen(feed_url, [entry])
            except PodcastError as exc:
                LOGGER.error(
                    "Skipping '%s': %s", entry.title or entry.link, exc.message
                )
                continue
        return episodes


def build_options(
    *,
    style: str = "solo",
    language: str = "en",
    hosts: Optional[List[Host]] = None,
    voice_id: str = "",
    music_preset: str = "none",
    music_bytes: Optional[bytes] = None,
    generate_metadata: bool = True,
    max_words: int = config.SCRIPT_MAX_WORDS,
) -> PipelineOptions:
    """Create :class:`PipelineOptions` using central defaults."""
    return PipelineOptions(
        style=config.get_style(style).key,
        language=config.get_language(language).code,
        hosts=list(hosts or []),
        voice_id=voice_id,
        music_preset=config.get_music_preset(music_preset).key,
        music_bytes=music_bytes,
        generate_metadata=generate_metadata,
        max_words=max_words,
    )
