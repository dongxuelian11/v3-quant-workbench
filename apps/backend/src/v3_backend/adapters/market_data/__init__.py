"""Optional market-data provider adapters."""

from .akshare import (
    AKSHARE_PROVIDER_REPOSITORY_REVISION,
    AKSHARE_PROVIDER_VERSION,
    AkshareAShareEodAdapter,
    ProviderAcquisitionError,
    ProviderDependencyUnavailable,
    ProviderVersionMismatch,
)

__all__ = [
    "AKSHARE_PROVIDER_REPOSITORY_REVISION",
    "AKSHARE_PROVIDER_VERSION",
    "AkshareAShareEodAdapter",
    "ProviderAcquisitionError",
    "ProviderDependencyUnavailable",
    "ProviderVersionMismatch",
]
