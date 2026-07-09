"""
Blog to Podcast Agent
=====================
A Streamlit web application that seamlessly transforms blog posts into AI-narrated podcasts.
This script orchestrates web scraping, AI summarization, and Text-to-Speech synthesis.

Author: Aniket Potabatti (@aniketpotabatti)
Created: December 31, 2025
License: MIT License
"""

import os
from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.models.google import Gemini
from agno.tools.firecrawl import FirecrawlTools
from elevenlabs import ElevenLabs
import streamlit as st

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
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Global reset ── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── App background ── */
.stApp {
    background: linear-gradient(135deg, #0f0c29 0%, #1a1040 50%, #0d1b2a 100%);
    min-height: 100vh;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container {
    padding-top: 2rem;
    padding-bottom: 4rem;
    max-width: 760px;
}

/* ── Hero card ── */
.hero-card {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 24px;
    padding: 2.5rem 2.5rem 2rem;
    margin-bottom: 2rem;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    text-align: center;
}
.hero-icon {
    font-size: 3.2rem;
    line-height: 1;
    margin-bottom: 0.6rem;
}
.hero-title {
    font-size: 2rem;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.5px;
    margin: 0 0 0.4rem;
}
.hero-sub {
    font-size: 0.95rem;
    color: rgba(255,255,255,0.50);
    margin: 0;
    font-weight: 400;
}

/* ── Section label ── */
.section-label {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.35);
    margin-bottom: 0.4rem;
}

/* ── URL input override ── */
.stTextInput > div > div > input {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 14px !important;
    color: #ffffff !important;
    font-size: 0.95rem !important;
    padding: 0.75rem 1.1rem !important;
    transition: border-color 0.2s;
}
.stTextInput > div > div > input:focus {
    border-color: rgba(139, 92, 246, 0.70) !important;
    box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.15) !important;
}
.stTextInput > div > div > input::placeholder {
    color: rgba(255,255,255,0.25) !important;
}
.stTextInput label {
    color: rgba(255,255,255,0.60) !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
}

/* ── Generate button ── */
.stButton > button {
    width: 100% !important;
    background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 14px !important;
    padding: 0.8rem 2rem !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
    transition: opacity 0.2s, transform 0.15s !important;
    cursor: pointer !important;
    margin-top: 0.5rem;
}
.stButton > button:hover:not([disabled]) {
    opacity: 0.88 !important;
    transform: translateY(-1px) !important;
}
.stButton > button[disabled] {
    opacity: 0.35 !important;
    cursor: not-allowed !important;
}

/* ── Download button ── */
.stDownloadButton > button {
    background: rgba(255,255,255,0.07) !important;
    color: rgba(255,255,255,0.80) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 12px !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    padding: 0.55rem 1.2rem !important;
    transition: background 0.2s !important;
}
.stDownloadButton > button:hover {
    background: rgba(255,255,255,0.12) !important;
}

/* ── Spinner text ── */
.stSpinner > div { color: rgba(255,255,255,0.60) !important; }

/* ── Result card ── */
.result-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(139, 92, 246, 0.25);
    border-radius: 20px;
    padding: 1.8rem;
    margin-top: 1.5rem;
}
.result-title {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #a78bfa;
    margin-bottom: 1rem;
}

/* ── Audio player ── */
.stAudio {
    border-radius: 12px;
    overflow: hidden;
}
audio {
    width: 100%;
    border-radius: 12px;
    background: transparent;
}

/* ── Expander (summary) ── */
.stExpander {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 14px !important;
    margin-top: 1rem;
}
.stExpander summary {
    color: rgba(255,255,255,0.55) !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
}
.stExpander p {
    color: rgba(255,255,255,0.75) !important;
    font-size: 0.93rem !important;
    line-height: 1.7 !important;
}

