"""
Content acquisition: blog URLs, PDF documents and RSS feeds.
==========================================================

Feature 1 - PDF / research paper ingestion
    * ``.pdf`` URLs are downloaded and parsed locally with ``pypdf``
      (free, deterministic), falling back to Firecrawl's PDF parser.
    * Local PDF bytes (Streamlit uploads) go straight through ``pypdf``.
    * Paper metadata (title / author) is read from the PDF document info.

Feature 2 - RSS feed monitoring
    * ``fetch_feed_entries`` lists the newest items of any RSS/Atom feed.
    * ``load_article_from_feed_entry`` turns one entry into an Article, so the
      monitor can generate episodes automatically.

All network access is isolated in thin wrappers that accept an injected
client, which keeps the module fully unit-testable offline.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List

import requests

from podcast import config
from podcast.errors import (
    ConfigurationError,
    IngestionError,
    InputError,
    classify_exception,
)
from podcast.models import Article, FeedEntry, SourceKind
from podcast.utils import (
    clean_text,
    get_logger,
    is_pdf_url,
    looks_like_pdf,
    read_json_file,
    retry_call,
    truncate_text,
    validate_url,
    write_json_file,
)

LOGGER = get_logger("ingestion")
USER_AGENT = (
    "BlogToPodcastAgent/2.0 (+https://github.com/aniketpotabatti/Blog-to-Podcast_Agent)"
)


def _field(obj: Any, name: str, default: Any = "") -> Any:
    """Read an attribute from a dict or a model object alike.

    Dicts are probed with several key spellings because provider payloads mix
    plain (``title``), camelCase and PDF-style (``/Title``) keys.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        for key in (name, f"/{name}", name.title(), name.lower(), f"/{name.title()}"):
            value = obj.get(key)
            if value:
                return value
        return default
    return getattr(obj, name, default) or default


def _require(module_name: str, package_hint: str) -> Any:
    """Import an optional dependency, raising a helpful error when missing."""
    try:
        return __import__(module_name)
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ConfigurationError(
            f"The '{module_name}' package is required for this feature.",
            hint=f"Install it with: pip install {package_hint}",
            stage="configuration",
        ) from exc


# ─────────────────────────────────────────────
#  Web pages (Firecrawl)
# ─────────────────────────────────────────────
def build_firecrawl_client(api_key: str) -> Any:
    """Create a Firecrawl client, validating that a key was supplied."""
    if not api_key:
        raise ConfigurationError(
            "A Firecrawl API key is required to scrape web pages.",
            hint="Add the key in the sidebar or set FIRECRAWL_API_KEY.",
        )
    firecrawl = _require("firecrawl", "firecrawl-py")
    return firecrawl.Firecrawl(api_key=api_key)


def article_from_document(document: Any, url: str = "") -> Article:
    """Convert a Firecrawl document into an :class:`Article`."""
    markdown = clean_text(_field(document, "markdown") or _field(document, "html"))
    metadata = _field(document, "metadata", {})
    title = _field(metadata, "title") or _field(metadata, "ogTitle")
    return Article(
        text=markdown,
        title=clean_text(str(title)),
        url=_field(metadata, "sourceURL") or url,
        kind=SourceKind.URL,
        author=clean_text(
            str(_field(metadata, "author") or _field(metadata, "dcCreator"))
        ),
        published=str(
            _field(metadata, "publishedTime") or _field(metadata, "date") or ""
        ),
    )


def scrape_url(
    url: str, *, api_key: str = "", client: Any = None, max_chars: int = 0
) -> Article:
    """Scrape a public web page into an Article via Firecrawl.

    Ads and navigation chrome are stripped using ``block_ads`` and
    ``only_main_content`` so the generated script stays clean.
    """
    try:
        target = validate_url(url)
    except InputError as exc:
        raise exc

    firecrawl = client or build_firecrawl_client(api_key)
    limit = max_chars or config.MAX_ARTICLE_CHARS

    def _scrape() -> Any:
        return firecrawl.scrape(
            target,
            formats=["markdown"],
            only_main_content=True,
            block_ads=True,
            timeout=config.REQUEST_TIMEOUT * 1000,
        )

    try:
        document = retry_call(
            _scrape,
            attempts=config.MAX_RETRIES,
            description=f"scrape {target}",
            logger=LOGGER,
        )
    except Exception as exc:
        raise classify_exception(exc, stage="ingestion") from exc

    article = article_from_document(document, target)
    if not article.text.strip():
        raise IngestionError(
            "No readable text was found at that URL.",
            hint="Try another article, or check the page is public and text-based.",
        )
    article.truncated = len(article.text) > limit
    article.text = truncate_text(article.text, limit)
    LOGGER.info(
        "Scraped %s (%d words%s)",
        target,
        article.word_count,
        ", truncated" if article.truncated else "",
    )
    return article


