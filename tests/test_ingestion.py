"""Tests for ingestion: blog URLs, PDF documents and RSS feeds."""

from __future__ import annotations

import io

import pytest

from podcast import config
from podcast.errors import ConfigurationError, IngestionError, InputError
from podcast.ingestion import (
    FeedMonitor,
    article_from_document,
    build_pdf_article,
    extract_pdf_text,
    feed_entry_from_parsed,
    feed_title,
    fetch_feed_entries,
    load_article_from_feed_entry,
    load_article_from_pdf_bytes,
    load_article_from_url,
    parse_feed,
    scrape_url,
)
from podcast.models import Article, FeedEntry, SourceKind

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Tech Blog</title>
    <link>https://example.com</link>
    <description>Posts about engineering</description>
    <item>
      <title>Why streaming data matters</title>
      <link>https://example.com/streaming-data</link>
      <guid>https://example.com/streaming-data</guid>
      <pubDate>Mon, 01 Sep 2025 10:00:00 GMT</pubDate>
      <description>Streaming data changes how teams build products.</description>
    </item>
    <item>
      <title>Designing reliable pipelines</title>
      <link>https://example.com/reliable-pipelines</link>
      <guid>post-2</guid>
      <pubDate>Tue, 02 Sep 2025 10:00:00 GMT</pubDate>
      <description>Reliability is a product feature, not an afterthought.</description>
    </item>
  </channel>
</rss>
"""


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, text: str = "", content: bytes = b"", status: int = 200):
        self.text = text
        self.content = content
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Records requests and replays a queued response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class FakeFirecrawl:
    """Stand-in for the Firecrawl client that captures scrape arguments."""

    def __init__(self, document=None, error=None):
        self.document = document
        self.error = error
        self.calls = []

    def scrape(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.document


class FakeDocument:
    """Stand-in for a Firecrawl scraped document."""

    def __init__(self, markdown="", **metadata):
        self.markdown = markdown
        self.html = ""
        self.metadata = metadata


def make_pdf_bytes(
    text: str = "Research paper body text.",
    title: str = "A Study",
    author: str = "A. Author",
) -> bytes:
    """Create a real single-page PDF using pypdf."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title, "/Author": author})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestArticleFromDocument:
    """Firecrawl documents must map onto our Article model reliably."""

    def test_maps_markdown_and_metadata(self):
        document = FakeDocument(
            markdown="# Title\n\nSome **body** text.",
            title="Real Title",
            author="Jane Doe",
            sourceURL="https://example.com/a",
            publishedTime="2025-09-01",
        )
        article = article_from_document(document)
        assert article.title == "Real Title"
        assert article.author == "Jane Doe"
        assert article.url == "https://example.com/a"
        assert article.published == "2025-09-01"
        assert "Some **body** text." in article.text

    def test_missing_metadata_is_tolerated(self):
        article = article_from_document(
            FakeDocument(markdown="body"), "https://fallback"
        )
        assert article.title == ""
        assert article.url == "https://fallback"

    def test_falls_back_to_html_when_no_markdown(self):
        document = FakeDocument(markdown="")
        document.html = "<p>hello</p>"
        assert "hello" in article_from_document(document).text


class TestScrapeUrl:
    """Web scraping is the primary ingestion path for blog posts."""

    def test_returns_article_with_cleaned_text(self):
        client = FakeFirecrawl(FakeDocument(markdown="Body text here.", title="Post"))
        article = scrape_url("https://example.com/post", client=client)
        assert article.kind is SourceKind.URL
        assert article.title == "Post"
        assert article.text == "Body text here."

    def test_requests_ad_blocking_and_main_content_only(self):
        client = FakeFirecrawl(FakeDocument(markdown="Body."))
        scrape_url("https://example.com/post", client=client)
        _, kwargs = client.calls[0]
        assert kwargs["block_ads"] is True
        assert kwargs["only_main_content"] is True
        assert kwargs["formats"] == ["markdown"]

    def test_truncates_overlong_content(self):
        client = FakeFirecrawl(FakeDocument(markdown="word " * 5000))
        article = scrape_url("https://example.com/post", client=client, max_chars=500)
        assert article.truncated is True
        assert len(article.text) <= 500

    def test_empty_content_raises_ingestion_error(self):
        client = FakeFirecrawl(FakeDocument(markdown="   "))
        with pytest.raises(IngestionError) as exc:
            scrape_url("https://example.com/post", client=client)
        assert exc.value.hint

    def test_invalid_url_is_rejected_before_calling_client(self):
        client = FakeFirecrawl(FakeDocument(markdown="body"))
        with pytest.raises(InputError):
            scrape_url("not a url", client=client)
        assert client.calls == []

    def test_missing_api_key_raises_configuration_error(self):
        with pytest.raises(ConfigurationError):
            scrape_url("https://example.com/post", api_key="")

    def test_provider_failure_becomes_typed_ingestion_error(self, monkeypatch):
        monkeypatch.setattr(config, "MAX_RETRIES", 1)  # keep the test fast
        client = FakeFirecrawl(error=RuntimeError("500 server error"))
        with pytest.raises(IngestionError):
            scrape_url("https://example.com/post", client=client)


