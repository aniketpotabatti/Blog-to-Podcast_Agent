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
from typing import List

import streamlit as st

from podcast import config
from podcast.errors import PodcastError
from podcast.models import Host
from podcast.pipeline import PodcastPipeline, build_options
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
# ─────────────────────────────────────────────
#  Custom CSS – dark glassmorphism theme
# ─────────────────────────────────────────────
st.markdown("""<style>
/* ════════════════════════════════════════════════════════════
   Blog to Podcast · Design system
   Palette : indigo night · violet → fuchsia accent
   Type    : Inter 300–800 · 8px spacing rhythm
   ════════════════════════════════════════════════════════════ */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

:root {
    --bg-0: #0b0a1f;
    --bg-1: #131034;
    --bg-2: #0a1626;
    --surface: rgba(255, 255, 255, 0.045);
    --surface-strong: rgba(255, 255, 255, 0.075);
    --line: rgba(255, 255, 255, 0.09);
    --line-strong: rgba(255, 255, 255, 0.17);
    --text-hi: #f4f2ff;
    --text-mid: rgba(244, 242, 255, 0.62);
    --text-lo: rgba(244, 242, 255, 0.40);
    --accent: #a78bfa;
    --accent-2: #e879f9;
    --accent-soft: rgba(167, 139, 250, 0.16);
    --radius-lg: 22px;
    --radius-md: 16px;
    --radius-sm: 12px;
}

/* ── Base & typography ── */
html, body, [class*="css"], .stApp, .stApp p, .stApp li {
    font-family: 'Inter', sans-serif;
    letter-spacing: 0.01em;
}
.stApp {
    color: var(--text-hi);
    background:
        radial-gradient(900px 520px at 85% -12%, rgba(167, 139, 250, 0.16), transparent 62%),
        radial-gradient(720px 420px at -12% 112%, rgba(232, 121, 249, 0.10), transparent 60%),
        linear-gradient(140deg, var(--bg-0) 0%, var(--bg-1) 52%, var(--bg-2) 100%);
    min-height: 100vh;
}
.stApp p, .stApp li { color: var(--text-mid); line-height: 1.6; }
.stApp strong { color: var(--text-hi); font-weight: 600; }
.stApp a { color: #c4b5fd; text-decoration: none; }

/* ── Chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container {
    padding-top: 2.2rem;
    padding-bottom: 3.2rem;
    max-width: 880px;
}

/* ── Section labels (left-aligned, tracked) ── */
.section-label {
    font-size: 0.70rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--text-lo);
    margin: 0 0 0.55rem;
    text-align: left;
}

/* ── Hero ── */
.hero-card {
    text-align: center;
    padding: 2.6rem 2.4rem 2.2rem;
    margin: 0 auto 0.9rem;
    border-radius: var(--radius-lg);
    background:
        linear-gradient(rgba(19, 16, 52, 0.72), rgba(19, 16, 52, 0.72)) padding-box,
        linear-gradient(135deg, rgba(167, 139, 250, 0.55), rgba(232, 121, 249, 0.35), rgba(103, 232, 249, 0.25)) border-box;
    border: 1px solid transparent;
    box-shadow: 0 24px 60px rgba(4, 2, 20, 0.55);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
}
.hero-icon {
    font-size: 3rem;
    line-height: 1;
    margin-bottom: 0.7rem;
    filter: drop-shadow(0 6px 18px rgba(167, 139, 250, 0.45));
}
.hero-title {
    font-size: 2.1rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin: 0 0 0.5rem;
    background: linear-gradient(100deg, #ffffff 0%, #d8ccff 55%, #f5d0fe 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
.hero-sub {
    font-size: 0.98rem;
    font-weight: 400;
    color: var(--text-mid);
    margin: 0 auto 1.15rem;
    max-width: 560px;
    line-height: 1.55;
}

/* ── Feature pills (centered chips) ── */
.hero-badges {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.45rem;
}
.pill {
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: #ddd6fe;
    background: rgba(167, 139, 250, 0.12);
    border: 1px solid rgba(167, 139, 250, 0.28);
    border-radius: 999px;
    padding: 0.28rem 0.75rem;
    white-space: nowrap;
}

/* ── Text inputs & areas ── */
.stTextInput input, .stTextArea textarea {
    background: var(--surface) !important;
    border: 1px solid var(--line) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-hi) !important;
    font-size: 0.94rem !important;
    padding: 0.72rem 1rem !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: rgba(167, 139, 250, 0.65) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
    outline: none !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {
    color: var(--text-lo) !important;
}

/* ── Selects & multiselect ── */
.stSelectbox > div > div, .stMultiSelect > div > div {
    background: var(--surface) !important;
    border: 1px solid var(--line) !important;
    border-radius: var(--radius-sm) !important;
    transition: border-color 0.18s ease;
}
.stSelectbox > div > div:hover, .stMultiSelect > div > div:hover {
    border-color: var(--line-strong) !important;
}
.stSelectbox span, .stMultiSelect span {
    color: var(--text-hi) !important;
    font-size: 0.94rem !important;
}
.stMultiSelect span[data-baseweb="tag"] {
    background: var(--accent-soft) !important;
    border: 1px solid rgba(167, 139, 250, 0.35) !important;
    color: #e9d5ff !important;
    border-radius: 8px !important;
}

/* ── File uploader ── */
.stFileUploader > div > div > div > div {
    background: var(--surface) !important;
    border: 1.5px dashed var(--line-strong) !important;
    border-radius: var(--radius-md) !important;
    padding: 2rem !important;
    text-align: center !important;
    transition: all 0.18s ease;
}
.stFileUploader > div > div > div > div:hover {
    border-color: rgba(167, 139, 250, 0.55) !important;
    background: var(--surface-strong) !important;
}
.stFileUploader span, .stFileUploader small { color: var(--text-mid) !important; }

/* ── Radio as soft chips ── */
[role="radiogroup"] {
    gap: 0.4rem !important;
}
[role="radiogroup"] label {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 0.32rem 0.8rem 0.32rem 0.55rem;
    transition: all 0.18s ease;
}
[role="radiogroup"] label:hover {
    border-color: var(--line-strong);
    background: var(--surface-strong);
}
[role="radiogroup"] label p, [role="radiogroup"] label span {
    color: var(--text-mid) !important;
    font-size: 0.9rem !important;
}

/* ── Checkbox ── */
.stCheckbox span { color: var(--text-mid) !important; font-size: 0.9rem; }

/* ── Slider ── */
.stSlider [role="slider"] {
    background: #ffffff !important;
    border: 3px solid rgba(167, 139, 250, 0.9) !important;
}
.stSlider [data-baseweb="slider"] > div {
    background: var(--accent-soft) !important;
}
.stSlider span { color: var(--text-mid) !important; font-size: 0.85rem; }

/* ── Expanders (glass cards) ── */
[data-testid="stExpander"] {
    background: var(--surface) !important;
    border: 1px solid var(--line) !important;
    border-radius: var(--radius-md) !important;
    overflow: hidden;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    color: var(--text-hi) !important;
}
[data-testid="stExpander"] summary:hover { color: #ddd6fe !important; }

/* ── Tabs (pill navigation) ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    border-bottom: 1px solid var(--line);
    padding-bottom: 0.4rem;
}
.stTabs [data-baseweb="tab"] {
    background: var(--surface) !important;
    border: 1px solid transparent;
    border-radius: 999px !important;
    padding: 0.45rem 1.15rem !important;
    transition: all 0.18s ease;
}
.stTabs [data-baseweb="tab"] p {
    font-size: 0.9rem !important;
    font-weight: 600;
    color: var(--text-mid) !important;
}
.stTabs [data-baseweb="tab"]:hover { background: var(--surface-strong) !important; }
.stTabs [aria-selected="true"] {
    background: var(--accent-soft) !important;
    border-color: rgba(167, 139, 250, 0.45);
}
.stTabs [aria-selected="true"] p { color: var(--text-hi) !important; }
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ── Buttons ── */
.stButton > button {
    border-radius: var(--radius-sm) !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    padding: 0.62rem 1.4rem !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(120deg, #8b5cf6 0%, #a855f7 55%, #d946ef 100%) !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: 0 10px 26px rgba(139, 92, 246, 0.35);
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1.5px);
    filter: brightness(1.06);
    box-shadow: 0 14px 32px rgba(139, 92, 246, 0.45);
}
.stButton > button:not([kind="primary"]) {
    background: var(--surface) !important;
    color: var(--text-hi) !important;
    border: 1px solid var(--line) !important;
}
.stButton > button:not([kind="primary"]):hover {
    border-color: var(--line-strong) !important;
    transform: translateY(-1.5px);
}

/* ── Download button (full-width ghost) ── */
.stDownloadButton > button {
    width: 100%;
    border-radius: var(--radius-sm) !important;
    font-weight: 700 !important;
    background: var(--surface-strong) !important;
    color: var(--text-hi) !important;
    border: 1px solid rgba(167, 139, 250, 0.4) !important;
    transition: all 0.15s ease;
}
.stDownloadButton > button:hover {
    border-color: rgba(167, 139, 250, 0.75) !important;
    transform: translateY(-1.5px);
}

/* ── Metrics (stat cards) ── */
[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    padding: 0.85rem 1.05rem 0.7rem;
}
[data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] {
    font-size: 0.66rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-lo) !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.35rem !important;
    font-weight: 700 !important;
    color: var(--text-hi) !important;
}

/* ── Status widget ── */
[data-testid="stStatusWidget"] {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
}

/* ── Result card (gradient border) ── */
.result-card {
    text-align: center;
    padding: 1.8rem 1.6rem;
    margin-top: 1.4rem;
    border-radius: var(--radius-lg);
    background:
        linear-gradient(rgba(19, 16, 52, 0.72), rgba(19, 16, 52, 0.72)) padding-box,
        linear-gradient(135deg, rgba(167, 139, 250, 0.5), rgba(232, 121, 249, 0.3)) border-box;
    border: 1px solid transparent;
    box-shadow: 0 18px 44px rgba(4, 2, 20, 0.45);
}
.result-title {
    font-size: 1.35rem;
    font-weight: 700;
    color: var(--text-hi);
    margin: 0 0 0.4rem;
    letter-spacing: -0.01em;
}

/* ── Audio player ── */
.stAudio, .stAudio > div {
    border-radius: var(--radius-md) !important;
    overflow: hidden;
}

/* ── Sidebar panel ── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(16, 13, 44, 0.96), rgba(11, 10, 31, 0.96));
    border-right: 1px solid var(--line);
}
section[data-testid="stSidebar"] hr {
    border-color: var(--line) !important;
    margin: 1.1rem 0;
}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
    font-size: 0.72rem !important;
    color: var(--text-lo) !important;
    line-height: 1.5;
}

/* ── Centered footer ── */
.app-footer {
    text-align: center;
    font-size: 0.78rem;
    color: var(--text-lo);
    padding-top: 0.4rem;
}
.app-footer strong { color: var(--text-mid); font-weight: 600; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: rgba(167, 139, 250, 0.25);
    border-radius: 8px;
    border: 2px solid transparent;
    background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover {
    background: rgba(167, 139, 250, 0.45);
    background-clip: content-box;
}

/* ── Mobile ── */
@media (max-width: 640px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; }
    .hero-card { padding: 1.7rem 1.1rem 1.4rem; }
    .hero-title { font-size: 1.6rem; }
    .hero-sub { font-size: 0.9rem; }
    .stTabs [data-baseweb="tab"] { padding: 0.4rem 0.8rem !important; }
    .stTabs [data-baseweb="tab"] p { font-size: 0.8rem !important; }
}
</style>""", unsafe_allow_html=True)

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
def env_key(name: str) -> str:
    """Read an API key from the environment as a sidebar default."""
    return os.environ.get(name, "")


