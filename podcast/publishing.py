"""
Episode publishing: local archive, RSS feed, webhook and YouTube.
================================================================

Feature 7 - One-click publishing to Spotify, YouTube and other platforms
    Every destination is exposed through a uniform ``publish()`` dispatcher so
    the UI can offer a checkbox list:

    * **Local archive** - writes the MP3 plus a JSON sidecar into
      ``outputs/episodes``.
    * **RSS feed** - rebuilds a valid RSS 2.0 + iTunes feed from the archive,
      which is how Spotify, Apple Podcasts and every other podcast app ingest
      shows (Spotify has no public episode-upload API).
    * **YouTube** - uploads an MP4 (cover art + narration) through the YouTube
      Data API v3 when ``google-api-python-client`` credentials are available.
    * **Webhook** - POSTs the MP3 and metadata as multipart form data, which
      covers Zapier, Make.com and any custom endpoint.

Nothing here mutates the episode: publishing is additive and each destination
reports its own success or failure.
"""

from __future__ import annotations

import json
import mimetypes
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

import requests

from podcast import config
from podcast.errors import (
    ConfigurationError,
    PodcastError,
    PublishingError,
    classify_exception,
)
from podcast.models import EpisodeResult, PublishResult
from podcast.utils import (
    format_bytes,
    get_logger,
    read_json_file,
    retry_call,
    sanitize_filename,
    slugify,
    write_json_file,
)

LOGGER = get_logger("publishing")

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)

MANIFEST_NAME = "feed.json"


def archive_dir() -> Any:
    """Directory holding published episodes."""
    return config.ARCHIVE_DIR


def manifest_path() -> Any:
    """Path of the feed manifest (used to rebuild the feed in order)."""
    return archive_dir() / MANIFEST_NAME


# ─────────────────────────────────────────────
#  Local archive
# ─────────────────────────────────────────────
def publish_to_archive(
    episode: EpisodeResult, *, directory: Any = None
) -> PublishResult:
    """Write the episode MP3 and a JSON sidecar into the archive directory."""
    target_dir = directory or archive_dir()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{episode.created_at.strftime('%Y%m%d-%H%M%S')}-{episode.metadata.slug}"
        audio_file = target_dir / sanitize_filename(
            f"{stem}.mp3", fallback="episode", extension="mp3"
        )
        sidecar_file = audio_file.with_suffix(".json")

        if episode.has_audio:
            audio_file.write_bytes(episode.audio_bytes)
        write_json_file(sidecar_file, episode.as_dict())

        if episode.has_audio:
            _append_to_manifest(
                {
                    "title": episode.metadata.title,
                    "description": episode.metadata.description,
                    "tags": episode.metadata.tags,
                    "language": episode.metadata.language,
                    "audio_file": audio_file.name,
                    "size_bytes": len(episode.audio_bytes),
                    "duration_seconds": round(episode.duration_seconds, 1),
                    "source_url": episode.article.url,
                    "published": episode.created_at.astimezone(timezone.utc).isoformat(),
                },
                directory=target_dir,
            )

        LOGGER.info("Archived episode '%s' to %s", episode.metadata.title, target_dir)
        return PublishResult(
            platform="archive",
            ok=True,
            message=(
                f"Saved {audio_file.name} ({format_bytes(len(episode.audio_bytes))})"
                if episode.has_audio
                else f"Saved metadata only ({sidecar_file.name})"
            ),
            location=str(audio_file),
        )
    except OSError as exc:
        raise PublishingError(
            f"Could not write the episode to disk ({exc}).",
            hint="Check that the outputs directory is writable.",
        ) from exc


def _append_to_manifest(entry: Dict[str, Any], *, directory: Any = None) -> None:
    """Add an episode to the feed manifest, newest first."""
    path = (directory or archive_dir()) / MANIFEST_NAME
    manifest = read_json_file(path, {"episodes": []})
    episodes = manifest.get("episodes")
    if not isinstance(episodes, list):
        episodes = []
    episodes.insert(0, entry)
    manifest["episodes"] = episodes[: config.FEED_MAX_ITEMS]
    write_json_file(path, manifest)


def load_manifest(directory: Any = None) -> List[Dict[str, Any]]:
    """Read the archive manifest as a list of episode records."""
    manifest = read_json_file((directory or archive_dir()) / MANIFEST_NAME, {})
    episodes = manifest.get("episodes")
    return episodes if isinstance(episodes, list) else []