# ─────────────────────────────────────────────
#  FEATURE 1: PDF & research paper ingestion
# ────────────────────────────────────────────
class TestExtractPdfText:
    """PDF parsing must work offline and fail clearly on bad input."""

    def test_non_pdf_payload_is_rejected(self):
        with pytest.raises(IngestionError) as exc:
            extract_pdf_text(b"<html>not a pdf</html>")
        assert "not a valid PDF" in exc.value.message

    def test_reads_document_metadata_and_page_count(self):
        data = make_pdf_bytes(title="Attention Is Useful", author="A. Author")
        extracted = extract_pdf_text(data)
        assert extracted["title"] == "Attention Is Useful"
        assert extracted["author"] == "A. Author"
        assert extracted["pages"] == 1
        assert extracted["pages_read"] == 1

    def test_page_budget_is_respected(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)

        extracted = extract_pdf_text(buffer.getvalue(), max_pages=2)
        assert extracted["pages"] == 5
        assert extracted["pages_read"] == 2

    def test_blank_page_reports_no_text(self):
        """Scanned PDFs have no selectable text - the caller must be told."""
        extracted = extract_pdf_text(make_pdf_bytes())
        assert extracted["text"] == ""


class TestPdfTitleHeuristic:
    """Research papers often lack metadata, so the first line is used."""

    def test_skips_identifiers_and_numeric_lines(self):
        from podcast.ingestion import _title_from_text

        text = (
            "arXiv:2401.00001v1 [cs.CL]\n"
            "1234567890 12345 67890 1234567\n"
            "Scaling Laws for Podcast Generation\n"
            "Abstract: this paper studies..."
        )
        assert _title_from_text(text) == "Scaling Laws for Podcast Generation"

    def test_returns_empty_when_nothing_suits(self):
        from podcast.ingestion import _title_from_text

        assert _title_from_text("123 456\n789 012\n") == ""


class TestBuildPdfArticle:
    """The Article built from a PDF feeds straight into the script writer."""

    def test_builds_article_from_extracted_content(self):
        extracted = {"text": "Body of paper. " * 10, "title": "Paper", "author": "A"}
        article = build_pdf_article(extracted, filename="paper.pdf")
        assert article.kind is SourceKind.PDF
        assert article.title == "Paper"
        assert article.author == "A"
        assert article.text.startswith("Body of paper.")

    def test_explicit_title_wins_over_extracted_title(self):
        extracted = {"text": "Body.", "title": "Extracted", "author": ""}
        assert build_pdf_article(extracted, title="Chosen").title == "Chosen"

    def test_filename_used_when_no_title_available(self):
        extracted = {"text": "Body.", "title": "", "author": ""}
        assert (
            build_pdf_article(extracted, filename="my-paper.pdf").title
            == "my-paper.pdf"
        )

    def test_empty_text_raises_with_ocr_hint(self):
        with pytest.raises(IngestionError) as exc:
            build_pdf_article({"text": "   ", "title": "x", "author": ""})
        assert "OCR" in exc.value.hint

    def test_truncation_flag(self):
        extracted = {"text": "word " * 500, "title": "t", "author": ""}
        article = build_pdf_article(extracted, max_chars=100)
        assert article.truncated is True and len(article.text) <= 100