def init_session() -> None:
    """Make sure every piece of session state exists before use."""
    defaults = {
        "article": None,      # Article | None
        "episode": None,      # EpisodeResult | None
        "feed_entries": [],   # list[FeedEntry]
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


def build_hosts(style_key: str, first_id: str, second_id: str = "") -> List[Host]:
    """Create Host entries for a style, filling any gaps with defaults."""
    defaults = config.default_hosts(style_key)
    picked = [first_id, second_id]
    hosts: List[Host] = []
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
        st.markdown('<div class="section-label">✅ All keys detected</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="section-label">⚠️ All three keys are required</div>',
                    unsafe_allow_html=True)
    return {
        "gemini": gemini.strip(),
        "firecrawl": firecrawl.strip(),
        "elevenlabs": elevenlabs.strip(),
        "ok": keys_ok,
    }


SOURCES = {"🌐 URL": "url", "📄 PDF": "pdf", "📡 RSS entry": "rss"}

init_session()

# ─────────────────────────────────────────────
#  Sidebar – credentials & episode settings
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="section-label">🔑 API keys</div>', unsafe_allow_html=True)
    keys = sidebar_keys()

    st.divider()
    st.markdown('<div class="section-label">🎚️ Episode settings</div>', unsafe_allow_html=True)
    style_label = st.selectbox(
        "Podcast style", list(config.STYLE_LABELS),
        help="Dialogue styles write a two-host conversation",
    )
    language_label = st.selectbox("Language", list(config.LANGUAGE_LABELS))
    style = config.get_style(style_label)

    voice_labels = [voice_label(voice) for voice in config.VOICES]
    host_one = st.selectbox("Voice — host 1", voice_labels)
    if style.host_count >= 2:
        host_two = st.selectbox(
            "Voice — host 2", voice_labels, index=min(1, len(voice_labels) - 1)
        )
    else:
        host_two = ""

    music_label = st.selectbox(
        "Background music", list(config.MUSIC_LABELS),
        help="Instrumental bed generated once, then mixed locally (no ffmpeg needed)",
    )
    auto_metadata = st.checkbox("Auto title & description", value=True)

    st.caption("Keys stay in this browser session only — nothing is stored or logged.")

keys_ok = keys["ok"]


def make_options():
    """Build pipeline options from the sidebar selections (single source of truth)."""
    return build_options(
        style=style.key,
        language=config.get_language(language_label).code,
        hosts=build_hosts(
            style.key,
            voice_id_from_label(host_one),
            voice_id_from_label(host_two),
        ),
        voice_id=voice_id_from_label(host_one),
        music_preset=config.get_music_preset(music_label).key,
        generate_metadata=auto_metadata,
    )
# ─────────────────────────────────────────────
#  Main area – tabs
# ─────────────────────────────────────────────
tab_generate, tab_batch, tab_publish, tab_about = st.tabs(
    ["🎙️ Generate", "📡 RSS monitor", "📤 Publish", "ℹ️ About"]
)

with tab_generate:
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
        "✨ Generate podcast",
        type="primary",
        disabled=not (keys_ok and source_ready),
        use_container_width=True,
    )

    if run_clicked and keys_ok:
        try:
            with st.status("Working on your episode…", expanded=True) as status:
                pipeline = make_pipeline(keys, status)

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

                episode = pipeline.generate(article, make_options())
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
    article = st.session_state.get("article")
    episode = st.session_state.get("episode")

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