# ─────────────────────────────────────────────
#  FEATURE 7: RSS feed (Spotify / Apple / any podcast app)
# ─────────────────────────────────────────────
def _itunes(tag: str) -> str:
    """Qualified iTunes namespace tag."""
    return f"{{{ITUNES_NS}}}{tag}"


def _atom(tag: str) -> str:
    """Qualified Atom namespace tag."""
    return f"{{{ATOM_NS}}}{tag}"


def _enclosure_url(record: Dict[str, Any], base_url: str) -> str:
    """Absolute enclosure URL for an episode (falls back to a relative path)."""
    filename = quote(str(record.get("audio_file", "")).strip())
    if not filename:
        return ""
    if not base_url:
        return filename
    return urljoin(base_url.rstrip("/") + "/", filename)


def _episode_identity(record: Dict[str, Any]) -> str:
    """Stable GUID for an episode record."""
    source = str(record.get("source_url") or "").strip()
    filename = str(record.get("audio_file") or "").strip()
    return source or filename or slugify(str(record.get("title", ""))) or "episode"


def _pub_date(record: Dict[str, Any]) -> str:
    """RFC-822 publication date required by RSS."""
    raw = str(record.get("published") or "")
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return format_datetime(parsed.astimezone(timezone.utc))


def build_feed_xml(
    records: List[Dict[str, Any]],
    *,
    base_url: str = "",
    title: str = config.FEED_TITLE,
    description: str = config.FEED_DESCRIPTION,
    language: str = config.FEED_LANGUAGE,
    link: str = "",
    max_items: int = config.FEED_MAX_ITEMS,
) -> str:
    """Build an RSS 2.0 feed with iTunes extensions from archive records.

    Args:
        records: Episode records, newest first.
        base_url: Public base URL hosting the MP3 files. Spotify and Apple
            Podcasts require web-reachable enclosure URLs.
        title: Podcast (channel) title.
        description: Channel description.
        language: Channel language code.
        link: Public URL of the show page.
        max_items: Maximum number of episodes to include.

    Returns:
        The serialised feed XML.
    """
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = title
    channel_link = link or base_url or "https://example.com/podcast"
    ET.SubElement(channel, "link").text = channel_link
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = language or config.FEED_LANGUAGE
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )
    ET.SubElement(channel, _itunes("author")).text = title
    ET.SubElement(channel, _itunes("explicit")).text = "false"
    ET.SubElement(channel, _atom("link"), {"rel": "self", "href": channel_link})

    if records:
        ET.SubElement(channel, _itunes("image"), {"href": str(records[0].get("image_url", ""))})

    for record in records[:max_items]:
        item = ET.SubElement(channel, "item")
        item_title = str(record.get("title") or "Untitled Episode")
        item_description = str(record.get("description") or item_title)
        ET.SubElement(item, "title").text = item_title
        ET.SubElement(item, "description").text = item_description
        ET.SubElement(item, "pubDate").text = _pub_date(record)

        guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
        guid.text = _episode_identity(record)

        enclosure = _enclosure_url(record, base_url)
        if enclosure:
            ET.SubElement(
                item,
                "enclosure",
                {
                    "url": enclosure,
                    "length": str(int(record.get("size_bytes") or 0)),
                    "type": "audio/mpeg",
                },
            )

        duration = int(round(float(record.get("duration_seconds") or 0)))
        if duration > 0:
            ET.SubElement(item, _itunes("duration")).text = str(duration)

        tags = record.get("tags") or []
        if isinstance(tags, list) and tags:
            ET.SubElement(item, _itunes("keywords")).text = ",".join(str(tag) for tag in tags)

        source = str(record.get("source_url") or "").strip()
        if source:
            ET.SubElement(item, "link").text = source
            ET.SubElement(item, _itunes("subtitle")).text = item_description[:255]

    return ET.tostring(rss, encoding="unicode", xml_declaration=True)


def publish_to_rss(
    episode: EpisodeResult,
    *,
    base_url: str = "",
    directory: Any = None,
    feed_file: Any = None,
    show_title: str = config.FEED_TITLE,
    show_description: str = config.FEED_DESCRIPTION,
) -> PublishResult:
    """Archive the episode and rebuild the podcast RSS feed.

    This is the supported distribution route for Spotify, Apple Podcasts,
    YouTube Music and every other podcast directory.
    """
    publish_to_archive(episode, directory=directory)
    target_dir = directory or archive_dir()
    target_feed = feed_file or (target_dir.parent / "feed.xml")

    records = load_manifest(target_dir)
    xml = build_feed_xml(
        records,
        base_url=base_url,
        title=show_title,
        description=show_description,
        language=episode.metadata.language,
        link=base_url,
    )
    try:
        target_feed.parent.mkdir(parents=True, exist_ok=True)
        target_feed.write_text(xml, encoding="utf-8")
    except OSError as exc:
        raise PublishingError(
            f"Could not write the RSS feed ({exc}).",
            hint="Check that the outputs directory is writable.",
        ) from exc

    message = f"Feed updated with {len(records)} episode(s)"
    if not base_url:
        message += (
            " - set a public base URL so Spotify can reach the MP3 files"
        )
    LOGGER.info("RSS feed written to %s (%d episode(s))", target_feed, len(records))
    return PublishResult(
        platform="rss",
        ok=True,
        message=message,
        location=str(target_feed),
        url=base_url,
    )