class TestLoadArticleFromPdfBytes:
    """Covers the Streamlit file-upload path."""

    def test_wires_extraction_into_an_article(self, monkeypatch):
        monkeypatch.setattr(
            "podcast.ingestion.extract_pdf_text",
            lambda data, max_pages=config.PDF_MAX_PAGES: {
                "text": "Uploaded document body. " * 5,
                "title": "Uploaded Paper",
                "author": "Author",
                "pages": 3,
                "pages_read": 3,
            },
        )
        article = load_article_from_pdf_bytes(
            make_pdf_bytes(), filename="upload.pdf", url="https://example.com/u.pdf"
        )
        assert article.kind is SourceKind.PDF
        assert article.title == "Uploaded Paper"
        assert "document body" in article.text

    def test_rejects_non_pdf_bytes(self):
        with pytest.raises(IngestionError):
            load_article_from_pdf_bytes(b"just text", filename="a.txt")


# ─────────────────────────────────────────────
#  FEATURE 2: RSS feed monitoring
# ─────────────────────────────────────────────
class TestParseFeed:
    """Feed parsing must surface every field the monitor needs."""

    def test_parses_entries(self):
        entries = parse_feed(RSS_SAMPLE)
        assert len(entries) == 2
        first = entries[0]
        assert first.title == "Why streaming data matters"
        assert first.link == "https://example.com/streaming-data"
        assert first.guid == "https://example.com/streaming-data"
        assert first.published.startswith("Mon, 01 Sep 2025")
        assert "Streaming data" in first.summary

    def test_guid_falls_back_to_link(self):
        entries = parse_feed(RSS_SAMPLE)
        assert entries[0].identity() == "https://example.com/streaming-data"
        assert entries[1].identity() == "post-2"

    def test_empty_feed_yields_no_entries(self):
        assert parse_feed("") == []

    def test_feed_title(self):
        assert feed_title(RSS_SAMPLE) == "Example Tech Blog"

    def test_feed_entry_from_parsed_handles_missing_fields(self):
        entry = feed_entry_from_parsed({})
        assert entry.title == "" and entry.link == "" and entry.identity() == ""


class TestFetchFeedEntries:
    """Feed fetching is the entry point of the monitoring feature."""

    def test_returns_entries_with_user_agent(self):
        session = FakeSession(FakeResponse(text=RSS_SAMPLE))
        entries = fetch_feed_entries("https://example.com/feed.xml", session=session)
        assert len(entries) == 2
        url, kwargs = session.calls[0]
        assert url == "https://example.com/feed.xml"
        assert "User-Agent" in kwargs["headers"]
        assert kwargs["timeout"] == config.REQUEST_TIMEOUT

    def test_limit_is_applied(self):
        session = FakeSession(FakeResponse(text=RSS_SAMPLE))
        entries = fetch_feed_entries(
            "https://example.com/feed.xml", limit=1, session=session
        )
        assert len(entries) == 1

    def test_invalid_url_rejected_before_network(self):
        session = FakeSession(FakeResponse(text=RSS_SAMPLE))
        with pytest.raises(InputError):
            fetch_feed_entries("nonsense", session=session)
        assert session.calls == []

    def test_feed_without_entries_raises(self):
        session = FakeSession(FakeResponse(text="<rss><channel></channel></rss>"))
        with pytest.raises(IngestionError):
            fetch_feed_entries("https://example.com/feed.xml", session=session)

    def test_http_failure_is_typed(self, monkeypatch):
        monkeypatch.setattr(config, "MAX_RETRIES", 1)
        session = FakeSession(FakeResponse(status=500))
        with pytest.raises(IngestionError):
            fetch_feed_entries("https://example.com/feed.xml", session=session)