# ─────────────────────────────────────────────
#  FEATURE 1: PDF & research paper ingestion
# ─────────────────────────────────────────────
def extract_pdf_text(
    data: bytes, *, max_pages: int = config.PDF_MAX_PAGES
) -> Dict[str, Any]:
    """Extract text and document info from raw PDF bytes using ``pypdf``.

    Args:
        data: Raw PDF payload.
        max_pages: Maximum number of pages to read (papers can be long).

    Returns:
        A mapping with ``text``, ``title``, ``author``, ``pages`` and
        ``pages_read`` keys.
    """
    if not looks_like_pdf(data):
        raise IngestionError(
            "The uploaded file is not a valid PDF.",
            hint="Export the document as PDF and try again.",
        )

    pypdf = _require("pypdf", "pypdf")
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:  # pragma: no cover - depends on the document
                raise IngestionError(
                    "This PDF is password protected.",
                    hint="Remove the password before uploading the document.",
                )
        total_pages = len(reader.pages)
        pages_read = min(total_pages, max(1, max_pages))
        chunks: List[str] = []
        for page in reader.pages[:pages_read]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception as exc:  # pragma: no cover - malformed page
                LOGGER.warning("Skipping unreadable PDF page: %s", exc)
        info: Any = getattr(reader, "metadata", None) or {}
        title = clean_text(str(_field(info, "title")))
        author = clean_text(str(_field(info, "author")))
    except IngestionError:
        raise
    except Exception as exc:
        raise classify_exception(exc, stage="ingestion") from exc

    text = clean_text("\n\n".join(chunks))
    if not title:
        title = _title_from_text(text)
    return {
        "text": text,
        "title": title,
        "author": author,
        "pages": total_pages,
        "pages_read": pages_read,
    }


def _title_from_text(text: str, max_length: int = 120) -> str:
    """Best-effort title: first reasonably long, non-trivial line of a paper."""
    for raw_line in (text or "").splitlines()[:25]:
        line = raw_line.strip()
        if len(line) < 12 or len(line) > max_length:
            continue
        lowered = line.lower()
        if lowered.startswith(("arxiv:", "doi:", "http", "www.", "abstract")):
            continue
        if sum(char.isdigit() for char in line) > len(line) / 3:
            continue
        return line
    return ""


def build_pdf_article(
    extracted: Dict[str, Any],
    *,
    filename: str = "",
    url: str = "",
    title: str = "",
    author: str = "",
    published: str = "",
    max_chars: int = 0,
) -> Article:
    """Turn extracted PDF content into a normalised :class:`Article`."""
    limit = max_chars or config.MAX_ARTICLE_CHARS
    text = clean_text(extracted.get("text", ""))
    if not text:
        raise IngestionError(
            "No selectable text was found in this PDF.",
            hint="Scanned PDFs need OCR; try a text-based PDF or the original web article.",
        )
    resolved_title = clean_text(title) or extracted.get("title", "") or filename
    return Article(
        text=truncate_text(text, limit),
        title=clean_text(resolved_title),
        url=url,
        kind=SourceKind.PDF,
        author=clean_text(author or extracted.get("author", "")),
        published=published,
        truncated=len(text) > limit,
    )


def load_article_from_pdf_bytes(
    data: bytes,
    *,
    filename: str = "document.pdf",
    url: str = "",
    title: str = "",
    max_chars: int = 0,
    max_pages: int = config.PDF_MAX_PAGES,
) -> Article:
    """Load an uploaded PDF (for example from a Streamlit file uploader)."""
    extracted = extract_pdf_text(data, max_pages=max_pages)
    article = build_pdf_article(
        extracted,
        filename=filename,
        url=url,
        title=title,
        max_chars=max_chars,
    )
    LOGGER.info(
        "Parsed PDF '%s' (%d/%d pages, %d words)",
        filename,
        extracted["pages_read"],
        extracted["pages"],
        article.word_count,
    )
    return article


def download_pdf(url: str, *, timeout: int = config.REQUEST_TIMEOUT) -> bytes:
    """Download a PDF over HTTP with retries."""
    target = validate_url(url)

    def _download() -> bytes:
        response = requests.get(
            target,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
        )
        response.raise_for_status()
        return response.content

    try:
        data = retry_call(
            _download,
            attempts=config.MAX_RETRIES,
            description=f"download {target}",
            logger=LOGGER,
        )
    except Exception as exc:
        raise classify_exception(exc, stage="ingestion") from exc

    if not looks_like_pdf(data):
        raise IngestionError(
            f"{target} did not return a PDF file.",
            hint="Check the link opens the document directly, or upload the file instead.",
        )
    return data


