"""Data provider clients (external market/macro data APIs)."""

from project_titan_x.core.data_providers.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageError,
    AlphaVantageNotConfigured,
    AlphaVantageQuotaExceeded,
    get_alpha_vantage_client,
)
from project_titan_x.core.data_providers.alternative_me import (
    AlternativeMeClient,
    AlternativeMeError,
    get_alternative_me_client,
)
from project_titan_x.core.data_providers.cftc import (
    CFTCClient,
    CFTCError,
    SYMBOL_TO_CFTC_MARKET,
    get_cftc_client,
)
from project_titan_x.core.data_providers.deribit import (
    DeribitClient,
    DeribitError,
    get_deribit_client,
)
from project_titan_x.core.data_providers.kite_option_chain import (
    KiteConnectClient,
    KiteConnectError,
    KiteNotConfigured,
    get_kite_client,
)

__all__ = [
    "AlphaVantageClient",
    "AlphaVantageError",
    "AlphaVantageNotConfigured",
    "AlphaVantageQuotaExceeded",
    "get_alpha_vantage_client",
    "AlternativeMeClient",
    "AlternativeMeError",
    "get_alternative_me_client",
    "CFTCClient",
    "CFTCError",
    "SYMBOL_TO_CFTC_MARKET",
    "get_cftc_client",
    "DeribitClient",
    "DeribitError",
    "get_deribit_client",
    "KiteConnectClient",
    "KiteConnectError",
    "KiteNotConfigured",
    "get_kite_client",
]
