"""
Podcast script writing: solo, multi-host dialogue and episode metadata.
=====================================================================

Feature 3 - Multilingual support
    The target language is injected into every prompt and carried on the
    resulting :class:`PodcastScript` so synthesis can match it.

Feature 4 - Multi-host / AI dialogue generation
    ``parse_script`` turns ``Speaker: line`` output into typed
    :class:`DialogueSegment` objects, each bound to a host voice id. If the
    model ignores the format the parser degrades gracefully instead of failing.

Feature 6 - Automatic episode titles and descriptions
    ``generate_metadata`` produces an SEO-friendly title, a description and
    tags, with a deterministic fallback so an episode is never left untitled.

The LLM is injected as a ``TextGenerator`` callable, so the whole module is
unit-testable without any API key.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from podcast import config
from podcast.config import match_host, resolve_hosts
from podcast.errors import ConfigurationError, ScriptGenerationError, classify_exception
from podcast.models import (
    Article,
    DialogueSegment,
    EpisodeMetadata,
    Host,
    PodcastScript,
)
from podcast.utils import (
    clean_text,
    coerce_str_list,
    get_logger,
    parse_json_object,
    retry_call,
    truncate_text,
    truncate_words,
)

LOGGER = get_logger("script")

# A callable that turns a prompt into raw model text.
TextGenerator = Callable[[str], str]

_SPEAKER_LINE_RE = re.compile(
    r"^\s*\**\s*(?P<speaker>[A-Za-z][A-Za-z0-9 .'\-]{0,29})\s*\**\s*:\s*(?P<line>.*)$"
)

SCRIPT_SYSTEM_INSTRUCTIONS = [
    "You are a professional podcast writer and script editor.",
    "You write natural, factual, spoken-word audio scripts.",
    "You never invent facts that are not supported by the source material.",
    "You never add sound-effect cues, stage directions or placeholder labels.",
]


# ─────────────────────────────────────────────
#  LLM plumbing
# ─────────────────────────────────────────────
def build_gemini_generator(
    api_key: str = "", model_id: str = config.DEFAULT_LLM_MODEL
) -> TextGenerator:
    """Create a ``TextGenerator`` backed by Google Gemini via Agno.

    Args:
        api_key: Gemini API key. When empty the SDK falls back to the
            ``GEMINI_API_KEY`` environment variable.
        model_id: Gemini model id.

    Returns:
        A callable accepting a prompt and returning the model's text.
    """

    def generate(prompt: str) -> str:
        if not api_key and not _has_env_credentials():
            raise ConfigurationError(
                "A Google Gemini API key is required to write the script.",
                hint="Add the key in the sidebar or set the GEMINI_API_KEY variable.",
            )
        from agno.agent import Agent
        from agno.models.google import Gemini

        model_kwargs: Dict[str, Any] = {"id": model_id}
        if api_key:
            model_kwargs["api_key"] = api_key
        agent = Agent(
            name="Podcast Script Writer",
            model=Gemini(**model_kwargs),
            instructions=SCRIPT_SYSTEM_INSTRUCTIONS,
            markdown=False,
        )
        response = agent.run(prompt)
        content = getattr(response, "content", None) or str(response)
        return str(content)

    return generate


def _has_env_credentials() -> bool:
    """True when a Gemini key is available through the environment."""
    import os

    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def generate_text(
    prompt: str,
    *,
    generator: Optional[TextGenerator] = None,
    api_key: str = "",
    model_id: str = config.DEFAULT_LLM_MODEL,
    attempts: Optional[int] = None,
    description: str = "llm call",
) -> str:
    """Run a prompt through the LLM with retries and typed errors.

    Configuration problems are not retried: a missing key will not fix itself.
    """
    run = generator or build_gemini_generator(api_key=api_key, model_id=model_id)
    try:
        text = retry_call(
            run,
            prompt,
            attempts=resolve_attempts(attempts),
            give_up_on=(ConfigurationError,),
            description=description,
            logger=LOGGER,
        )
    except ConfigurationError:
        raise
    except Exception as exc:
        raise classify_exception(exc, stage="script") from exc

    if not (text or "").strip():
        raise ScriptGenerationError(
            "The model returned an empty script.",
            hint="Retry the generation, or use a shorter source article.",
        )
    return text


def resolve_attempts(attempts: Optional[int] = None) -> int:
    """Resolve a retry budget, reading :mod:`podcast.config` at call time."""
    if attempts and attempts > 0:
        return attempts
    return config.MAX_RETRIES


# ─────────────────────────────────────────────
#  FEATURE 3 & 4: script prompt
# ─────────────────────────────────────────────
def build_script_prompt(
    article: Article,
    *,
    style_key: str = "solo",
    language: str = "en",
    hosts: Optional[Sequence[Host]] = None,
    max_words: int = config.SCRIPT_MAX_WORDS,
) -> str:
    """Build the script-writing prompt for an article.

    The prompt carries the language requirement (Feature 3) and the host
    roster plus strict line format (Feature 4).
    """
    style = config.get_style(style_key)
    lang = config.get_language(language)
    roster = resolve_hosts(style.key, hosts)

    parts = [
        "Write a podcast script based on the source article below.",
        "",
        f"SOURCE TITLE: {article.display_title}",
    ]
    if article.author:
        parts.append(f"SOURCE AUTHOR: {article.author}")
    if article.url:
        parts.append(f"SOURCE URL: {article.url}")
    parts += [
        "",
        "TARGET LANGUAGE: "
        f"{lang.label} ({lang.code}). Write every word of the script in "
        f"{lang.label}.",
        f"STYLE: {style.label} - {style.description}",
        f"LENGTH: at most {max_words} words of spoken narration.",
        "",
        "REQUIREMENTS:",
        f"- {style.guidance}",
        "- Open with a hook in the first two sentences.",
        "- Cover the main points, then close with a clear takeaway.",
        "- Stay faithful to the article: do not add outside facts or opinions.",
        "- Write for the ear: short sentences, no markdown, no bullet points.",
    ]

    if style.host_count >= 2:
        parts += [
            "",
            "HOSTS:",
            _host_roster(roster),
            "",
            "OUTPUT FORMAT (strict):",
            "Return only dialogue lines, one turn per line, using exactly these",
            "host names and a colon after each name. Never use any other speaker",
            "name or any label other than the hosts listed above.",
            "",
            *[f"{host.name}: <what {host.name} says>" for host in roster],
            "",
            "Continue alternating for the whole script.",
        ]
    else:
        parts += [
            "",
            "OUTPUT FORMAT (strict):",
            "Return only the spoken narration as plain prose - no speaker",
            "labels, no headings, no markdown.",
        ]

    parts += ["", "SOURCE ARTICLE:", truncate_words(clean_text(article.text), 4000)]
    return "\n".join(parts)


def _host_roster(hosts: Sequence[Host]) -> str:
    """Format the host roster for the prompt."""
    return "\n".join([f"- {host.name}: {host.persona}" for host in hosts])


# ─────────────────────────────────────────────
#  FEATURE 4: dialogue parsing
# ─────────────────────────────────────────────


def parse_script(
    raw: str,
    hosts: Sequence[Host],
    *,
    language: str = "en",
    style_key: str = "solo",
) -> PodcastScript:
    """Parse raw model output into a :class:`PodcastScript`.

    Handles ``Rachel: ...`` dialogue, bold ``**Rachel:**`` labels and unlabelled
    prose. When the model does not follow the dialogue format, the text is kept
    as a single narration segment so nothing is ever lost.
    """
    text = clean_text(raw)
    if not text:
        raise ScriptGenerationError(
            "The generated script was empty after cleaning.",
            hint="Retry the generation or shorten the source article.",
        )

    resolved_hosts = list(hosts) or [
        Host(name=voice.name, voice_id=voice.voice_id)
        for voice in config.default_hosts(style_key)
    ]

    if len(resolved_hosts) < 2:
        return PodcastScript(
            segments=[
                DialogueSegment(
                    speaker=resolved_hosts[0].name,
                    text=_strip_speaker_prefix(text),
                    voice_id=resolved_hosts[0].voice_id,
                )
            ],
            language=language,
            style=style_key,
        )

    segments: List[DialogueSegment] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _SPEAKER_LINE_RE.match(stripped)
        host = match_host(match.group("speaker"), resolved_hosts) if match else None

        if host is not None:
            speech = clean_text(match.group("line"))
            if not speech:
                continue
            segments.append(
                DialogueSegment(speaker=host.name, text=speech, voice_id=host.voice_id)
            )
            continue

        if segments:
            segments[-1].text = clean_text(f"{segments[-1].text} {stripped}")
        else:
            segments.append(
                DialogueSegment(
                    speaker=resolved_hosts[0].name,
                    text=stripped,
                    voice_id=resolved_hosts[0].voice_id,
                )
            )

    if not segments:
        raise ScriptGenerationError(
            "Could not read any spoken lines from the generated script.",
            hint="Retry the generation; the model may have returned only headings.",
        )

    if len({segment.speaker for segment in segments}) < 2:
        LOGGER.warning(
            "Dialogue script collapsed to a single speaker; narration will use one voice."
        )
    return PodcastScript(segments=segments, language=language, style=style_key)


def _strip_speaker_prefix(text: str) -> str:
    """Remove a leading ``Name:`` label from single-narrator scripts."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned: List[str] = []
    for line in lines:
        match = _SPEAKER_LINE_RE.match(line)
        cleaned.append(match.group("line").strip() if match else line)
    return clean_text(" ".join(cleaned))


