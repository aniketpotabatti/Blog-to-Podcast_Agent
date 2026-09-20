"""
Blog to Podcast Agent — Streamlit UI
====================================
A Streamlit web application that transforms blog posts, PDFs and RSS feeds into
AI-narrated, music-bedded podcasts ready to publish.

Built on the ``podcast`` package which provides the full pipeline:
ingestion, script generation, TTS synthesis, audio mixing and publishing.

Author: Aniket Potabatti (@aniketpotabatti)
Created: Aug 2025
License: MIT License
"""

from __future__ import annotations

import os

import streamlit as st

from podcast import config
from podcast.errors import PodcastError
from podcast.models import Host
from podcast.pipeline import PodcastPipeline, build_options
from podcast.ui_styles import build_css
from podcast.utils import setup_logging

setup_logging()

# ─────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Blog to Podcast · AI Agent",
    page_icon="🎙️",
    layout="centered",
)
st.markdown(build_css(), unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  Hero section
# ─────────────────────────────────────────────
st.markdown(
    """
    <div class="hero-card">
        <div class="hero-icon">🎙️</div>
        <div class="hero-title">Blog to Podcast · AI Agent</div>
        <div class="hero-sub">Turn any article into a studio-quality podcast in seconds</div>
        <div class="hero-badges">
            <span class="pill">🌐 URL · PDF · RSS</span>
            <span class="pill">🧠 Solo &amp; two-host scripts</span>
            <span class="pill">🌍 15 languages</span>
            <span class="pill">🎙️ Multi-voice dialogue</span>
            <span class="pill">🎵 Music beds</span>
            <span class="pill">🏷️ Auto titles</span>
            <span class="pill">🚀 One-click publish</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
SOURCES = {"🌐 URL": "url", "📄 PDF": "pdf", "📡 RSS entry": "rss"}


def env_key(name: str) -> str:
    """Read an API key from the environment as a sidebar default."""
    return os.environ.get(name, "")


def init_session() -> None:
    """Make sure every piece of session state exists before use."""
    defaults = {
        "article": None,  # Article | None
        "episode": None,  # EpisodeResult | None
        "feed_entries": [],  # list[FeedEntry]
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def voice_label(voice) -> str:
    """Human readable label for a configured voice."""
    return f"{voice.name} — {voice.description}"


def voice_id_from_label(label: str) -> str:
    """Map a selected voice label back to its ElevenLabs voice id."""
    for voice in config.VOICES:
        if voice_label(voice) == label:
            return voice.voice_id
    return config.DEFAULT_VOICE_ID


def build_hosts(style_key: str, first_id: str, second_id: str = "") -> list[Host]:
    """Create Host entries for a style, filling any gaps with defaults."""
    defaults = config.default_hosts(style_key)
    picked = [first_id, second_id]
    hosts: list[Host] = []
    for index, default_voice in enumerate(defaults):
        voice_id = default_voice.voice_id
        if index < len(picked) and picked[index]:
            voice_id = picked[index]
        hosts.append(Host(name=default_voice.name, voice_id=voice_id))
    return hosts


def make_pipeline(keys: dict, status) -> PodcastPipeline:
    """Create a pipeline wired to the sidebar keys and a status indicator."""

    def progress(stage: str, detail: str = "") -> None:
        label = f"{stage}…" if not detail else f"{stage} · {detail}"
        status.update(label=label, state="running")

    return PodcastPipeline(
        gemini_api_key=keys.get("gemini", ""),
        firecrawl_api_key=keys.get("firecrawl", ""),
        elevenlabs_api_key=keys.get("elevenlabs", ""),
        progress=progress,
    )


def sidebar_keys() -> dict:
    """Collect the three provider keys, defaulting to environment values."""
    gemini = st.text_input(
        "Google Gemini",
        value=env_key("GEMINI_API_KEY"),
        type="password",
        help="Scripts & metadata — aistudio.google.com/apikey",
    )
    firecrawl = st.text_input(
        "Firecrawl",
        value=env_key("FIRECRAWL_API_KEY"),
        type="password",
        help="Article scraping — firecrawl.dev",
    )
    elevenlabs = st.text_input(
        "ElevenLabs",
        value=env_key("ELEVENLABS_API_KEY"),
        type="password",
        help="Speech & music — elevenlabs.io",
    )
    keys_ok = all([gemini.strip(), firecrawl.strip(), elevenlabs.strip()])
    if keys_ok:
        st.markdown(
            '<div class="section-label">✅ All keys detected</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="section-label">⚠️ All three keys are required</div>',
            unsafe_allow_html=True,
        )
    return {
        "gemini": gemini.strip(),
        "firecrawl": firecrawl.strip(),
        "elevenlabs": elevenlabs.strip(),
        "ok": keys_ok,
    }


def render_sidebar():
    """Renders the sidebar with API keys and episode settings."""
    with st.sidebar:
        st.markdown('<div class="section-label">🔑 API keys</div>', unsafe_allow_html=True)
        keys = sidebar_keys()

        st.divider()
        st.markdown(
            '<div class="section-label">🎚️ Episode settings</div>', unsafe_allow_html=True
        )
        style_label = st.selectbox(
            "Podcast style",
            list(config.STYLE_LABELS),
            help="Dialogue styles write a two-host conversation",
        )
        language_label = st.selectbox("Language", list(config.LANGUAGE_LABELS))
        style = config.get_style(style_label)

        voice_labels = [voice_label(voice) for voice in config.VOICES]
        host_one = st.selectbox("Voice — host 1", voice_labels)
        if style.host_count >= 2:
            host_two = st.selectbox(
                "Voice — host 2",
                voice_labels,
                index=min(1, len(voice_labels) - 1),
            )
        else:
            host_two = ""

        music_label = st.selectbox(
            "Background music",
            list(config.MUSIC_LABELS),
            help="Instrumental bed generated once, then mixed locally (no ffmpeg needed)",
        )
        auto_metadata = st.checkbox("Auto title & description", value=True)

        st.caption(
            "Keys stay in this browser session only — nothing is stored or logged."
        )

    return {
        "keys": keys,
        "style": style,
        "language_code": config.get_language(language_label).code,
        "hosts": build_hosts(
            style.key,
            voice_id_from_label(host_one),
            voice_id_from_label(host_two),
        ),
        "voice_id": voice_id_from_label(host_one),
        "music_preset": config.get_music_preset(music_label).key,
        "auto_metadata": auto_metadata,
    }


def render_main_tabs(settings: dict):
    """Renders the main application tabs."""
    tab_generate, tab_batch, tab_publish, tab_about = st.tabs(
        ["🎙️ Generate", "📡 RSS monitor", "📤 Publish", "ℹ️ About"]
    )

    with tab_generate:
        render_generate_tab(settings)
    with tab_batch:
        render_batch_tab(settings)
    with tab_publish:
        render_publish_tab(settings)
    with tab_about:
        render_about_tab()


def render_generate_tab(settings: dict):
    """Renders the generation tab content."""
    source = st.radio("Source", list(SOURCES), horizontal=True)
    kind = SOURCES[source]
    url = ""
    uploaded = None
    feed_url = ""
    if kind == "url":
        url = st.text_input("Article URL", placeholder="https://example.com/my-post")
    elif kind == "pdf":
        uploaded = st.file_uploader(
            "PDF document (research paper, report, newsletter…)", type=["pdf"]
        )
    else:
        feed_url = st.text_input(
            "RSS / Atom feed URL",
            placeholder="https://example.com/feed.xml",
            help="The newest entry is turned into an episode",
        )

    source_ready = (
        (kind == "url" and bool(url.strip()))
        or (kind == "pdf" and uploaded is not None)
        or (kind == "rss" and bool(feed_url.strip()))
    )
    run_clicked = st.button(
        "✨ Generate Podcast",
        type="primary",
        disabled=not (settings["keys"]["ok"] and source_ready),
        use_container_width=True,
    )

    if run_clicked and settings["keys"]["ok"]:
        try:
            with st.status("Working on your episode…", expanded=True) as status:
                pipeline = make_pipeline(settings["keys"], status)

                if kind == "url":
                    article = pipeline.load_from_url(url.strip())
                elif kind == "pdf":
                    article = pipeline.load_from_pdf(
                        uploaded.getvalue(), filename=uploaded.name
                    )
                else:
                    entries = pipeline.list_feed_entries(feed_url.strip(), limit=5)
                    st.write(f"Newest entry: {entries[0].title}")
                    article = pipeline.load_from_feed_entry(entries[0])
                st.session_state["article"] = article

                options = build_options(
                    style=settings["style"].key,
                    language=settings["language_code"],
                    hosts=settings["hosts"],
                    voice_id=settings["voice_id"],
                    music_preset=settings["music_preset"],
                    generate_metadata=settings["auto_metadata"],
                )
                episode = pipeline.generate(article, options)
                st.session_state["episode"] = episode
                status.update(
                    label="Episode ready 🎧", state="complete", expanded=False
                )
        except PodcastError as exc:
            st.error(exc.message)
            if exc.hint:
                st.info(f"💡 {exc.hint}")
        except Exception as exc:  # unexpected - surfaced for debugging
            st.exception(exc)

    render_episode_result(st.session_state.get("article"), st.session_state.get("episode"))


def render_episode_result(article, episode):
    """Renders the result of a generation."""
    if article is not None:
        with st.expander("📄 Source preview", expanded=False):
            st.markdown(f"**{article.display_title}**")
            st.caption(f"{article.word_count} words · source: {article.kind.value}")
            preview = article.text[:1200]
            st.text(preview + ("…" if len(article.text) > 1200 else ""))

    if episode is not None and episode.has_audio:
        st.markdown('<div class="result-card">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="result-title">🎧 {episode.metadata.title}</div>',
            unsafe_allow_html=True,
        )
        if episode.metadata.description:
            st.caption(episode.metadata.description)
        st.audio(episode.audio_bytes, format=episode.audio_format)
        st.download_button(
            "⬇️  Download MP3",
            data=episode.audio_bytes,
            file_name=episode.audio_filename,
            mime=episode.audio_format,
            use_container_width=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        words = len(episode.script.narration_text.split())
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Duration", episode.duration_label)
        col2.metric("Words", words)
        col3.metric("Speakers", "2 hosts" if episode.script.is_dialogue else "Solo")
        col4.metric("Music", episode.music_preset)

        with st.expander("📝 Script", expanded=False):
            st.text(episode.script.text)
        with st.expander("🏷️ Episode metadata", expanded=False):
            st.write(episode.metadata.title)
            st.write(episode.metadata.description)
            st.write(", ".join(episode.metadata.tags) or "—")


def render_batch_tab(settings: dict):
    """Renders the batch tab content."""
    st.caption(
        "Watch a feed and turn its newest unprocessed entries into episodes. "
        "Already-generated items are tracked in `outputs/rss_state.json`."
    )
    batch_feed = st.text_input(
        "Feed URL", key="batch_feed", placeholder="https://example.com/feed.xml"
    )
    batch_limit = st.slider("Episodes per run", 1, 10, 2)
    col_a, col_b = st.columns(2)
    with col_a:
        preview_clicked = st.button(
            "👀 Preview newest entries",
            disabled=not (settings["keys"]["ok"] and batch_feed.strip()),
            use_container_width=True,
        )
    with col_b:
        batch_clicked = st.button(
            "⚙️ Generate batch",
            disabled=not (settings["keys"]["ok"] and batch_feed.strip()),
            use_container_width=True,
        )

    if preview_clicked and settings["keys"]["ok"]:
        try:
            with st.status("Checking feed…", expanded=True) as status:
                pipeline = make_pipeline(settings["keys"], status)
                st.session_state["feed_entries"] = pipeline.list_feed_entries(
                    batch_feed.strip(), limit=batch_limit
                )
        except PodcastError as exc:
            st.error(exc.message)
            if exc.hint:
                st.info(f"💡 {exc.hint}")

    for entry in st.session_state.get("feed_entries") or []:
        st.markdown(f"- **{entry.title or entry.link}** — {entry.link or 'no link'}")

    if batch_clicked and settings["keys"]["ok"]:
        try:
            with st.status("Generating batch…", expanded=True) as status:
                pipeline = make_pipeline(settings["keys"], status)
                options = build_options(
                    style=settings["style"].key,
                    language=settings["language_code"],
                    hosts=settings["hosts"],
                    voice_id=settings["voice_id"],
                    music_preset=settings["music_preset"],
                    generate_metadata=settings["auto_metadata"],
                )
                episodes = pipeline.generate_from_feed(
                    batch_feed.strip(), options, limit=batch_limit
                )
            if episodes:
                for generated in episodes:
                    st.success(
                        f"✅ {generated.metadata.title} — {generated.duration_label}"
                    )
                latest = episodes[-1]
                st.session_state["episode"] = latest
                st.session_state["article"] = latest.article
            else:
                st.info("Nothing new to process — every entry was already generated.")
        except PodcastError as exc:
            st.error(exc.message)
            if exc.hint:
                st.info(f"💡 {exc.hint}")


def render_publish_tab(settings: dict):
    """Renders the publish tab content."""
    published_episode = st.session_state.get("episode")
    if published_episode is None or not published_episode.has_audio:
        st.info("Generate an episode first — publishing works on the latest result.")
    else:
        st.markdown(f"**Ready to publish:** {published_episode.metadata.title}")
        selected_labels = st.multiselect(
            "Destinations",
            list(config.PLATFORM_LABELS),
            default=[config.PLATFORM_LABELS[0]],
            help="RSS is how Spotify, Apple Podcasts and YouTube Music ingest shows",
        )
        base_url = st.text_input(
            "Public base URL for the feed",
            placeholder="https://myserver.com/podcast",
            help="Makes enclosure URLs absolute (required by Spotify)",
        )
        webhook_url = st.text_input(
            "Webhook endpoint",
            placeholder="https://hooks.zapier.com/…",
            help="POSTs the MP3 plus metadata (Zapier, Make.com, custom APIs)",
        )
        privacy = st.selectbox("YouTube privacy", ["private", "unlisted", "public"])

        if st.button(
            "🚀 Publish episode",
            type="primary",
            disabled=not selected_labels,
            use_container_width=True,
        ):
            platform_keys = [
                config.get_platform(label).key for label in selected_labels
            ]
            try:
                with st.status("Publishing…", expanded=True) as status:
                    pipeline = make_pipeline(settings["keys"], status)
                    results = pipeline.publish(
                        published_episode,
                        platform_keys,
                        webhook_url=webhook_url.strip(),
                        feed_base_url=base_url.strip(),
                        youtube_privacy=privacy,
                    )
                for result in results:
                    detail = result.message + (f" → {result.url}" if result.url else "")
                    if result.ok:
                        st.success(f"**{result.platform}** — {detail}")
                    else:
                        st.error(f"**{result.platform}** — {detail}")
            except PodcastError as exc:
                st.error(exc.message)
                if exc.hint:
                    st.info(f"💡 {exc.hint}")


def render_about_tab():
    """Renders the about tab content."""
    st.markdown(
        """
        **What this app does**

        - 🌐 **Any source** — blog URLs, uploaded PDFs & research papers, RSS feeds.
        - 🧠 **Smart scripts** — Gemini writes solo monologues or two-host dialogues.
        - 🌍 **Multilingual** — 15 languages; the multilingual voice model is picked automatically.
        - 🎙️ **True multi-voice** — dialogue episodes keep a distinct voice per host.
        - 🎵 **Music** — intro/outro stings and continuous underlays, mixed without ffmpeg.
        - 🏷️ **Auto metadata** — episode title, description and tags are generated for you.
        - 🚀 **Publishing** — local archive, RSS feed (the Spotify/Apple route), YouTube, webhooks.
        """
    )
    st.caption(
        "Configuration lives in `podcast/config.py` · logs in `outputs/logs/app.log` · "
        "published episodes in `outputs/episodes/`."
    )


# ─────────────────────────────────────────────
#  App entry
# ─────────────────────────────────────────────
init_session()
settings = render_sidebar()
render_main_tabs(settings)
st.markdown(
    '<div class="app-footer">Blog to Podcast Agent · <strong>Gemini</strong> + '
    "<strong>Firecrawl</strong> + <strong>ElevenLabs</strong> · MIT License</div>",
    unsafe_allow_html=True,
)