# ─────────────────────────────────────────────
#  Webhook (Zapier / Make / custom endpoints)
# ─────────────────────────────────────────────
def publish_to_webhook(
    episode: EpisodeResult,
    webhook_url: str,
    *,
    session: Any = None,
    timeout: int = config.REQUEST_TIMEOUT,
    attempts: Optional[int] = None,
) -> PublishResult:
    """POST the episode to a webhook as multipart form data.

    The payload carries the MP3 under ``file`` plus flat metadata fields that
    automation platforms can map directly.
    """
    from podcast.utils import validate_url

    target = validate_url(webhook_url)
    http = session or requests
    filename = sanitize_filename(
        f"{episode.metadata.slug}.mp3", fallback="episode", extension="mp3"
    )
    mime = mimetypes.guess_type(filename)[0] or "audio/mpeg"
    fields = {
        "title": episode.metadata.title,
        "description": episode.metadata.description,
        "language": episode.metadata.language,
        "style": episode.script.style,
        "source_url": episode.article.url,
        "duration_seconds": str(round(episode.duration_seconds, 1)),
        "tags": json.dumps(episode.metadata.tags),
    }

    def _post() -> Any:
        if episode.has_audio:
            return http.post(
                target,
                data=fields,
                files={"file": (filename, episode.audio_bytes, mime)},
                timeout=timeout,
            )
        return http.post(target, data=fields, timeout=timeout)

    try:
        response = retry_call(
            _post,
            attempts=attempts if attempts and attempts > 0 else config.MAX_RETRIES,
            description=f"webhook {target}",
            logger=LOGGER,
        )
        status = getattr(response, "status_code", 0)
        if status >= 400:
            raise PublishingError(
                f"The webhook responded with HTTP {status}.",
                hint="Check the endpoint URL and that it accepts multipart uploads.",
            )
    except PublishingError:
        raise
    except Exception as exc:
        raise classify_exception(exc, stage="publishing") from exc

    response_url = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            response_url = str(payload.get("url") or payload.get("location") or "")
    except Exception:  # noqa: BLE001 - response body is optional
        response_url = ""

    LOGGER.info("Webhook delivered episode to %s (HTTP %s)", target, status)
    return PublishResult(
        platform="webhook",
        ok=True,
        message=f"Delivered to {target} (HTTP {status})",
        url=response_url,
    )


# ─────────────────────────────────────────────
#  YouTube (Data API v3)
# ─────────────────────────────────────────────
try:  # optional dependency - only needed for YouTube uploads
    from googleapiclient.http import MediaFileUpload  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    MediaFileUpload = None  # type: ignore

try:  # optional dependency
    from googleapiclient.discovery import build as _google_build  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    _google_build = None  # type: ignore


def build_youtube_client(
    *,
    credentials: Any = None,
    credentials_file: Any = None,
    client_id: str = "",
    client_secret: str = "",
    refresh_token: str = "",
) -> Any:
    """Create an authenticated YouTube API client.

    Credentials are resolved in order: an explicit ``credentials`` object, a
    token file, then the ``client_id``/``client_secret``/``refresh_token``
    trio (typically supplied through ``st.secrets`` or environment variables).

    Raises:
        ConfigurationError: when no usable credentials are configured.
    """
    if _google_build is None:  # pragma: no cover - optional dependency
        raise ConfigurationError(
            "YouTube publishing requires the Google API client libraries.",
            hint="Install them with: pip install google-api-python-client google-auth",
        )

    if credentials is None:
        try:
            from google.oauth2.credentials import Credentials
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ConfigurationError(
                "YouTube publishing requires the google-auth library.",
                hint="Install it with: pip install google-auth",
            ) from exc

        if credentials_file:
            if not os.path.exists(credentials_file):
                raise ConfigurationError(
                    f"YouTube token file not found: {credentials_file}",
                    hint="Point the setting at a valid authorized-user token JSON file.",
                )
            credentials = Credentials.from_authorized_user_file(
                str(credentials_file), list(config.YOUTUBE_UPLOAD_SCOPES)
            )
        elif client_id and client_secret and refresh_token:
            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=list(config.YOUTUBE_UPLOAD_SCOPES),
            )
        else:
            raise ConfigurationError(
                "No YouTube credentials were provided.",
                hint=(
                    "Supply a token file, or client_id + client_secret + refresh_token "
                    "for an account with the youtube.upload scope."
                ),
            )

    return _google_build(
        config.YOUTUBE_API_SERVICE,
        config.YOUTUBE_API_VERSION,
        credentials=credentials,
        cache_discovery=False,
    )


