"""KnowGate CLI — engineer query + admin ops client for the KnowGate RAG platform.

Sub-commands are registered in :mod:`knowgate_cli.main`. The package is
import-safe; only invoking the entry point touches keyring / network.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
