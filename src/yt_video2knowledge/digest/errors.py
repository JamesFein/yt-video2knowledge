"""Error types shared by digest modules."""
from __future__ import annotations

from typing import Any

class DigestError(RuntimeError):
    """Base error for digest workflow."""


class MissingDependencyError(DigestError):
    """Raised when an external dependency is unavailable."""


class ConfigurationError(DigestError):
    """Raised when runtime configuration is incomplete."""

class ExternalCommandError(DigestError):
    """Raised when an external command fails."""


class BrowserConnectionError(DigestError):
    """Raised when the current Chrome CDP endpoint cannot be used."""


class ModelResponseError(DigestError):
    """Raised when a model response cannot safely be used."""

    failure_kind = "model_response_error"

    def __init__(
        self,
        message: str,
        *,
        response_id: str | None = None,
        provider: str | None = None,
        provider_status: str | None = None,
        stop_reason: str | None = None,
        output_chars: int = 0,
        validation_errors: list[str] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.response_id = response_id
        self.provider = provider
        self.provider_status = provider_status
        self.stop_reason = stop_reason
        self.output_chars = output_chars
        self.validation_errors = list(validation_errors or [])
        self.usage = dict(usage or {})


class TransportModelResponseError(ModelResponseError):
    """Raised when the HTTP or JSON response is incomplete."""

    failure_kind = "transport_error"


class IncompleteModelResponseError(ModelResponseError):
    """Raised when the provider or completion marker reports truncation."""

    failure_kind = "incomplete_response"


class InvalidSummaryArticleError(ModelResponseError):
    """Raised when generated Markdown fails minimum structural checks."""

    failure_kind = "invalid_structure"


class PolicyModelResponseError(ModelResponseError):
    """Raised when the provider refuses the request for policy reasons."""

    failure_kind = "policy_rejection"


class ProviderModelResponseError(ModelResponseError):
    """Raised when the provider reports a non-policy request failure."""

    failure_kind = "provider_error"