def build_youtube_video(
    episode: EpisodeResult,
    *,
    cover_bytes: Optional[bytes] = None,
    size: tuple = (1280, 720),
) -> bytes:
    """Render an MP4 (still cover + narration) suitable for YouTube.

    Requires ``moviepy`` and a working ``ffmpeg`` binary, because YouTube only
    accepts video files.

    Raises:
        PublishingError: when the rendering stack is unavailable.
    """
    try:
        from moviepy import AudioFileClip, ColorClip, ImageClip
    except ImportError as exc:
        raise PublishingError(
            "Creating a YouTube video needs the 'moviepy' package and ffmpeg.",
            hint=(
                "Install them with: pip install moviepy && "
                "(apt-get install ffmpeg | brew install ffmpeg)"
            ),
        ) from exc

    import tempfile

    with tempfile.TemporaryDirectory() as workdir:
        audio_path = os.path.join(workdir, "narration.mp3")
        video_path = os.path.join(workdir, "episode.mp4")
        with open(audio_path, "wb") as handle:
            handle.write(episode.audio_bytes)

        audio = AudioFileClip(audio_path)
        if cover_bytes:
            cover_path = os.path.join(workdir, "cover.jpg")
            with open(cover_path, "wb") as handle:
                handle.write(cover_bytes)
            base = ImageClip(cover_path).with_duration(audio.duration).resized(size)
        else:
            base = ColorClip(size=size, color=(15, 12, 41)).with_duration(audio.duration)

        video = base.with_audio(audio)
        video.write_videofile(
            video_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            logger=None,
        )
        video.close()
        audio.close()
        with open(video_path, "rb") as handle:
            return handle.read()


