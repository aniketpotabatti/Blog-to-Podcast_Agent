"""UI styling for the Blog-to-Podcast Streamlit application."""

from __future__ import annotations

import tomllib
from pathlib import Path

_THEME_PATH = Path(__file__).resolve().parent.parent / "colors.toml"


def rgba(value: str | list) -> str:
    """Convert a hex string or [r, g, b, a] tuple to a CSS colour."""
    if isinstance(value, str):
        return value
    r, g, b, a = value
    return f"rgba({r}, {g}, {b}, {a})"


def build_css() -> str:
    """Build the full CSS block from design tokens in colors.toml."""
    cfg = tomllib.loads(_THEME_PATH.read_text(encoding="utf-8"))
    
    bg = cfg["base_background"]
    surf = cfg["surface"]
    ln = cfg["line"]
    txt = cfg["text"]
    acc = cfg["accent"]
    grd = cfg["gradient"]
    rad = cfg["radius"]
    fnt = cfg["font"]
    hero = cfg["hero"]
    ctrl = cfg["control"]
    sect = cfg["section_label"]
    pan = cfg["panel"]
    pill = cfg["pill"]
    btn = cfg["button"]
    tag = cfg["tag"]
    tab = cfg["tab"]
    exp = cfg["expander"]
    dl = cfg["download"]
    res = cfg["result"]
    sb = cfg["scrollbar"]
    lay = cfg["layout"]
    foot = cfg["footer"]
    met = cfg["metric"]

    root = f""":root {{
    --bg-0: {bg[0]};
    --bg-1: {bg[1]};
    --bg-2: {bg[2]};
    --surface: {rgba(surf["default"])};
    --surface-strong: {rgba(surf["strong"])};
    --surface-accent: {rgba(surf["accent"])};
    --surface-pill: {rgba(surf["pill"])};
    --surface-header: {rgba(surf["header"])};
    --line: {rgba(ln["hairline"])};
    --line-strong: {rgba(ln["strong"])};
    --text-hi: {txt["hi"]};
    --text-mid: {rgba(txt["mid"])};
    --text-lo: {rgba(txt["lo"])};
    --accent: {acc["primary"]};
    --accent-2: {acc["secondary"]};
    --accent-soft: {rgba(acc["soft"])};
    --accent-ink: {acc["ink"]};
    --link: {acc["link"]};
    --accent-glow-top: {rgba(grd["accent_glow_top"])};
    --accent-glow-bottom: {rgba(grd["accent_glow_bottom"])};
    --hero-border-a: {rgba(grd["hero_border_a"])};
    --hero-border-b: {rgba(grd["hero_border_b"])};
    --hero-border-c: {rgba(grd["hero_border_c"])};
    --hero-header-op: {rgba(grd["hero_header_op"])};
    --shadow-drop: {rgba(grd["shadow_drop"])};
    --hero-icon-shadow: {rgba(grd["hero_icon_shadow"])};
    --hero-text-0: {cfg["hero_text_stops"][0]};
    --hero-text-1: {cfg["hero_text_stops"][1]};
    --hero-text-2: {cfg["hero_text_stops"][2]};
    --btn-grad-0: {cfg["button_gradient"][0]};
    --btn-grad-1: {cfg["button_gradient"][1]};
    --btn-grad-2: {cfg["button_gradient"][2]};
    --focus-ring-outer: {rgba(cfg["focus_ring_outer"])};
    --focus-ring-inner: {rgba(cfg["focus_ring_inner"])};
    --focus-border-hover: {rgba(cfg["focus_border_hover"])};
    --focus-border-active: {rgba(cfg["focus_border_active"])};
    --focus-ink-on-accent: {cfg["focus_ink_on_accent_bg"]};
    --chip-accent-line: {rgba(cfg["chip_accent_line"])};
    --chip-accent-bg: {rgba(cfg["chip_accent_bg"])};
    --sidebar-glow-1: {rgba(cfg["sidebar_glow_stop1"])};
    --sidebar-glow-2: {rgba(cfg["sidebar_glow_stop2"])};
    --sidebar-surface: {rgba(cfg["sidebar_surface"])};
    --sidebar-bottom: {rgba(cfg["sidebar_bottom"])};
    --pill-text: {pill["text"]};
    --pill-border: {rgba(pill["border"])};
    --tag-border: {rgba(tag["border"])};
    --tab-selected-border: {rgba(tab["selected_border"])};
    --expander-hover: {exp["hover_text"]};
    --download-border: {rgba(dl["border"])};
    --download-border-hover: {rgba(dl["border_hover"])};
    --btn-primary-shadow: {rgba(btn["primary_shadow"])};
    --btn-primary-shadow-hover: {rgba(btn["primary_shadow_hover"])};
    --result-shadow: {rgba(res["shadow"])};
    --result-border-a: {rgba(res["border_a"])};
    --result-border-b: {rgba(res["border_b"])};
    --scrollbar-thumb: {rgba(sb["thumb"])};
    --scrollbar-thumb-hover: {rgba(sb["thumb_hover"])};
    --radius-lg: {rad["lg"]}px;
    --radius-md: {rad["md"]}px;
    --radius-sm: {rad["sm"]}px;
    --radius-pill: {rad["pill"]}px;
    --radius-chip: {rad["chip"]}px;
    --font: '{fnt["family"]}', sans-serif;
    --track-h: {fnt["track_heading"]}em;
    --track-b: {fnt["track_body"]}em;
    --track-l: {fnt["track_label"]}em;
    --section-size: {sect["size"]}rem;
    --section-weight: {sect["weight"]};
    --section-mb: {sect["margin_bottom"]}rem;
    --hero-icon-size: {hero["icon_size"]}rem;
    --hero-title-size: {hero["title_size"]}rem;
    --hero-title-weight: {hero["title_weight"]};
    --hero-title-track: {hero["title_track"]}em;
    --hero-sub-size: {hero["subtitle_size"]}rem;
    --hero-sub-max: {hero["subtitle_max_width"]}px;
    --hero-sub-line: {hero["subtitle_line"]};
    --hero-icon-shadow-r: {hero["icon_shadow_radius"]}px;
    --hero-icon-shadow-x: {hero["icon_shadow_x"]}px;
    --hero-icon-shadow-y: {hero["icon_shadow_y"]}px;
    --hero-card-pad: {hero["card_padding"]};
    --hero-card-margin: {hero["card_margin"]};
    --hero-backdrop-blur: {hero["backdrop_blur"]}px;
    --hero-glow-size: {hero["glow_size"]}px;
    --hero-glow-height: {hero["glow_height"]}px;
    --ctrl-fs: {ctrl["font_size"]}rem;
    --ctrl-pad-x: {ctrl["input_pad_x"]}rem;
    --ctrl-pad-y: {ctrl["input_pad_y"]}rem;
    --ctrl-baseweb-fs: {ctrl["baseweb_fs"]}rem;
    --pill-size: {pill["size"]}rem;
    --pill-weight: {pill["weight"]};
    --pill-track: {pill["track"]}em;
    --pill-pad-y: {pill["pad_y"]}rem;
    --pill-pad-x: {pill["pad_x"]}rem;
    --btn-fs: {btn["font_size"]}rem;
    --btn-pad-y: {btn["pad_y"]}rem;
    --btn-pad-x: {btn["pad_x"]}rem;
    --tab-fs: {tab["font_size"]}rem;
    --tab-pad-y: {tab["pad_y"]}rem;
    --tab-pad-x: {tab["pad_x"]}rem;
    --tab-radius: {tab["radius"]}px;
    --tab-list-radius: {tab["list_radius"]}px;
    --result-pad: {res["padding"]};
    --result-mt: {res["margin_top"]}rem;
    --result-title-size: {res["title_size"]}rem;
    --result-title-weight: {res["title_weight"]};
    --result-title-track: {res["title_track"]}em;
    --metric-pad: {met["pad"]};
    --metric-label-size: {met["label_size"]}rem;
    --metric-label-track: {met["label_track"]}em;
    --metric-value-size: {met["value_size"]}rem;
    --footer-size: {foot["size"]}rem;
    --footer-pad-top: {foot["pad_top"]}rem;
    --layout-block-pt: {lay["block_pad_top"]}rem;
    --layout-block-pb: {lay["block_pad_bottom"]}rem;
    --layout-max-width: {lay["max_width"]}px;
    --layout-mobile-break: {lay["mobile_break"]}px;
    --layout-mobile-px: {lay["mobile_pad_x"]}rem;
    --hero-mobile-pad: {lay["hero_mobile_pad"]};
    --hero-mobile-title: {lay["hero_mobile_title"]}rem;
    --hero-mobile-sub: {lay["hero_mobile_sub"]}rem;
    --tab-mobile-pad: {lay["tab_mobile_pad"]};
    --tab-mobile-fs: {lay["tab_mobile_fs"]}rem;
    --panel-header-mb: {pan["header_margin_b"]}rem;
    --scrollbar-width: {sb["width"]}px;
}}"""

    css = """
/* ── Base & typography ── */
html, body, [class*="css"], .stApp, .stApp p, .stApp li {
    font-family: var(--font);
    letter-spacing: var(--track-b);
}
.stApp {
    color: var(--text-hi);
    background:
        radial-gradient(var(--hero-glow-size) var(--hero-glow-height) at 85% -12%, var(--accent-glow-top), transparent 62%),
        radial-gradient(720px 420px at -12% 112%, var(--accent-glow-bottom), transparent 60%),
        linear-gradient(140deg, var(--bg-0) 0%, var(--bg-1) 52%, var(--bg-2) 100%);
    min-height: 100vh;
}
.stApp p, .stApp li { color: var(--text-mid); line-height: 1.6; }
.stApp strong { color: var(--text-hi); font-weight: 600; }
.stApp a { color: var(--link); text-decoration: none; }

/* ── Chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container {
    padding-top: var(--layout-block-pt);
    padding-bottom: var(--layout-block-pb);
    max-width: var(--layout-max-width);
}

/* ── Section labels ── */
.section-label {
    font-size: var(--section-size);
    font-weight: var(--section-weight);
    letter-spacing: var(--track-l);
    text-transform: uppercase;
    color: var(--text-lo);
    margin: 0 0 var(--section-mb);
    text-align: left;
}

/* ── Hero ── */
.hero-card {
    text-align: center;
    padding: var(--hero-card-pad);
    margin: var(--hero-card-margin);
    border-radius: var(--radius-lg);
    background:
        linear-gradient(var(--hero-header-op), var(--hero-header-op)) padding-box,
        linear-gradient(135deg, var(--hero-border-a), var(--hero-border-b), var(--hero-border-c)) border-box;
    border: 1px solid transparent;
    box-shadow: 0 24px 60px var(--shadow-drop);
    backdrop-filter: blur(var(--hero-backdrop-blur));
    -webkit-backdrop-filter: blur(var(--hero-backdrop-blur));
}
.hero-icon {
    font-size: var(--hero-icon-size);
    line-height: 1;
    margin-bottom: 0.7rem;
    filter: drop-shadow(var(--hero-icon-shadow-x) var(--hero-icon-shadow-y) var(--hero-icon-shadow-r) var(--hero-icon-shadow));
}
.hero-title {
    font-size: var(--hero-title-size);
    font-weight: var(--hero-title-weight);
    letter-spacing: var(--hero-title-track);
    margin: 0 0 0.5rem;
    background: linear-gradient(100deg, var(--hero-text-0) 0%, var(--hero-text-1) 55%, var(--hero-text-2) 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
.hero-sub {
    font-size: var(--hero-sub-size);
    font-weight: 400;
    color: var(--text-mid);
    margin: 0 auto 1.15rem;
    max-width: var(--hero-sub-max);
    line-height: var(--hero-sub-line);
}

/* ── Feature pills ── */
.hero-badges {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.45rem;
}
.pill {
    display: inline-block;
    font-size: var(--pill-size);
    font-weight: var(--pill-weight);
    letter-spacing: var(--pill-track);
    color: var(--pill-text);
    background: var(--surface-accent);
    border: 1px solid var(--pill-border);
    border-radius: var(--radius-pill);
    padding: var(--pill-pad-y) var(--pill-pad-x);
    white-space: nowrap;
}

/* ── Text inputs & areas ── */
.stTextInput input, .stTextArea textarea {
    background: var(--surface) !important;
    border: 1px solid var(--line) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-hi) !important;
    font-size: var(--ctrl-fs) !important;
    padding: var(--ctrl-pad-y) var(--ctrl-pad-x) !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--focus-border-hover) !important;
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
    font-size: var(--ctrl-fs) !important;
}
.stMultiSelect span[data-baseweb="tag"] {
    background: var(--accent-soft) !important;
    border: 1px solid var(--tag-border) !important;
    color: var(--accent-ink) !important;
    border-radius: var(--radius-chip) !important;
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
    border-color: var(--hero-border-a) !important;
    background: var(--surface-strong) !important;
}
.stFileUploader span, .stFileUploader small { color: var(--text-mid) !important; }

/* ── Radio as soft chips ── */
[role="radiogroup"] { gap: 0.4rem !important; }
[role="radiogroup"] label {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--radius-pill);
    padding: 0.32rem 0.8rem 0.32rem 0.55rem;
    transition: all 0.18s ease;
}
[role="radiogroup"] label:hover {
    border-color: var(--line-strong);
    background: var(--surface-strong);
}
[role="radiogroup"] label p, [role="radiogroup"] label span {
    color: var(--text-mid) !important;
    font-size: var(--ctrl-baseweb-fs) !important;
}

/* ── Checkbox ── */
.stCheckbox span { color: var(--text-mid) !important; font-size: var(--ctrl-baseweb-fs); }

/* ── Slider ── */
.stSlider [role="slider"] {
    background: var(--focus-ink-on-accent) !important;
    border: 3px solid var(--chip-accent-line) !important;
}
.stSlider [data-baseweb="slider"] > div { background: var(--accent-soft) !important; }
.stSlider span { color: var(--text-mid) !important; font-size: 0.85rem; }

/* ── Expanders ── */
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
[data-testid="stExpander"] summary:hover { color: var(--expander-hover) !important; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    border-bottom: 1px solid var(--line);
    border-radius: var(--tab-list-radius) !important;
    padding-bottom: 0.4rem;
}
.stTabs [data-baseweb="tab"] {
    background: var(--surface) !important;
    border: 1px solid transparent;
    border-radius: var(--tab-radius) !important;
    padding: var(--tab-pad-y) var(--tab-pad-x) !important;
    transition: all 0.18s ease;
    overflow: hidden;
}
.stTabs [data-baseweb="tab"] p {
    font-size: var(--tab-fs) !important;
    font-weight: 600;
    color: var(--text-mid) !important;
}
.stTabs [data-baseweb="tab"]:hover { background: var(--surface-strong) !important; }
.stTabs [aria-selected="true"] {
    background: var(--accent-soft) !important;
    border-color: var(--tab-selected-border);
}
.stTabs [aria-selected="true"] p { color: var(--text-hi) !important; }
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none; }
/* BaseWeb paints the tab background on an inner div; keep its corners rounded. */
.stTabs [data-baseweb="tab"] > div,
.stTabs [data-baseweb="tab"] > div > div {
    border-radius: var(--tab-radius) !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: var(--radius-sm) !important;
    font-weight: 700 !important;
    font-size: var(--btn-fs) !important;
    padding: var(--btn-pad-y) var(--btn-pad-x) !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(120deg, var(--btn-grad-0) 0%, var(--btn-grad-1) 55%, var(--btn-grad-2) 100%) !important;
    color: var(--focus-ink-on-accent) !important;
    border: none !important;
    box-shadow: 0 10px 26px var(--btn-primary-shadow);
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1.5px);
    filter: brightness(1.06);
    box-shadow: 0 14px 32px var(--btn-primary-shadow-hover);
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

/* ── Download button ── */
.stDownloadButton > button {
    width: 100%;
    border-radius: var(--radius-sm) !important;
    font-weight: 700 !important;
    background: var(--surface-strong) !important;
    color: var(--text-hi) !important;
    border: 1px solid var(--download-border) !important;
    transition: all 0.15s ease;
}
.stDownloadButton > button:hover {
    border-color: var(--download-border-hover) !important;
    transform: translateY(-1.5px);
}

/* ── Metrics ── */
[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    padding: var(--metric-pad);
}
[data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] {
    font-size: var(--metric-label-size) !important;
    font-weight: 700 !important;
    letter-spacing: var(--metric-label-track);
    text-transform: uppercase;
    color: var(--text-lo) !important;
}
[data-testid="stMetricValue"] {
    font-size: var(--metric-value-size) !important;
    font-weight: 700 !important;
    color: var(--text-hi) !important;
}

/* ── Status widget ── */
[data-testid="stStatusWidget"] {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
}

/* ── Result card ── */
.result-card {
    text-align: center;
    padding: var(--result-pad);
    margin-top: var(--result-mt);
    border-radius: var(--radius-lg);
    background:
        linear-gradient(var(--hero-header-op), var(--hero-header-op)) padding-box,
        linear-gradient(135deg, var(--result-border-a), var(--result-border-b)) border-box;
    border: 1px solid transparent;
    box-shadow: 0 18px 44px var(--result-shadow);
}
.result-title {
    font-size: var(--result-title-size);
    font-weight: var(--result-title-weight);
    color: var(--text-hi);
    margin: 0 0 0.4rem;
    letter-spacing: var(--result-title-track);
}

/* ── Audio player ── */
.stAudio, .stAudio > div {
    border-radius: var(--radius-md) !important;
    overflow: hidden;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--surface-header), var(--sidebar-bottom));
    border-right: 1px solid var(--line);
}
section[data-testid="stSidebar"] hr {
    border-color: var(--line) !important;
    margin: var(--panel-header-mb) 0;
}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
    font-size: var(--pill-size) !important;
    color: var(--text-lo) !important;
    line-height: 1.5;
}

/* ── Footer ── */
.app-footer {
    text-align: center;
    font-size: var(--footer-size);
    color: var(--text-lo);
    padding-top: var(--footer-pad-top);
}
.app-footer strong { color: var(--text-mid); font-weight: 600; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: var(--scrollbar-width); height: var(--scrollbar-width); }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: var(--scrollbar-thumb);
    border-radius: var(--radius-chip);
    border: 2px solid transparent;
    background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--scrollbar-thumb-hover);
    background-clip: content-box;
}

"""

    mobile = f"""
/* ── Mobile ── */
@media (max-width: {lay["mobile_break"]}px) {{
    .block-container {{ padding-left: var(--layout-mobile-px); padding-right: var(--layout-mobile-px); }}
    .hero-card {{ padding: var(--hero-mobile-pad); }}
    .hero-title {{ font-size: var(--hero-mobile-title); }}
    .hero-sub {{ font-size: var(--hero-mobile-sub); }}
    .stTabs [data-baseweb="tab"] {{ padding: var(--tab-mobile-pad) !important; }}
    .stTabs [data-baseweb="tab"] p {{ font-size: var(--tab-mobile-fs) !important; }}
}}
"""

    return f"<style>\n@import url('{fnt['url']}');\n\n{root}\n{css}\n{mobile}\n</style>"