def generate_script(
    article: Article,
    *,
    style_key: str = "solo",
    language: str = "en",
    hosts: Optional[Sequence[Host]] = None,
    generator: Optional[TextGenerator] = None,
    api_key: str = "",
    model_id: str = config.DEFAULT_LLM_MODEL,
    max_words: int = config.SCRIPT_MAX_WORDS,
    attempts: Optional[int] = None,
) -> PodcastScript:
    """Generate a podcast script from an article (Features 3 and 4)."""
    style = config.get_style(style_key)
    prompt = build_script_prompt(
        article,
        style_key=style.key,
        language=language,
        hosts=hosts,
        max_words=max_words,
    )
    raw = generate_text(
        prompt,
        generator=generator,
        api_key=api_key,
        model_id=model_id,
        attempts=attempts,
        description=f"script ({style.key}, {language})",
    )
    script = parse_script(
        raw,
        hosts or [],
        language=config.get_language(language).code,
        style_key=style.key,
    )
    LOGGER.info(
        "Script ready: %d segment(s), %d characters, style=%s, language=%s",
        len(script.segments),
        script.characters,
        script.style,
        script.language,
    )
    return script


# ─────────────────────────────────────────────
#  FEATURE 6: automatic episode titles and descriptions
# ─────────────────────────────────────────────
def build_metadata_prompt(
    article: Article,
    script: PodcastScript,
    *,
    language: str = "en",
    max_tags: int = config.METADATA_MAX_TAGS,
) -> str:
    """Build the prompt that produces the episode metadata JSON."""
    lang = config.get_language(language)
    return "\n".join(
        [
            "Create the publishing metadata for this podcast episode.",
            "",
            f"LANGUAGE: write every field in {lang.label} ({lang.code}).",
            f"SOURCE TITLE: {article.display_title}",
            f"SOURCE TYPE: {article.kind.value}",
            "",
            "SCRIPT (for context):",
            truncate_text(script.narration_text, 2000),
            "",
            "Respond with JSON only, using exactly these keys:",
            '{ "title": string, "description": string, "tags": [string] }',
            "",
            "RULES:",
            "- title: catchy, specific, at most 70 characters, no quotes or emoji.",
            "- description: 2-3 sentences, at most 350 characters, written as show notes.",
            f"- tags: 3 to {max_tags} short lowercase keywords, no '#' characters.",
        ]
    )