/* ── Alerts ── */
.stSuccess, .stWarning, .stError, .stInfo {
    border-radius: 14px !important;
    font-size: 0.90rem !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: rgba(15, 12, 41, 0.92) !important;
    border-right: 1px solid rgba(255,255,255,0.07) !important;
}
[data-testid="stSidebar"] .stTextInput > div > div > input {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 10px !important;
    color: #fff !important;
    font-size: 0.88rem !important;
}
[data-testid="stSidebar"] label {
    color: rgba(255,255,255,0.55) !important;
    font-size: 0.82rem !important;
}
.sidebar-header {
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.28);
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(255,255,255,0.07);
}
.key-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.80rem;
    color: rgba(255,255,255,0.40);
    margin-top: 1.2rem;
}
.dot-ok  { width:7px; height:7px; border-radius:50%; background:#34d399; display:inline-block; }
.dot-bad { width:7px; height:7px; border-radius:50%; background:#6b7280; display:inline-block; }

/* ── Step badges ── */
.steps-row {
    display: flex;
    gap: 0.6rem;
    margin: 1.4rem 0 1rem;
    justify-content: center;
    flex-wrap: wrap;
}
.step-badge {
    display: flex;
    align-items: center;
    gap: 6px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 100px;
    padding: 0.35rem 0.85rem;
    font-size: 0.78rem;
    color: rgba(255,255,255,0.45);
    font-weight: 500;
}
.step-badge span { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  Sidebar – API Keys
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-header">🔑 API Keys</div>', unsafe_allow_html=True)
    gemini_key      = st.text_input("Gemini API Key",      type="password", placeholder="AIza…")
    elevenlabs_key  = st.text_input("ElevenLabs API Key",  type="password", placeholder="sk_…")
    firecrawl_key   = st.text_input("Firecrawl API Key",   type="password", placeholder="fc-…")

    # Live key status indicators
    def dot(ok): return f'<span class="{"dot-ok" if ok else "dot-bad"}"></span>'
    st.markdown(f"""
    <div style="margin-top:1.4rem;">
      <div class="key-status">{dot(bool(gemini_key))} Gemini</div>
      <div class="key-status">{dot(bool(elevenlabs_key))} ElevenLabs</div>
      <div class="key-status">{dot(bool(firecrawl_key))} Firecrawl</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""
    <div style="font-size:0.75rem; color:rgba(255,255,255,0.25); line-height:1.6;">
    Keys are used only during this session and are never stored.
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  Main – Hero
# ─────────────────────────────────────────────
st.markdown("""
<div class="hero-card">
  <div class="hero-icon">🎙️</div>
  <h1 class="hero-title">Blog to Podcast</h1>
  <p class="hero-sub">Transform any blog post into an AI-narrated podcast in seconds.</p>
  <div class="steps-row">
    <div class="step-badge"><span>🔗</span> Paste URL</div>
    <div class="step-badge"><span>🤖</span> AI Summary</div>
    <div class="step-badge"><span>🔊</span> Voice Synthesis</div>
    <div class="step-badge"><span>⬇️</span> Download</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  URL Input
# ─────────────────────────────────────────────
st.markdown('<div class="section-label">Blog URL</div>', unsafe_allow_html=True)
url = st.text_input(
    label="blog_url",
    label_visibility="collapsed",
    placeholder="https://example.com/your-blog-post",
    value="",
)

# ─────────────────────────────────────────────
#  Generate button
# ─────────────────────────────────────────────
keys_ready = all([gemini_key, elevenlabs_key, firecrawl_key])
if not keys_ready:
    st.caption("⬅️  Enter all three API keys in the sidebar to unlock generation.")

clicked = st.button("✨ Generate Podcast", disabled=not keys_ready)

# ─────────────────────────────────────────────
#  Processing
# ─────────────────────────────────────────────
if clicked:
    if not url.strip():
        st.warning("Please enter a blog URL to continue.")
    else:
        with st.spinner("Scraping blog and synthesising audio — this takes ~20 s…"):
            try:
                # Set env keys
                os.environ["GEMINI_API_KEY"]    = gemini_key
                os.environ["FIRECRAWL_API_KEY"] = firecrawl_key

                # ── Step 1 : Summarise ──────────────────────────
                agent = Agent(
                    name="Blog Summarizer",
                    model=Gemini(id="gemini-2.5-flash"),
                    tools=[FirecrawlTools()],
                    instructions=[
                        "Scrape the blog URL and create a concise, engaging summary "
                        "(max 2000 characters) suitable for a podcast.",
                        "The summary should be conversational and capture the main points.",
                    ],
                )
                response: RunOutput = agent.run(
                    f"Scrape and summarize this blog for a podcast: {url}"
                )
                summary = response.content if hasattr(response, "content") else str(response)

                if not summary:
                    st.error("Could not generate a summary. Please try a different URL.")
                    st.stop()

                # ── Step 2 : TTS ────────────────────────────────
                client = ElevenLabs(api_key=elevenlabs_key)
                try:
                    audio_generator = client.text_to_speech.convert(
                        text=summary,
                        voice_id="JBFqnCBsd6RMkjVDRZzb",
                        model_id="eleven_turbo_v2_5",
                    )
                except Exception as tts_err:
                    err_str = str(tts_err)
                    # Show the raw error so we know exactly what ElevenLabs is complaining about
                    st.error(f"ElevenLabs API Error: {err_str}")
                    st.info("If it says 'invalid_api_key', double-check you copied the full key. If it says 'missing_permissions', verify your key has Text-to-Speech enabled in the ElevenLabs dashboard.")
                    st.stop()

                audio_bytes = b"".join(
                    chunk for chunk in audio_generator if chunk
                )

                # ── Step 3 : Display results ─────────────────────
                st.markdown('<div class="result-card">', unsafe_allow_html=True)
                st.markdown('<div class="result-title">🎧 Your Podcast is Ready</div>', unsafe_allow_html=True)

                st.audio(audio_bytes, format="audio/mp3")

                st.download_button(
                    label="⬇️  Download MP3",
                    data=audio_bytes,
                    file_name="podcast.mp3",
                    mime="audio/mp3",
                    use_container_width=True,
                )

                with st.expander("📄  View generated script"):
                    st.write(summary)

                st.markdown("</div>", unsafe_allow_html=True)

            except Exception as e:
                err_str = str(e)
                st.error(f"An error occurred: {err_str}")