class TestFeedMonitor:
    """The monitor guarantees only genuinely new articles become episodes."""

    FEED = "https://example.com/feed.xml"

    def test_first_run_reports_all_entries_as_new(self, tmp_path):
        monitor = FeedMonitor(tmp_path / "state.json")
        entries = parse_feed(RSS_SAMPLE)
        assert len(monitor.new_entries(self.FEED, entries)) == 2

    def test_processed_entries_are_not_repeated(self, tmp_path):
        monitor = FeedMonitor(tmp_path / "state.json")
        entries = parse_feed(RSS_SAMPLE)
        monitor.mark_entries_seen(self.FEED, entries[:1])

        new = monitor.new_entries(self.FEED, entries)
        assert [entry.guid for entry in new] == ["post-2"]

    def test_state_is_persisted_to_disk(self, tmp_path):
        state_file = tmp_path / "state.json"
        FeedMonitor(state_file).mark_seen(self.FEED, ["a", "b"])

        assert FeedMonitor(state_file).seen(self.FEED) == ["a", "b"]

    def test_marking_twice_does_not_duplicate(self, tmp_path):
        monitor = FeedMonitor(tmp_path / "state.json")
        monitor.mark_seen(self.FEED, ["a"])
        monitor.mark_seen(self.FEED, ["a", "b"])
        assert monitor.seen(self.FEED) == ["a", "b"]

    def test_state_is_scoped_per_feed(self, tmp_path):
        monitor = FeedMonitor(tmp_path / "state.json")
        monitor.mark_seen(self.FEED, ["a"])
        assert monitor.seen("https://other.example.com/feed") == []

    def test_reset_for_one_feed(self, tmp_path):
        monitor = FeedMonitor(tmp_path / "state.json")
        monitor.mark_seen(self.FEED, ["a"])
        monitor.mark_seen("https://other.example.com/feed", ["b"])
        monitor.reset(self.FEED)
        assert monitor.seen(self.FEED) == []
        assert monitor.seen("https://other.example.com/feed") == ["b"]

    def test_reset_all_feeds(self, tmp_path):
        monitor = FeedMonitor(tmp_path / "state.json")
        monitor.mark_seen(self.FEED, ["a"])
        monitor.reset()
        assert monitor.seen(self.FEED) == []


class TestLoadArticleFromFeedEntry:
    """One feed item becomes one Article, resiliently."""

    def test_scrapes_the_entry_link(self):
        client = FakeFirecrawl(
            FakeDocument(markdown="Article body.", title="From scrape")
        )
        entry = FeedEntry(title="Feed title", link="https://example.com/post")
        article = load_article_from_feed_entry(entry, client=client)
        assert article.kind is SourceKind.RSS
        assert article.text == "Article body."
        assert article.title == "From scrape"

    def test_entry_without_link_uses_summary(self):
        entry = FeedEntry(title="T", summary="Short summary text.")
        article = load_article_from_feed_entry(entry, client=FakeFirecrawl())
        assert article.text == "Short summary text."
        assert article.kind is SourceKind.RSS

    def test_scrape_failure_falls_back_to_summary(self, monkeypatch):
        monkeypatch.setattr(config, "MAX_RETRIES", 1)
        entry = FeedEntry(
            title="T", link="https://example.com/post", summary="Fallback summary."
        )
        client = FakeFirecrawl(error=RuntimeError("403 forbidden"))
        article = load_article_from_feed_entry(entry, client=client)
        assert article.text == "Fallback summary."
        assert article.url == "https://example.com/post"

    def test_entry_with_nothing_usable_raises(self):
        with pytest.raises(InputError):
            load_article_from_feed_entry(FeedEntry(title="", link=""))


class TestSourceDispatcher:
    """PDF links must never be sent to the HTML scraper."""

    def test_pdf_url_routes_to_pdf_pipeline(self, monkeypatch):
        captured = {}

        def fake_pdf(url, **kwargs):
            captured["url"] = url
            return Article(text="pdf body", kind=SourceKind.PDF)

        monkeypatch.setattr("podcast.ingestion.load_article_from_pdf_url", fake_pdf)
        article = load_article_from_url("https://arxiv.org/pdf/2401.00001.pdf")
        assert article.kind is SourceKind.PDF
        assert captured["url"].endswith("2401.00001.pdf")

    def test_html_url_routes_to_scraper(self, monkeypatch):
        captured = {}

        def fake_scrape(url, **kwargs):
            captured["url"] = url
            return Article(text="html body")

        monkeypatch.setattr("podcast.ingestion.scrape_url", fake_scrape)
        article = load_article_from_url("https://example.com/blog")
        assert article.kind is SourceKind.URL
        assert captured["url"] == "https://example.com/blog"

    def test_invalid_url_rejected(self):
        with pytest.raises(InputError):
            load_article_from_url("")