def upload_to_youtube(
    episode: EpisodeResult,
    *,
    client: Any = None,
    credentials: Any = None,
    credentials_file: Any = None,
    client_id: str = "",
    client_secret: str = "",
    refresh_token: str = "",
    privacy: str = config.YOUTUBE_PRIVACY_STATUS,
    video_bytes: Optional[bytes] = None,
    cover_bytes: Optional[bytes] = None,
    title: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    attempts: Optional[int] = None,
) -> PublishResult:
    """Upload the episode to YouTube as a video.

    Args:
        client: Injected YouTube API client (used in tests).
        privacy: ``private``, ``unlisted`` or ``public``.
        video_bytes: Pre-rendered MP4. When omitted, the video is rendered with
            ``build_youtube_video`` (requires moviepy + ffmpeg).

    Raises:
        PublishingError: when audio is missing or the upload fails.
    """
    if not episode.has_audio:
        raise PublishingError(
            "There is no narration audio to upload.",
            hint="Generate the episode audio before publishing.",
        )
    if MediaFileUpload is None and client is None:  # pragma: no cover - optional dep
        raise ConfigurationError(
            "YouTube uploads require the Google API client libraries.",
            hint="Install them with: pip install google-api-python-client google-auth",
        )

    youtube = client or build_youtube_client(
        credentials=credentials,
        credentials_file=credentials_file,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )

    video = video_bytes if video_bytes is not None else build_youtube_video(
        episode, cover_bytes=cover_bytes
    )

    import tempfile

    body = {
        "snippet": {
            "title": (title or episode.metadata.title or "Podcast episode")[:100],
            "description": (description or episode.metadata.description)[:5000],
            "tags": (tags or episode.metadata.tags or list(config.YOUTUBE_DEFAULT_TAGS))[:30],
            "categoryId": config.YOUTUBE_CATEGORY_ID,
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
        handle.write(video)
        temp_path = handle.name

    try:
        def _upload() -> Any:
            media = MediaFileUpload(temp_path, mimetype="video/mp4", resumable=True)
            request = youtube.videos().insert(
                part="snippet,status", body=body, media_body=media
            )
            return request.execute()

        try:
            response = retry_call(
                _upload,
                attempts=attempts if attempts and attempts > 0 else config.MAX_RETRIES,
                description="youtube upload",
                logger=LOGGER,
            )
        except Exception as exc:
            raise classify_exception(exc, stage="publishing") from exc
    finally:
        try:
            os.unlink(temp_path)
        except OSError:  # pragma: no cover - best effort cleanup
            pass

    video_id = str((response or {}).get("id") or "")
    if not video_id:
        raise PublishingError(
            "YouTube accepted the upload but returned no video id.",
            hint="Check your quota and the API response permissions.",
        )

    url = f"https://youtu.be/{video_id}"
    LOGGER.info("Uploaded episode to YouTube: %s", url)
    return PublishResult(
        platform="youtube",
        ok=True,
        message=f"Uploaded as {privacy} ({video_id})",
        url=url,
        location=video_id,
    )


# ─────────────────────────────────────────────
#  FEATURE 7: unified dispatcher
# ─────────────────────────────────────────────
def publish_one(
    episode: EpisodeResult,
    platform_key: str,
    *,
    webhook_url: str = "",
    base_url: str = "",
    directory: Any = None,
    feed_file: Any = None,
    youtube_client: Any = None,
    youtube_video: Optional[bytes] = None,
    youtube_privacy: str = config.YOUTUBE_PRIVACY_STATUS,
) -> PublishResult:
    """Publish an episode to a single destination.

    Args:
        episode: The finished episode.
        platform_key: Key or label from :data:`podcast.config.PLATFORMS`.
        webhook_url: Required for the ``webhook`` destination.
        base_url: Public URL hosting the episode files (RSS/Spotify).
        directory: Archive directory override (used in tests).
        feed_file: RSS output path override (used in tests).
        youtube_client: Injected YouTube client.
        youtube_video: Pre-rendered MP4 for YouTube.

    Returns:
        A :class:`PublishResult`; failures are reported, never raised, so one
        destination cannot abort the others.

    Raises:
        ConfigurationError: for a missing required setting (e.g. no webhook URL).
    """
    spec = config.get_platform(platform_key)
    try:
        if spec.mode == "archive":
            return publish_to_archive(episode, directory=directory)
        if spec.mode == "rss":
            return publish_to_rss(
                episode, base_url=base_url, directory=directory, feed_file=feed_file
            )
        if spec.mode == "webhook":
            if not (webhook_url or "").strip():
                raise ConfigurationError(
                    "A webhook URL is required to publish to a webhook.",
                    hint="Paste the endpoint URL (Zapier, Make.com or your own API).",
                )
            return publish_to_webhook(episode, webhook_url)
        if spec.mode == "youtube":
            return upload_to_youtube(
                episode,
                client=youtube_client,
                privacy=youtube_privacy,
                video_bytes=youtube_video,
            )
        raise PublishingError(
            f"Unknown publishing destination '{spec.key}'.",
            hint="Pick one of the destinations shown in the publishing section.",
        )
    except PodcastError as exc:
        LOGGER.warning("Publishing to %s failed: %s", spec.key, exc.message)
        message = exc.message
        hint = getattr(exc, "hint", "")
        if hint:
            message = f"{message} {hint}"
        return PublishResult(platform=spec.key, ok=False, message=message)


def publish_episode(
    episode: EpisodeResult,
    platform_keys: Any,
    *,
    webhook_url: str = "",
    base_url: str = "",
    directory: Any = None,
    feed_file: Any = None,
    youtube_client: Any = None,
    youtube_video: Optional[bytes] = None,
    youtube_privacy: str = config.YOUTUBE_PRIVACY_STATUS,
) -> List[PublishResult]:
    """Publish an episode to every selected destination.

    Args:
        platform_keys: Iterable of platform keys or labels.

    Returns:
        One :class:`PublishResult` per destination, in the order requested.
    """
    keys = [platform_keys] if isinstance(platform_keys, str) else list(platform_keys or [])
    results: List[PublishResult] = []
    for key in keys:
        result = publish_one(
            episode,
            key,
            webhook_url=webhook_url,
            base_url=base_url,
            directory=directory,
            feed_file=feed_file,
            youtube_client=youtube_client,
            youtube_video=youtube_video,
            youtube_privacy=youtube_privacy,
        )
        results.append(result)
        LOGGER.info(
            "Publish %s -> %s (%s)",
            key,
            "ok" if result.ok else "failed",
            result.message,
        )
    return results