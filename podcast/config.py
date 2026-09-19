"""
Central configuration for the Blog-to-Podcast agent.
===================================================

All tunable values live here so the pipeline modules stay free of magic
strings: model ids, voice ids, language list, style presets and music presets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

# ─────────────────────────────────────────────
#  Paths
# ─────────────────────────────────────────────
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"
ARCHIVE_DIR = OUTPUT_DIR / "episodes"
MUSIC_DIR = OUTPUT_DIR / "music"
RSS_STATE_FILE = OUTPUT_DIR / "rss_state.json"
LOG_DIR = OUTPUT_DIR / "logs"

# ─────────────────────────────────────────────
#  LLM
# ─────────────────────────────────────────────
DEFAULT_LLM_MODEL = "gemini-2.5-flash"
SCRIPT_MAX_WORDS = 450
METADATA_MAX_TAGS = 6

# ─────────────────────────────────────────────
#  Text-to-speech
# ────────────────────────────────────────────
TTS_MODEL_DEFAULT = "eleven_turbo_v2_5"
TTS_MODEL_MULTILINGUAL = "eleven_multilingual_v2"
TTS_OUTPUT_FORMAT = "mp3_44100_128"
TTS_CHUNK_CHARS = 1800
TTS_MAX_RETRIES = 3
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # "George" - the project default voice

# ─────────────────────────────────────────────
#  Networking / retries
# ────────────────────────────────────────────
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.5
BACKOFF_MAX_SECONDS = 20.0

# ────────────────────────────────────────────
#  Ingestion
# ─────────────────────────────────────────────
MAX_ARTICLE_CHARS = 40_000
PDF_MAX_PAGES = 40
RSS_DEFAULT_LIMIT = 10
PDF_CONTENT_TYPES = ("application/pdf", "application/x-pdf")

# ─────────────────────────────────────────────
#  Audio
# ─────────────────────────────────────────────
DEFAULT_FADE_SECONDS = 1.5
MIX_SAMPLE_RATE = 44_100
WORDS_PER_MINUTE = 150

# ─────────────────────────────────────────────
#  Publishing
# ─────────────────────────────────────────────
FEED_TITLE = "Blog to Podcast - AI Episodes"
FEED_DESCRIPTION = "AI-narrated podcast episodes generated from blog posts, PDFs and RSS feeds."
FEED_LANGUAGE = "en"
FEED_MAX_ITEMS = 50


# ─────────────────────────────────────────────
#  Languages  (FEATURE 3: multilingual support)
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class Language:
    """A selectable narration language."""

    label: str
    code: str  # ElevenLabs / ISO-639-1 code
    native: str = ""


LANGUAGES: Tuple[Language, ...] = (
    Language("English", "en", "English"),
    Language("Spanish", "es", "Espanol"),
    Language("French", "fr", "Francais"),
    Language("German", "de", "Deutsch"),
    Language("Italian", "it", "Italiano"),
    Language("Portuguese", "pt", "Portugues"),
    Language("Dutch", "nl", "Nederlands"),
    Language("Polish", "pl", "Polski"),
    Language("Turkish", "tr", "Turkce"),
    Language("Russian", "ru", "Russkij"),
    Language("Arabic", "ar", "Arabiyya"),
    Language("Hindi", "hi", "Hindi"),
    Language("Japanese", "ja", "Nihongo"),
    Language("Korean", "ko", "Hangugeo"),
    Language("Mandarin Chinese", "zh", "Putonghua"),
)

LANGUAGE_BY_CODE: Dict[str, Language] = {lang.code: lang for lang in LANGUAGES}
LANGUAGE_LABELS: Tuple[str, ...] = tuple(lang.label for lang in LANGUAGES)


def get_language(code_or_label: str) -> Language:
    """Resolve a language by ISO code or display label (defaults to English)."""
    needle = (code_or_label or "").strip().lower()
    if needle in LANGUAGE_BY_CODE:
        return LANGUAGE_BY_CODE[needle]
    for lang in LANGUAGES:
        if lang.label.lower() == needle:
            return lang
    return LANGUAGE_BY_CODE["en"]


def resolve_tts_model(language_code: str) -> str:
    """Pick the TTS model: turbo for English, multilingual v2 elsewhere."""
    return TTS_MODEL_DEFAULT if language_code == "en" else TTS_MODEL_MULTILINGUAL


# ────────────────────────────────────────────
#  Voices  (used by solo narration and multi-host dialogue)
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class Voice:
    """A curated ElevenLabs voice option."""

    name: str
    voice_id: str
    description: str


VOICES: Tuple[Voice, ...] = (
    Voice("George", "JBFqnCBsd6RMkjVDRZzb", "Warm British narrator (project default)"),
    Voice("Rachel", "21m00Tcm4TlvDq8ikWAM", "Calm American female narrator"),
    Voice("Charlotte", "XB0fDUnXU5powFXDhCwa", "Soft, expressive female voice"),
    Voice("Alice", "Xb7hH8MSUJpSbSDYk0k2", "Clear, friendly British female voice"),
    Voice("Matilda", "XrExE9yKIg1WjnnlVkGX", "Bright, upbeat female voice"),
    Voice("Jessica", "cgSgspJ2msm6clMCkdW9", "Conversational American female voice"),
    Voice("Laura", "FGY2WhTYpPnrIDTdsKH5", "Lively female voice for casual shows"),
    Voice("Adam", "pNInz6obpgDQGcFmaJgB", "Deep American male narrator"),
    Voice("Daniel", "onwK4e9ZLuTAKqWW03F9", "Authoritative British male news voice"),
    Voice("Brian", "nPczCjzI2devNBz1zQrb", "Rich, steady American male voice"),
    Voice("Will", "bIHbv24MWmeRgasZH58o", "Young, relaxed American male voice"),
    Voice("Chris", "iP95p4xoKVk53GoZ742B", "Casual, friendly male voice"),
    Voice("Liam", "TX3LPaxmHKxFdv7VOQHJ", "Clear, energetic male voice"),
    Voice("Callum", "N2lVS1w4EtoT3dr4eOWO", "Intense, characterful male voice"),
)

VOICE_BY_ID: Dict[str, Voice] = {voice.voice_id: voice for voice in VOICES}


def voice_name(voice_id: str) -> str:
    """Human readable name for a voice id, falling back to the raw id."""
    voice = VOICE_BY_ID.get(voice_id)
    return voice.name if voice else voice_id


# ─────────────────────────────────────────────
#  Script styles  (FEATURE 4: multi-host dialogue)
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class StylePreset:
    """A podcast format: how many hosts and how the script should read."""

    key: str
    label: str
    description: str
    host_count: int
    guidance: str


STYLES: Tuple[StylePreset, ...] = (
    StylePreset(
        key="solo",
        label="Solo monologue",
        description="One narrator walking the listener through the article.",
        host_count=1,
        guidance=(
            "Deliver a single-narrator monologue. Do not use speaker labels, "
            "stage directions or sound-effect cues."
        ),
    ),
    StylePreset(
        key="dialogue",
        label="Two-host conversation",
        description="Two hosts discuss, question and react to the article.",
        host_count=2,
        guidance=(
            "Write a natural two-host conversation. The hosts should build on "
            "each other, ask genuine questions and occasionally disagree."
        ),
    ),
    StylePreset(
        key="interview",
        label="Interview",
        description="One interviewer quizzes one expert about the article.",
        host_count=2,
        guidance=(
            "Write an interview: the first host is a curious interviewer, the "
            "second answers with expertise drawn from the article."
        ),
    ),
    StylePreset(
        key="news_brief",
        label="News brief",
        description="Fast, factual headlines-style summary.",
        host_count=1,
        guidance=(
            "Deliver a crisp news brief: lead with the headline, then the key "
            "facts, then why it matters. Keep sentences short."
        ),
    ),
    StylePreset(
        key="deep_dive",
        label="Deep dive",
        description="Two hosts analyse implications and context in depth.",
        host_count=2,
        guidance=(
            "Write an analytical deep dive between two hosts, covering context, "
            "implications and open questions raised by the article."
        ),
    ),
)

STYLE_BY_KEY: Dict[str, StylePreset] = {style.key: style for style in STYLES}
STYLE_LABELS: Tuple[str, ...] = tuple(style.label for style in STYLES)

# Default host pairs used when the user does not customise speakers.
DEFAULT_HOST_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("Rachel", "Adam"),
    ("Charlotte", "Daniel"),
    ("Matilda", "Brian"),
)


def get_style(key_or_label: str) -> StylePreset:
    """Resolve a style preset by key or label (defaults to solo)."""
    needle = (key_or_label or "").strip().lower()
    if needle in STYLE_BY_KEY:
        return STYLE_BY_KEY[needle]
    for style in STYLES:
        if style.label.lower() == needle:
            return style
    return STYLE_BY_KEY["solo"]


def default_hosts(style_key: str, voices: Tuple[Voice, ...] = VOICES) -> List[Voice]:
    """Pick sensible default voices for the number of hosts a style needs."""
    style = get_style(style_key)
    if style.host_count < 2:
        return [VOICES[0]]
    pair = DEFAULT_HOST_PAIRS[0]
    chosen: List[Voice] = []
    for name in pair:
        match = next((v for v in voices if v.name.lower() == name.lower()), None)
        if match:
            chosen.append(match)
    while len(chosen) < style.host_count:
        chosen.append(VOICES[len(chosen)])
    return chosen[: style.host_count]


# ─────────────────────────────────────────────
#  Music presets  (FEATURE 5: background music)
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class MusicPreset:
    """How a background music bed should be generated and mixed."""

    key: str
    label: str
    description: str
    prompt: str
    intro_seconds: float = 0.0
    outro_seconds: float = 0.0
    underlay_gain_db: float = -22.0
    fade_seconds: float = DEFAULT_FADE_SECONDS
    underlay: bool = False


MUSIC_PRESETS: Tuple[MusicPreset, ...] = (
    MusicPreset(
        key="none",
        label="No music",
        description="Narration only.",
        prompt="",
    ),
    MusicPreset(
        key="intro_outro",
        label="Intro & outro sting",
        description="Short musical stings before and after the narration.",
        prompt="Warm, optimistic tech podcast sting, short and clean, instrumental",
        intro_seconds=6.0,
        outro_seconds=8.0,
    ),
    MusicPreset(
        key="calm_underlay",
        label="Calm underlay",
        description="Soft ambient bed under the whole narration plus stings.",
        prompt="Soft ambient electronic podcast bed, calm, sparse, instrumental, no drums",
        intro_seconds=4.0,
        outro_seconds=6.0,
        underlay_gain_db=-24.0,
        underlay=True,
    ),
    MusicPreset(
        key="upbeat",
        label="Upbeat",
        description="Energetic intro and outro for a lively show.",
        prompt="Upbeat modern podcast intro music, punchy and bright, instrumental",
        intro_seconds=7.0,
        outro_seconds=7.0,
        underlay_gain_db=-20.0,
    ),
    MusicPreset(
        key="cinematic",
        label="Cinematic",
        description="Cinematic underlay with a confident intro and outro.",
        prompt="Cinematic documentary score, inspiring strings and soft percussion, instrumental",
        intro_seconds=8.0,
        outro_seconds=10.0,
        underlay_gain_db=-25.0,
        underlay=True,
    ),
    MusicPreset(
        key="lofi",
        label="Lo-fi underlay",
        description="Relaxed lo-fi bed for long-form narration.",
        prompt="Lo-fi hip hop study beat, mellow, instrumental, no vocals",
        intro_seconds=4.0,
        outro_seconds=6.0,
        underlay_gain_db=-23.0,
        underlay=True,
    ),
)

MUSIC_BY_KEY: Dict[str, MusicPreset] = {preset.key: preset for preset in MUSIC_PRESETS}
MUSIC_LABELS: Tuple[str, ...] = tuple(preset.label for preset in MUSIC_PRESETS)
MUSIC_MAX_LENGTH_MS = 120_000
MUSIC_DEFAULT_LENGTH_MS = 30_000


def get_music_preset(key_or_label: str) -> MusicPreset:
    """Resolve a music preset by key or label (defaults to no music)."""
    needle = (key_or_label or "").strip().lower()
    if needle in MUSIC_BY_KEY:
        return MUSIC_BY_KEY[needle]
    for preset in MUSIC_PRESETS:
        if preset.label.lower() == needle:
            return preset
    return MUSIC_BY_KEY["none"]


# ─────────────────────────────────────────────
#  Publishing destinations  (FEATURE 7)
# ─────────────────────────────────────────────
@dataclass(frozen=True)
class PlatformSpec:
    """A publishing destination and the mechanism used to reach it."""

    key: str
    label: str
    mode: str  # "archive" | "rss" | "webhook" | "youtube"
    description: str
    docs_url: str = ""


PLATFORMS: Tuple[PlatformSpec, ...] = (
    PlatformSpec(
        key="archive",
        label="Local archive",
        mode="archive",
        description="Save the MP3 plus episode metadata into outputs/episodes.",
    ),
    PlatformSpec(
        key="rss",
        label="RSS feed (self-hosted)",
        mode="rss",
        description="Rebuild an RSS 2.0 + iTunes feed that any podcast app can subscribe to.",
    ),
    PlatformSpec(
        key="spotify",
        label="Spotify",
        mode="rss",
        description=(
            "Spotify has no public episode-upload API: it ingests shows through "
            "an RSS feed. This publishes the feed and returns the submission link."
        ),
        docs_url="https://podcasters.spotify.com/",
    ),
    PlatformSpec(
        key="youtube",
        label="YouTube",
        mode="youtube",
        description="Upload an MP4 (cover image + narration) through the YouTube Data API v3.",
        docs_url="https://developers.google.com/youtube/v3/guides/uploading_a_video",
    ),
    PlatformSpec(
        key="webhook",
        label="Webhook (Zapier / Make / other platforms)",
        mode="webhook",
        description="POST the MP3 and metadata to any endpoint that accepts multipart uploads.",
    ),
)

PLATFORM_BY_KEY: Dict[str, PlatformSpec] = {spec.key: spec for spec in PLATFORMS}
PLATFORM_LABELS: Tuple[str, ...] = tuple(spec.label for spec in PLATFORMS)

YOUTUBE_UPLOAD_SCOPES: Tuple[str, ...] = ("https://www.googleapis.com/auth/youtube.upload",)
YOUTUBE_API_SERVICE = "youtube"
YOUTUBE_API_VERSION = "v3"
YOUTUBE_CATEGORY_ID = "22"  # People & Blogs
YOUTUBE_PRIVACY_STATUS = "private"
YOUTUBE_DEFAULT_TAGS: Tuple[str, ...] = ("podcast", "ai", "blog to podcast")


def get_platform(key_or_label: str) -> PlatformSpec:
    """Resolve a publishing platform by key or label (defaults to archive)."""
    needle = (key_or_label or "").strip().lower()
    if needle in PLATFORM_BY_KEY:
        return PLATFORM_BY_KEY[needle]
    for spec in PLATFORMS:
        if spec.label.lower() == needle:
            return spec
    return PLATFORM_BY_KEY["archive"]