def load_article_from_pdf_url(
    url: str,
    *,
    api_key: str = "",
    client: Any = None,
    max_chars: int = 0,
    max_pages: int = config.PDF_MAX_PAGES,
) -> Article:
    """Ingest a PDF (e.g. a research paper) from a direct URL.

    Strategy: parse locally with ``pypdf`` first because it is free and
    deterministic; if that yields no text (scanned document, exotic encoding)
    fall back to Firecrawl's hosted PDF parser.
    """
    target = validate_url(url)
    try:
        data = download_pdf(target)
        extracted = extract_pdf_text(data, max_pages=max_pages)
        article = build_pdf_article(extracted, url=target, max_chars=max_chars)
        title = _title_from_text(article.text)
        if not article.title or not article.title.strip():
            article.title = title
        LOGGER.info("Parsed PDF from URL %s (%d words)", target, article.word_count)
        return article
    except IngestionError as local_error:
        LOGGER.warning("Local PDF parsing failed for %s: %s", target, local_error)

    return scrape_with_pdf_parser(
        target, api_key=api_key, client=client, max_chars=max_chars
    )


def scrape_with_pdf_parser(
    url: str, *, api_key: str = "", client: Any = None, max_chars: int = 0
) -> Article:
    """Fallback ingestion for PDFs using Firecrawl's PDF parser."""
    firecrawl = client or build_firecrawl_client(api_key)
    limit = max_chars or config.MAX_ARTICLE_CHARS
    try:
        from firecrawl.v2.types import PDFParser  # local import keeps the SDK optional

        parsers: Any = [PDFParser(max_pages=config.PDF_MAX_PAGES)]
    except ImportError:  # pragma: no cover - very old SDK
        parsers = ["pdf"]

    def _scrape() -> Any:
        return firecrawl.scrape(
            url,
            formats=["markdown"],
            parsers=parsers,
            only_main_content=True,
            block_ads=True,
            timeout=config.REQUEST_TIMEOUT * 1000,
        )

    try:
        document = retry_call(
            _scrape,
            attempts=config.MAX_RETRIES,
            description="scrape pdf",
            logger=LOGGER,
        )
    except Exception as exc:
        raise classify_exception(exc, stage="ingestion") from exc

    article = article_from_document(document, url)
    article.kind = SourceKind.PDF
    article.text = truncate_text(article.text, limit)
    if not article.text.strip():
        raise IngestionError(
            "Could not read any text from that PDF.",
            hint="Upload the file directly or try a text-based version of the document.",
        )
    return article


# ─────────────────────────────────────────────
#  FEATURE 2: RSS feed monitoring
# ─────────────────────────────────────────────
def parse_feed(raw_xml: str) -> List[FeedEntry]:
    """Parse RSS/Atom XML into a list of :class:`FeedEntry` objects."""
    feedparser = _require("feedparser", "feedparser")
    parsed = feedparser.parse(raw_xml or "")
    entries: List[FeedEntry] = []
    for item in getattr(parsed, "entries", []) or []:
        entry = feed_entry_from_parsed(item)
        if entry.link or entry.title:
            entries.append(entry)
    return entries


def feed_entry_from_parsed(item: Any) -> FeedEntry:
    """Convert a single feedparser entry into a :class:`FeedEntry`."""
    published = str(
        _field(item, "published") or _field(item, "updated") or _field(item, "created")
    )
    return FeedEntry(
        title=clean_text(str(_field(item, "title"))),
        link=str(_field(item, "link")),
        guid=str(_field(item, "id") or _field(item, "guid") or _field(item, "link")),
        published=published,
        summary=clean_text(str(_field(item, "summary") or _field(item, "description"))),
    )


def feed_title(raw_xml: str) -> str:
    """Return the feed's own title, if present."""
    feedparser = _require("feedparser", "feedparser")
    parsed = feedparser.parse(raw_xml or "")
    return clean_text(str(_field(_field(parsed, "feed", {}), "title")))


