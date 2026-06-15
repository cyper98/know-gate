"""TOML-backed config store for the KnowGate CLI.

Config lives at ``~/.config/knowgate/config.toml`` (per XDG-ish convention;
we always use ``~/.config/knowgate/`` regardless of platform to keep
the behaviour predictable for engineers). Keys:

- ``api_url`` (default ``http://localhost:8000``) — base URL of the API
- ``default_language`` (default ``en``) — language for the ``kg query`` command
- ``output_format`` (default ``human``) — ``human`` or ``json``

Reads use stdlib :mod:`tomllib` (3.11+). Writes use :mod:`tomli_w` (the
stdlib has no writer in 3.12). A missing file is treated as an empty
config; a malformed file raises a friendly :class:`ConfigError` rather
than a stack trace.

This module never touches credentials — those live in :mod:`knowgate_cli.auth`
(keyring / system keychain).
"""

from __future__ import annotations

import contextlib
import os
import sys
import tomllib
from pathlib import Path

import tomli_w

# === Public defaults ===
# Single source of truth so the `kg config list` output stays consistent
# with `kg config get <unknown>` (returns the default rather than raising).

DEFAULTS: dict[str, str] = {
    "api_url": "http://localhost:8000",
    "default_language": "en",
    "output_format": "human",
}

# Keys the user is allowed to set. Anything else is rejected up-front so
# typos don't silently persist a config that nothing reads.
ALLOWED_KEYS: frozenset[str] = frozenset(DEFAULTS.keys())


class ConfigError(RuntimeError):
    """Raised on malformed config file or invalid key writes."""


# === Path resolution ===


def config_dir() -> Path:
    """Return the config directory, creating it on first access.

    Honours ``$KNOWGATE_CONFIG_DIR`` for tests and override scenarios,
    otherwise falls back to ``~/.config/knowgate``.
    """
    override = os.environ.get("KNOWGATE_CONFIG_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".config" / "knowgate"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    """Return the full path to the config TOML file."""
    return config_dir() / "config.toml"


# === Read / write ===


def load() -> dict[str, str]:
    """Read the config file and merge with defaults.

    Returns:
        Dict of key -> string value. Always contains every key in
        :data:`DEFAULTS` (uses the default when a key is missing).
    """
    path = config_path()
    merged: dict[str, str] = dict(DEFAULTS)
    if not path.exists():
        return merged
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Config file {path} is not valid TOML: {exc}. Fix or delete the file to continue."
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a TOML table at the top level.")
    for key, value in data.items():
        if key in ALLOWED_KEYS and isinstance(value, str):
            merged[key] = value
        elif key in ALLOWED_KEYS:
            # Coerce non-string values to string rather than silently dropping;
            # tells the user "I saw this key but the value is the wrong shape".
            merged[key] = str(value)
        # Unknown keys are silently ignored on read so users don't get
        # scared by warnings when we remove a legacy key in a later release.
    return merged


def get(key: str) -> str:
    """Read a single key (with default fallback)."""
    if key not in ALLOWED_KEYS:
        raise ConfigError(f"Unknown config key '{key}'. Allowed keys: {sorted(ALLOWED_KEYS)}")
    return load()[key]


def set_value(key: str, value: str) -> Path:
    """Persist ``key = value`` and return the config path.

    Atomic-ish: write to a temp file in the same directory, then rename.
    Avoids a half-written config if the process is killed mid-write.
    """
    if key not in ALLOWED_KEYS:
        raise ConfigError(f"Unknown config key '{key}'. Allowed keys: {sorted(ALLOWED_KEYS)}")
    current = load()
    current[key] = value
    path = config_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("wb") as fh:
            tomli_w.dump(current, fh)
        os.replace(tmp, path)
    except OSError as exc:
        # Clean up the temp file if rename failed
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise ConfigError(f"Could not write config to {path}: {exc}") from exc
    return path


def list_all() -> dict[str, str]:
    """Return the full config dict (defaults + persisted overrides)."""
    return load()


__all__ = [
    "ALLOWED_KEYS",
    "DEFAULTS",
    "ConfigError",
    "config_dir",
    "config_path",
    "get",
    "list_all",
    "load",
    "set_value",
]


# Convenience: re-bind sys.stdout for the few callers that prefer
# printing to a captured stream in tests. Keeping this internal because
# it's not part of the documented public API.
_internal_stdout = sys.stdout
