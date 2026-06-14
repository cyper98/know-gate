"""Source connectors (Google Drive, Notion, future: Slack, Confluence, etc.).

Each connector implements `BaseSourceConnector` and is instantiated by the
sync engine from a `Source` row. The connector handles the provider-specific
OAuth + API calls; the engine handles persistence + lifecycle.
"""

from app.sources.base import (
    BaseSourceConnector,
    ConnectorAuthError,
    ConnectorError,
    ConnectorRateLimitError,
    SourceDoc,
)

__all__ = [
    "BaseSourceConnector",
    "ConnectorAuthError",
    "ConnectorError",
    "ConnectorRateLimitError",
    "SourceDoc",
]