def fetch_feed_entries(
    feed_url: str,
    *,
    limit: int = config.RSS_DEFAULT_LIMIT,
    session: Any = None,
) -> List[FeedEntry]:
    """Fetch and list the newest entries of an RSS/Atom feed.

    Args:
        feed_url: Absolute URL of the feed.
        limit: Maximum number of entries to return (newest first).
        session: Optional ``requests`` session (injected in tests).

    Returns:
        A list of :class:`FeedEntry` objects.
    """
    target = validate_url(feed_url)
    http = session or requests

    def _fetch() -> str:
        response = http.get(
            target,
            timeout=config.REQUEST_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        response.raise_for_status()
        return response.text

    try:
        raw_xml = retry_call(
            _fetch,
            attempts=config.MAX_RETRIES,
            description=f"fetch feed {target}",
            logger=LOGGER,
        )
    except Exception as exc:
        raise classify_exception(exc, stage="ingestion") from exc

    entries = parse_feed(raw_xml)
    if not entries:
        raise IngestionError(
            f"No entries were found in {target}.",
            hint="Check the URL points at an RSS or Atom feed (usually .xml or /feed).",
        )
    LOGGER.info("Feed %s returned %d entrie(s)", target, len(entries))
    return entries[: max(1, limit)]


class FeedMonitor:
    """Tracks which feed entries have already been turned into episodes.

    Processed identifiers are persisted as JSON so scheduled runs only pick up
    genuinely new articles instead of regenerating the whole feed every time.
    """

    def __init__(self, state_file: Any = None):
        self.state_file = state_file or config.RSS_STATE_FILE

    def _load(self) -> Dict[str, List[str]]:
        """Read persisted monitor state as ``{feed_url: [identities]}``."""
        state = read_json_file(self.state_file, {})
        return {
            str(key): [str(item) for item in value]
            for key, value in state.items()
            if isinstance(value, list)
        }

    def seen(self, feed_url: str) -> List[str]:
        """Identifiers already processed for a feed."""
        return self._load().get((feed_url or "").strip(), [])

    def mark_seen(self, feed_url: str, identities: List[str]) -> None:
        """Record identifiers as processed, preserving order and de-duplicating."""
        state = self._load()
        key = (feed_url or "").strip()
        merged = list(
            dict.fromkeys(state.get(key, []) + [str(item) for item in identities])
        )
        state[key] = merged[-500:]  # cap growth on long-running feeds
        write_json_file(self.state_file, state)

    def new_entries(self, feed_url: str, entries: List[FeedEntry]) -> List[FeedEntry]:
        """Return only the entries that have not been processed yet."""
        known = set(self.seen(feed_url))
        return [entry for entry in entries if entry.identity() not in known]

    def reset(self, feed_url: str = "") -> None:
        """Forget processed entries for one feed, or for every feed."""
        if not feed_url:
            write_json_file(self.state_file, {})
            return
        state = self._load()
        state.pop(feed_url.strip(), None)
        write_json_file(self.state_file, state)

    def mark_entries_seen(self, feed_url: str, entries: List[FeedEntry]) -> None:
        """Convenience wrapper: mark a list of entries as processed."""
        self.mark_seen(feed_url, [entry.identity() for entry in entries])


def load_article_from_feed_entry(
    entry: FeedEntry,
    *,
    api_key: str = "",
    client: Any = None,
    max_chars: int = 0,
) -> Article:
    """Turn one feed entry into an Article by scraping its linked article.

    Falls back to the entry's own summary when the link cannot be scraped, so a
    single unreachable article never breaks a whole monitoring run.
    """
    if not entry.link:
        return _article_from_entry_summary(entry)

    try:
        article = scrape_url(
            entry.link, api_key=api_key, client=client, max_chars=max_chars
        )
        article.kind = SourceKind.RSS
    except IngestionError as exc:
        LOGGER.warning("Falling back to feed summary for %s: %s", entry.link, exc)
        article = _article_from_entry_summary(entry)

    if not article.title:
        article.title = entry.title
    if not article.published:
        article.published = entry.published
    if not article.url:
        article.url = entry.link
    return article


def _article_from_entry_summary(entry: FeedEntry) -> Article:
    """Build an article from a feed entry's own summary text."""
    summary = (entry.summary or entry.title or "").strip()
    if not summary:
        raise InputError(
            "This feed entry has neither a link nor a summary.",
            hint="Choose a feed whose items include article links or descriptions.",
        )
    return Article(
        text=summary,
        title=entry.title,
        url=entry.link,
        kind=SourceKind.RSS,
        published=entry.published,
    )


# ─────────────────────────────────────────────
#  Source dispatcher
# ─────────────────────────────────────────────
def load_article_from_url(
    url: str,
    *,
    api_key: str = "",
    client: Any = None,
    max_chars: int = 0,
    max_pages: int = config.PDF_MAX_PAGES,
) -> Article:
    """Load an Article from any URL, routing PDFs to the PDF pipeline.

    Detection is two-stage: the URL path is inspected first (cheap), then the
    response signature is sniffed when a PDF is likely.

    Args:
        url: Web page or direct PDF link.
        api_key: Firecrawl API key (used for HTML pages and PDF fallback).
        client: Optional pre-built Firecrawl client.
        max_chars: Character budget for the extracted text.
        max_pages: Page budget when the target is a PDF.

    Returns:
        A normalised :class:`Article`.
    """
    target = validate_url(url)
    if is_pdf_url(target):
        LOGGER.info("Detected PDF source: %s", target)
        return load_article_from_pdf_url(
            target,
            api_key=api_key,
            client=client,
            max_chars=max_chars,
            max_pages=max_pages,
        )
    return scrape_url(target, api_key=api_key, client=client, max_chars=max_chars)
