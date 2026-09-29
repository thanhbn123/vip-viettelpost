"""Provider-neutral errors. Adapters raise subclasses; the application maps them to HTTP.

Messages must never contain credentials. Adapters are responsible for redaction.
"""


class ProviderError(Exception):
    """Base class for anything a provider adapter raises on purpose."""


class ProviderRequestError(ProviderError, ValueError):
    """The core request cannot be expressed for this provider (caller error, not retryable)."""


class ProviderTimeoutError(ProviderError):
    """No answer within the timeout. The outcome at the provider is UNKNOWN."""


class ProviderUnavailableError(ProviderError):
    """Network failure or provider-side (5xx) error. Retryable."""


class ProviderRejectedError(ProviderError):
    """The provider answered and refused the request (business rule / validation)."""


class ProviderAuthError(ProviderRejectedError):
    """Credentials or token rejected by the provider."""


class ProviderResponseError(ProviderError):
    """The provider answered with a body that does not match its documented contract."""