with tab_batch:
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
            disabled=not (keys_ok and batch_feed.strip()),
            use_container_width=True,
        )
    with col_b:
        batch_clicked = st.button(
            "⚙️ Generate batch",
            disabled=not (keys_ok and batch_feed.strip()),
            use_container_width=True,
        )

    if preview_clicked and keys_ok:
        try:
            with st.status("Checking feed…", expanded=True) as status:
                pipeline = make_pipeline(keys, status)
                st.session_state["feed_entries"] = pipeline.list_feed_entries(
                    batch_feed.strip(), limit=batch_limit
                )
        except PodcastError as exc:
            st.error(exc.message)
            if exc.hint:
                st.info(f"💡 {exc.hint}")

    for entry in st.session_state.get("feed_entries") or []:
        st.markdown(f"- **{entry.title or entry.link}** — {entry.link or 'no link'}")

    if batch_clicked and keys_ok:
        try:
            with st.status("Generating batch…", expanded=True) as status:
                pipeline = make_pipeline(keys, status)
                episodes = pipeline.generate_from_feed(
                    batch_feed.strip(), make_options(), limit=batch_limit
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
with tab_publish:
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
                    pipeline = make_pipeline(keys, status)
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

with tab_about:
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

st.markdown(
    '<div class="app-footer">Blog to Podcast Agent · <strong>Gemini</strong> + '
    "<strong>Firecrawl</strong> + <strong>ElevenLabs</strong> · MIT License</div>",
    unsafe_allow_html=True,
)