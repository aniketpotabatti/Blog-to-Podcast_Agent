"""
Shared helpers: retries, text chunking, validation and parsing.
=============================================================

Small, dependency-light utilities used by every pipeline layer. Nothing here
imports a provider SDK, which keeps the module trivially unit-testable.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar
from urllib.parse import urlparse

from podcast import config
from podcast.errors import InputError

T = TypeVar("T")

LOGGER_NAME = "blog_to_podcast"
_LOGGER_CONFIGURED = False


def get_logger(name: str = "") -> logging.Logger:
    """Return a child logger of the package logger."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def setup_logging(
    level: int = logging.INFO, log_to_file: bool = True
) -> logging.Logger:
    """Configure console (and optional file) logging exactly once."""
    global _LOGGER_CONFIGURED
    logger = logging.getLogger(LOGGER_NAME)
    if _LOGGER_CONFIGURED:
        return logger

    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    if log_to_file:
        try:
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                config.LOG_DIR / "app.log", encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:  # pragma: no cover - read-only filesystems
            pass

    _LOGGER_CONFIGURED = True
    return logger


# ─────────────────────────────────────────────
#  Retries
# ─────────────────────────────────────────────
def retry(
    attempts: int = config.MAX_RETRIES,
    base_delay: float = config.BACKOFF_BASE_SECONDS,
    max_delay: float = config.BACKOFF_MAX_SECONDS,
    retry_on: Sequence[type] = (Exception,),
    give_up_on: Sequence[type] = (),
    logger: Optional[logging.Logger] = None,
    description: str = "",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that wraps ``retry_call`` for easier use on functions."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        from functools import wraps

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return retry_call(
                func,
                *args,
                attempts=attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                retry_on=retry_on,
                give_up_on=give_up_on,
                logger=logger,
                description=description,
                **kwargs,
            )

        return wrapper

    return decorator


def retry_call(
    func: Callable[..., T],
    *args: Any,
    attempts: int = config.MAX_RETRIES,
    base_delay: float = config.BACKOFF_BASE_SECONDS,
    max_delay: float = config.BACKOFF_MAX_SECONDS,
    retry_on: Sequence[type] = (Exception,),
    give_up_on: Sequence[type] = (),
    logger: Optional[logging.Logger] = None,
    description: str = "",
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> T:
    """Call ``func`` with exponential backoff and jitter.

    Args:
        func: Callable to execute.
        attempts: Total number of attempts (must be >= 1).
        base_delay: Delay before the second attempt, doubled each retry.
        max_delay: Upper bound for a single delay.
        retry_on: Exception types that trigger another attempt.
        give_up_on: Exception types that abort immediately.

    Returns:
        Whatever ``func`` returns on the first successful attempt.

    Raises:
        The last exception raised by ``func`` when every attempt fails.
    """
    label = description or getattr(func, "__name__", "call")
    log = logger or get_logger("retry")
    attempts = max(1, attempts)
    
    # Ensure give_up_on always includes KeyboardInterrupt to allow graceful exit
    give_up_on = tuple(set(give_up_on) | {KeyboardInterrupt})

    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except give_up_on:
            raise
        except retry_on as exc:  # type: ignore[misc]
            if attempt == attempts:
                log.error("%s failed after %d attempt(s): %s", label, attempt, exc)
                raise
            
            # Exponential backoff with full jitter
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jittered_delay = random.uniform(0, delay)
            
            log.warning(
                "%s failed (attempt %d/%d): %s - retrying in %.1fs",
                label,
                attempt,
                attempts,
                exc,
                jittered_delay,
            )
            sleep(jittered_delay)

    # This part should be unreachable if attempts >= 1
    raise RuntimeError("Retry loop exhausted unexpectedly.")


# ─────────────────────────────────────────────
#  Validation helpers
# ─────────────────────────────────────────────
def validate_url(raw_url: str) -> str:
    """Validate an http(s) URL and return it normalised.

    Raises:
        InputError: when the value is empty, not a URL or not http(s).
    """
    candidate = (raw_url or "").strip()
    if not candidate:
        raise InputError(
            "Please provide a source URL.", hint="Paste a full https:// link."
        )
    if " " in candidate:
        raise InputError(
            f"'{candidate}' is not a valid URL.",
            hint="Remove the spaces and include the https:// prefix.",
        )
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InputError(
            f"'{candidate}' is not a valid URL.",
            hint="Only http:// and https:// sources are supported.",
        )
    host = parsed.hostname or ""
    if "." not in host and host not in ("localhost", "127.0.0.1"):
        raise InputError(
            f"'{candidate}' does not look like a real address.",
            hint="Use a full URL such as https://example.com/article.",
        )
    return parsed.geturl()


def is_pdf_url(url: str) -> bool:
    """True when the URL most likely points at a PDF document."""
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or "/pdf/" in path


def looks_like_pdf(data: bytes) -> bool:
    """True when the payload starts with the PDF magic number."""
    return data[:5] == b"%PDF-"


# ─────────────────────────────────────────────
#  Text helpers
# ─────────────────────────────────────────────
_WHITESPACE_RE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def clean_text(text: str) -> str:
    """Collapse noisy whitespace while preserving paragraph breaks."""
    if not text:
        return ""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    normalised = _WHITESPACE_RE.sub(" ", normalised)
    normalised = _BLANK_LINES_RE.sub("\n\n", normalised)
    return normalised.strip()


def truncate_text(text: str, max_chars: int, suffix: str = " ...") -> str:
    """Truncate text on a word boundary, appending ``suffix`` when cut."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    clipped = text[: max_chars - len(suffix)]
    if " " in clipped:
        clipped = clipped[: clipped.rfind(" ")]
    return clipped.rstrip() + suffix


def truncate_words(text: str, max_words: int) -> str:
    """Truncate text after ``max_words`` words (0 disables truncation)."""
    if max_words <= 0:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip() + " ..."


def estimate_speech_seconds(text: str, wpm: int = config.WORDS_PER_MINUTE) -> int:
    """Estimate narration duration in seconds from a word count."""
    words = len(text.split())
    if not words:
        return 0
    return max(1, int(round(words / max(1, wpm) * 60)))


def chunk_text(text: str, max_chars: int = config.TTS_CHUNK_CHARS) -> List[str]:
    """Split text into chunks of at most ``max_chars``, preferring sentences."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > max_chars:
            head, sentence = sentence[:max_chars], sentence[max_chars:]
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(head.strip())
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current.strip())
            current = sentence
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def slugify(text: str, max_length: int = 60) -> str:
    """Convert arbitrary text into a lowercase, filesystem-safe slug."""
    if not text:
        return ""
    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP_RE.sub("-", ascii_text).strip("-")
    return slug[:max_length].strip("-")


def sanitize_filename(name: str, fallback: str = "episode", extension: str = "") -> str:
    """Return a safe filename, forcing ``extension`` when one is supplied."""
    stem, suffix = os.path.splitext(os.path.basename(name or ""))
    safe_stem = slugify(stem) or slugify(fallback) or "episode"
    if extension:
        return f"{safe_stem}.{slugify(extension)}"
    suffix = slugify(suffix.lstrip("."))
    return f"{safe_stem}.{suffix}" if suffix else safe_stem


def format_bytes(size: int) -> str:
    """Human readable byte size, e.g. ``1.4 MB``."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"  # pragma: no cover - unreachable


def coerce_str_list(value: Any, limit: int = 0) -> List[str]:
    """Normalise an arbitrary value into a clean list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in re.split(r"[,\n;]", value)]
    elif isinstance(value, (list, tuple, set)):
        items = [str(part).strip() for part in value]
    else:
        items = [str(value).strip()]
    cleaned = [item for item in items if item]
    return cleaned[:limit] if limit else cleaned


# ─────────────────────────────────────────────
#  JSON parsing (LLM output)
# ─────────────────────────────────────────────
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_json_object(raw: str) -> Dict[str, Any]:
    """Extract a JSON object from raw LLM output.

    Handles markdown fences, leading prose and trailing commentary by scanning
    for the first balanced ``{...}`` block.

    Returns:
        The parsed mapping, or an empty dict when nothing parseable is found.
    """
    if not raw:
        return {}
    text = raw.strip()

    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    return parsed if isinstance(parsed, dict) else {}
        start = text.find("{", start + 1)
    return {}


def to_json(data: Dict[str, Any], indent: int = 2) -> str:
    """Serialise a mapping to pretty JSON, tolerating non-serialisable values."""
    return json.dumps(data, indent=indent, ensure_ascii=False, default=str)


def read_json_file(
    path: Any, default: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Read a JSON file, returning ``default`` when missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else (default or {})
    except (OSError, json.JSONDecodeError):
        return default or {}


def write_json_file(path: Any, data: Dict[str, Any]) -> None:
    """Write a mapping to JSON, creating parent directories as needed."""
    target = os.fspath(path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, default=str)