def fallback_metadata(article: Article, *, language: str = "en") -> EpisodeMetadata:
    """Deterministic metadata used when the model output is unusable."""
    title = truncate_text(clean_text(article.display_title), 70, suffix="...")
    description_source = (
        f"A podcast episode based on {article.display_title}."
        if article.kind.value != "url"
        else f"An AI-narrated summary of {article.display_title}."
    )
    return EpisodeMetadata(
        title=title or "Untitled Episode",
        description=truncate_text(description_source, 350, suffix="..."),
        tags=[],
        language=config.get_language(language).code,
    )


def metadata_from_raw(
    raw: str, article: Article, *, language: str = "en"
) -> EpisodeMetadata:
    """Parse model JSON into :class:`EpisodeMetadata`, falling back safely."""
    payload = parse_json_object(raw)
    if not payload:
        LOGGER.warning("Metadata JSON could not be parsed; using fallback metadata.")
        return fallback_metadata(article, language=language)

    fallback = fallback_metadata(article, language=language)
    title = truncate_text(clean_text(str(payload.get("title", ""))), 70, suffix="...")
    description = truncate_text(
        clean_text(str(payload.get("description", ""))), 350, suffix="..."
    )
    tags = [
        tag.lower().lstrip("#")
        for tag in coerce_str_list(payload.get("tags"), limit=config.METADATA_MAX_TAGS)
    ]
    return EpisodeMetadata(
        title=title or fallback.title,
        description=description or fallback.description,
        tags=tags,
        language=fallback.language,
    )


def generate_metadata(
    article: Article,
    script: PodcastScript,
    *,
    generator: Optional[TextGenerator] = None,
    api_key: str = "",
    model_id: str = config.DEFAULT_LLM_MODEL,
    language: str = "en",
    attempts: Optional[int] = None,
) -> EpisodeMetadata:
    """Generate the episode title, description and tags (Feature 6).

    Any failure degrades to deterministic metadata rather than aborting the
    pipeline, because an untitled episode is worse than a generic title.
    """
    lang_code = config.get_language(language).code
    prompt = build_metadata_prompt(article, script, language=language)
    try:
        raw = generate_text(
            prompt,
            generator=generator,
            api_key=api_key,
            model_id=model_id,
            attempts=attempts,
            description="episode metadata",
        )
    except ScriptGenerationError as exc:
        LOGGER.warning("Metadata generation failed (%s); using fallback.", exc)
        return fallback_metadata(article, language=lang_code)

    metadata = metadata_from_raw(raw, article, language=lang_code)
    LOGGER.info(
        "Episode metadata ready: '%s' (%d tag(s))", metadata.title, len(metadata.tags)
    )
    return metadata
