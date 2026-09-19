"""Tests for episode publishing (Feature 7)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from podcast import config
from podcast.errors import ConfigurationError, PublishingError
from podcast.models import (
    Article,
    EpisodeMetadata,
    EpisodeResult,
    PodcastScript,
    SourceKind,
)
from podcast.publishing import (
    build_feed_xml,
    load_manifest,
    publish_episode,
    publish_one,
    publish_to_archive,
    publish_to_rss,
    publish_to_webhook,
    upload_to_youtube,
)
from tests.conftest import make_mp3_bytes

ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def make_episode(*, with_audio: bool = True, title: str = "AI Teams Explained") -> EpisodeResult:
    """Build an EpisodeResult for publishing tests."""
    article = Article(
        text="Body text " * 20,
        title="Source Article",
        url="https://example.com/article",
        kind=SourceKind.URL,
    )
    script = PodcastScript(segments=[], style="solo")
    return EpisodeResult(
        metadata=EpisodeMetadata(
            title=title,
            description="A short episode about AI teams.",
            tags=["ai", "teams"],
            language="en",
        ),
        script=script,
        article=article,
        audio_bytes=make_mp3_bytes(1.0) if with_audio else b"",
        audio_filename="episode.mp3",
        duration_seconds=42.5,
    )


class TestArchivePublishing:
    """The local archive is the foundation of the RSS feed."""

    def test_writes_audio_and_sidecar(self, tmp_path):
        episode = make_episode()
        result = publish_to_archive(episode, directory=tmp_path)

        assert result.ok is True
        assert result.platform == "archive"
        mp3_files = list(tmp_path.glob("*.mp3"))
        sidecars = [path for path in tmp_path.glob("*.json") if path.name != "feed.json"]
        assert len(mp3_files) == 1 and len(sidecars) == 1
        assert mp3_files[0].read_bytes() == episode.audio_bytes

    def test_sidecar_contains_episode_metadata(self, tmp_path):
        publish_to_archive(make_episode(), directory=tmp_path)
        sidecar = next(tmp_path.glob("*.json"))
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        assert payload["title"] == "AI Teams Explained"
        assert payload["source_url"] == "https://example.com/article"
        assert payload["duration_seconds"] == 42.5

    def test_manifest_is_updated_newest_first(self, tmp_path):
        publish_to_archive(make_episode(title="First"), directory=tmp_path)
        publish_to_archive(make_episode(title="Second"), directory=tmp_path)

        records = load_manifest(tmp_path)
        assert [record["title"] for record in records] == ["Second", "First"]

    def test_metadata_only_episode_is_archived_without_manifest_entry(self, tmp_path):
        result = publish_to_archive(make_episode(with_audio=False), directory=tmp_path)
        assert result.ok is True
        assert list(tmp_path.glob("*.mp3")) == []
        assert load_manifest(tmp_path) == []


class TestFeedBuilder:
    """The feed is how Spotify and Apple Podcasts ingest the show."""

    def records(self):
        return [
            {
                "title": "Episode Two",
                "description": "Second episode",
                "tags": ["ai", "data"],
                "audio_file": "ep2.mp3",
                "size_bytes": 2048,
                "duration_seconds": 61.4,
                "source_url": "https://example.com/two",
                "published": "2025-09-02T10:00:00+00:00",
            },
            {
                "title": "Episode One",
                "description": "First episode",
                "audio_file": "ep1.mp3",
                "size_bytes": 1024,
                "duration_seconds": 30,
                "source_url": "https://example.com/one",
                "published": "2025-09-01T10:00:00+00:00",
            },
        ]

    def test_feed_parses_as_valid_xml(self):
        xml = build_feed_xml(self.records(), base_url="https://cdn.example.com/pod")
        root = ET.fromstring(xml)
        assert root.tag == "rss"
        assert root.find("./channel/title").text == config.FEED_TITLE

    def test_enclosure_urls_are_absolute_when_base_url_given(self):
        xml = build_feed_xml(self.records(), base_url="https://cdn.example.com/pod")
        root = ET.fromstring(xml)
        url = root.find("./channel/item/enclosure").get("url")
        assert url == "https://cdn.example.com/pod/ep2.mp3"

    def test_enclosure_falls_back_to_relative_path(self):
        xml = build_feed_xml(self.records())
        root = ET.fromstring(xml)
        assert root.find("./channel/item/enclosure").get("url") == "ep2.mp3"

    def test_itunes_extensions_are_present(self):
        root = ET.fromstring(build_feed_xml(self.records(), base_url="https://x.test"))
        item = root.find("./channel/item")
        assert item.find(f"{ITUNES_NS}duration").text == "61"
        assert item.find(f"{ITUNES_NS}keywords").text == "ai,data"
        assert root.find(f"./channel/{ITUNES_NS}explicit").text == "false"

    def test_guid_and_pubdate_are_set(self):
        root = ET.fromstring(build_feed_xml(self.records()))
        item = root.find("./channel/item")
        assert item.find("guid").text == "https://example.com/two"
        assert "Sep 2025" in item.find("pubDate").text

    def test_max_items_is_respected(self):
        root = ET.fromstring(build_feed_xml(self.records(), max_items=1))
        assert len(root.findall("./channel/item")) == 1

    def test_empty_feed_is_still_valid(self):
        root = ET.fromstring(build_feed_xml([]))
        assert root.find("./channel/title") is not None
        assert root.findall("./channel/item") == []

    def test_language_is_carried_on_the_channel(self):
        root = ET.fromstring(build_feed_xml(self.records(), language="pt"))
        assert root.find("./channel/language").text == "pt"


class TestRssPublishing:
    """Publishing to RSS also archives and rebuilds the feed file."""

    def test_writes_feed_and_archives_episode(self, tmp_path):
        episode = make_episode()
        result = publish_to_rss(
            episode,
            base_url="https://cdn.example.com/pod",
            directory=tmp_path / "episodes",
            feed_file=tmp_path / "feed.xml",
        )

        assert result.ok is True
        assert result.location.endswith("feed.xml")
        xml = (tmp_path / "feed.xml").read_text(encoding="utf-8")
        root = ET.fromstring(xml)
        assert root.find("./channel/item/title").text == "AI Teams Explained"
        assert list((tmp_path / "episodes").glob("*.mp3"))

    def test_missing_base_url_is_reported_in_the_message(self, tmp_path):
        result = publish_to_rss(
            make_episode(),
            directory=tmp_path / "episodes",
            feed_file=tmp_path / "feed.xml",
        )
        assert result.ok is True
        assert "base URL" in result.message

    def test_second_episode_is_appended_to_the_feed(self, tmp_path):
        common = {
            "base_url": "https://cdn.example.com/pod",
            "directory": tmp_path / "episodes",
            "feed_file": tmp_path / "feed.xml",
        }
        publish_to_rss(make_episode(title="First"), **common)
        publish_to_rss(make_episode(title="Second"), **common)

        root = ET.fromstring((tmp_path / "feed.xml").read_text(encoding="utf-8"))
        titles = [item.find("title").text for item in root.findall("./channel/item")]
        assert titles == ["Second", "First"]


class FakeResponse:
    """Minimal HTTP response stand-in."""

    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeWebhookSession:
    """Captures webhook requests."""

    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


class TestWebhookPublishing:
    """Webhooks reach Zapier, Make.com and custom endpoints."""

    def test_sends_multipart_with_audio_and_metadata(self):
        session = FakeWebhookSession()
        result = publish_to_webhook(
            make_episode(), "https://hooks.example.com/podcast", session=session
        )

        assert result.ok is True
        url, kwargs = session.calls[0]
        assert url == "https://hooks.example.com/podcast"
        assert kwargs["files"]["file"][0] == "ai-teams-explained.mp3"
        assert kwargs["data"]["title"] == "AI Teams Explained"
        assert json.loads(kwargs["data"]["tags"]) == ["ai", "teams"]

    def test_omits_file_when_there_is_no_audio(self):
        session = FakeWebhookSession()
        publish_to_webhook(make_episode(with_audio=False), "https://hooks.example.com/x", session=session)
        assert "files" not in session.calls[0][1]

    def test_response_url_is_captured(self):
        session = FakeWebhookSession(
            FakeResponse(payload={"url": "https://example.com/uploaded"})
        )
        result = publish_to_webhook(make_episode(), "https://hooks.example.com/x", session=session)
        assert result.url == "https://example.com/uploaded"

    def test_error_status_is_typed(self):
        session = FakeWebhookSession(FakeResponse(status_code=500))
        with pytest.raises(PublishingError):
            publish_to_webhook(make_episode(), "https://hooks.example.com/x", session=session)

    def test_invalid_url_is_rejected_before_posting(self):
        session = FakeWebhookSession()
        with pytest.raises(Exception):
            publish_to_webhook(make_episode(), "nonsense", session=session)
        assert session.calls == []


class FakeYouTubeRequest:
    """Records the insert call and replays a scripted response."""

    def __init__(self, response, error=None):
        self.response = response
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.response


class FakeYouTubeVideos:
    """Captures the parameters passed to ``videos().insert``."""

    def __init__(self, response, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def insert(self, **kwargs):
        self.calls.append(kwargs)
        return FakeYouTubeRequest(self.response, self.error)


class FakeYouTubeClient:
    """Minimal YouTube API client."""

    def __init__(self, response=None, error=None):
        resolved = {"id": "abc123"} if response is None else response
        self.videos_resource = FakeYouTubeVideos(resolved, error)

    def videos(self):
        return self.videos_resource


class TestYouTubePublishing:
    """YouTube uploads are driven through an injected client."""

    def test_uploads_video_and_returns_watch_url(self, monkeypatch):
        monkeypatch.setattr("podcast.publishing.MediaFileUpload", lambda *a, **k: object())
        client = FakeYouTubeClient()
        result = upload_to_youtube(make_episode(), client=client, video_bytes=b"MP4")

        assert result.ok is True
        assert result.url == "https://youtu.be/abc123"
        assert result.location == "abc123"

    def test_upload_body_carries_metadata(self, monkeypatch):
        monkeypatch.setattr("podcast.publishing.MediaFileUpload", lambda *a, **k: object())
        client = FakeYouTubeClient()
        upload_to_youtube(make_episode(), client=client, video_bytes=b"MP4")

        body = client.videos_resource.calls[0]["body"]
        assert body["snippet"]["title"] == "AI Teams Explained"
        assert body["snippet"]["categoryId"] == config.YOUTUBE_CATEGORY_ID
        assert body["status"]["privacyStatus"] == config.YOUTUBE_PRIVACY_STATUS

    def test_privacy_can_be_overridden(self, monkeypatch):
        monkeypatch.setattr("podcast.publishing.MediaFileUpload", lambda *a, **k: object())
        client = FakeYouTubeClient()
        upload_to_youtube(
            make_episode(), client=client, video_bytes=b"MP4", privacy="public"
        )
        assert client.videos_resource.calls[0]["body"]["status"]["privacyStatus"] == "public"

    def test_missing_audio_is_rejected(self):
        with pytest.raises(PublishingError):
            upload_to_youtube(make_episode(with_audio=False), client=FakeYouTubeClient())

    def test_response_without_id_is_rejected(self, monkeypatch):
        monkeypatch.setattr("podcast.publishing.MediaFileUpload", lambda *a, **k: object())
        client = FakeYouTubeClient(response={})
        with pytest.raises(PublishingError):
            upload_to_youtube(make_episode(), client=client, video_bytes=b"MP4")

    def test_upload_failure_is_typed(self, monkeypatch):
        monkeypatch.setattr("podcast.publishing.MediaFileUpload", lambda *a, **k: object())
        monkeypatch.setattr(config, "MAX_RETRIES", 1)
        client = FakeYouTubeClient(error=RuntimeError("quotaExceeded"))
        with pytest.raises(Exception):
            upload_to_youtube(make_episode(), client=client, video_bytes=b"MP4")

    def test_missing_credentials_raise_configuration_error(self):
        with pytest.raises(ConfigurationError):
            upload_to_youtube(make_episode(), video_bytes=b"MP4")


class TestPublishDispatcher:
    """One-click publishing fans out to the selected destinations."""

    def test_archive_destination(self, tmp_path):
        result = publish_one(make_episode(), "archive", directory=tmp_path)
        assert result.ok is True and result.platform == "archive"

    def test_rss_destination(self, tmp_path):
        result = publish_one(
            make_episode(),
            "rss",
            base_url="https://cdn.example.com/pod",
            directory=tmp_path / "episodes",
            feed_file=tmp_path / "feed.xml",
        )
        assert result.ok is True and result.platform == "rss"

    def test_spotify_maps_to_the_rss_feed(self, tmp_path):
        result = publish_one(
            make_episode(),
            "spotify",
            directory=tmp_path / "episodes",
            feed_file=tmp_path / "feed.xml",
        )
        assert result.ok is True
        assert (tmp_path / "feed.xml").exists()

    def test_webhook_without_url_reports_failure_not_crash(self):
        result = publish_one(make_episode(), "webhook")
        assert result.ok is False
        assert "webhook URL" in result.message

    def test_youtube_failure_does_not_raise(self):
        result = publish_one(make_episode(), "youtube")
        assert result.ok is False
        assert result.message

    def test_multiple_destinations_return_one_result_each(self, tmp_path):
        results = publish_episode(
            make_episode(),
            ["archive", "rss"],
            directory=tmp_path / "episodes",
            feed_file=tmp_path / "feed.xml",
        )
        assert [result.platform for result in results] == ["archive", "rss"]
        assert all(result.ok for result in results)

    def test_a_failing_destination_does_not_block_the_others(self, tmp_path):
        results = publish_episode(
            make_episode(),
            ["webhook", "archive"],  # webhook has no URL -> fails
            directory=tmp_path,
        )
        assert results[0].ok is False
        assert results[1].ok is True

    def test_labels_are_accepted_as_well_as_keys(self, tmp_path):
        result = publish_one(make_episode(), config.PLATFORM_LABELS[0], directory=tmp_path)
        assert result.ok is True

    def test_empty_selection_returns_no_results(self):
        assert publish_episode(make_episode(), []) == []