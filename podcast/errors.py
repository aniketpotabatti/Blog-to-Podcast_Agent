"""
Typed error taxonomy with actionable user messages.
==================================================

Every failure in the pipeline is normalised into a :class:`PodcastError` so the
UI can show a short ``message`` plus a concrete ``hint`` instead of a raw
traceback. :func:`classify_exception` maps third-party SDK errors onto the
right subclass.
"""

from __future__ import annotations

from typing import Optional


class PodcastError(Exception):
    """Base class for all pipeline errors."""

    stage: str = "pipeline"

    def __init__(self, message: str, hint: str = "", stage: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        if stage:
            self.stage = stage

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ConfigurationError(PodcastError):
    """Missing or malformed configuration (e.g. API keys)."""

    stage = "configuration"


class InputError(PodcastError):
    """The supplied source (URL, PDF, feed) is invalid or unusable."""

    stage = "input"


class IngestionError(PodcastError):
    """Content could not be fetched or extracted."""

    stage = "ingestion"


class PaywallError(IngestionError):
    """The page is behind a login, paywall or anti-bot challenge."""

    stage = "ingestion"


class ScriptGenerationError(PodcastError):
    """The LLM failed to produce a usable podcast script."""

    stage = "script"


class SpeechSynthesisError(PodcastError):
    """Text-to-speech synthesis failed."""

    stage = "speech"


class AuthenticationError(SpeechSynthesisError):
    """Provider rejected the API key or the key lacks permissions."""

    stage = "speech"


class RateLimitError(PodcastError):
    """Provider rate limit or quota exceeded."""

    stage = "provider"


class QuotaError(RateLimitError):
    """Account credit/quota exhausted."""

    stage = "provider"


class AudioProcessingError(PodcastError):
    """Audio decoding, mixing or encoding failed."""

    stage = "audio"


class PublishingError(PodcastError):
    """An episode could not be published to the requested destination."""

    stage = "publishing"


_AUTH_MARKERS = (
    "401",
    "403",
    "invalid_api_key",
    "invalid api key",
    "unauthorized",
    "missing_permissions",
    "permission",
    "authentication",
)
_RATE_MARKERS = ("429", "rate limit", "too many requests", "slow down")
_QUOTA_MARKERS = ("quota", "insufficient_credits", "credit", "exceeded your current")
_PAYWALL_MARKERS = (
    "paywall",
    "login required",
    "403 forbidden",
    "captcha",
    "not authorized",
)


def _matches(text: str, markers: tuple) -> bool:
    """Case-insensitive substring check against a marker tuple."""
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def classify_exception(exc: BaseException, stage: str = "pipeline") -> PodcastError:
    """Map any exception raised by a dependency onto a :class:`PodcastError`.

    Args:
        exc: The original exception.
        stage: Pipeline stage in which the failure occurred.

    Returns:
        A typed :class:`PodcastError` ready to be surfaced in the UI.
    """
    if isinstance(exc, PodcastError):
        return exc

    message = str(exc) or exc.__class__.__name__

    # During ingestion a 403 usually means anti-bot/paywall rather than a bad
    # credential, so that check has to come first.
    if stage == "ingestion" and _matches(message, _PAYWALL_MARKERS):
        return PaywallError(
            f"Content could not be accessed ({message}).",
            hint="Try a publicly accessible source without a login or paywall.",
        )
    if _matches(message, _AUTH_MARKERS):
        return AuthenticationError(
            f"Provider rejected the credential ({message}).",
            hint=(
                "Re-check the API key and make sure it has the required "
                "permissions enabled in the provider dashboard."
            ),
            stage=stage,
        )
    if _matches(message, _QUOTA_MARKERS):
        return QuotaError(
            f"Provider quota exhausted ({message}).",
            hint="Top up your account credits or wait for the quota to reset.",
            stage=stage,
        )
    if _matches(message, _RATE_MARKERS):
        return RateLimitError(
            f"Provider rate limit reached ({message}).",
            hint="Wait a few seconds and retry, or lower the request frequency.",
            stage=stage,
        )

    defaults = {
        "configuration": ConfigurationError,
        "input": InputError,
        "ingestion": IngestionError,
        "script": ScriptGenerationError,
        "speech": SpeechSynthesisError,
        "audio": AudioProcessingError,
        "publishing": PublishingError,
    }
    error_cls = defaults.get(stage, PodcastError)
    return error_cls(message, stage=stage)