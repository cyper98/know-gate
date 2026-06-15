"""Terminal output layer for the KnowGate CLI.

Wraps :mod:`rich` to give the rest of the CLI a stable, minimal surface:

- ``info`` / ``success`` / ``warning`` / ``error`` — coloured one-liners
- ``table`` — render a list of dicts as a Rich table (auto column sizing)
- ``panel`` — bordered block (used for the LLM answer body)
- ``json`` — pretty-print OR raw ``json.dumps`` depending on mode
- ``spinner`` — context manager for long-running operations
- ``prompt`` — typed prompt (email, password, text)

When ``json_mode=True`` (set via ``--json`` global flag or
``output_format=json`` in config), all human output is suppressed and
data is emitted as raw JSON to stdout. Errors in JSON mode go to stderr
as a single envelope ``{"error": {"code", "message"}}`` so downstream
``jq`` pipelines can still detect failure.

This module never raises on output errors. A broken terminal (no TTY,
missing color support) falls back to plain text — the user still gets
the message.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Iterator
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text


class Output:
    """Centralised terminal output with optional JSON mode.

    Args:
        json_mode: When True, suppress all human output and emit JSON.
        color: When False, force plain text (used in tests + non-TTY).
        stderr_console: Console bound to stderr (for errors + spinners
            that shouldn't pollute a piped stdout).
    """

    def __init__(
        self,
        *,
        json_mode: bool = False,
        color: bool | None = None,
    ) -> None:
        self.json_mode = json_mode
        # Default color to whether stdout looks like a TTY. In tests
        # (where stdout is captured) this becomes False automatically,
        # which in turn makes Rich treat the console as non-interactive
        # — so Output.confirm() returns the default instead of calling
        # console.input() and crashing on the pytest capture.
        if color is None:
            color = sys.stdout.isatty()
        self._console = Console(
            file=sys.stdout,
            no_color=not color,
            force_terminal=color,
            highlight=False,
        )
        self._err = Console(
            file=sys.stderr,
            no_color=not color,
            force_terminal=color,
            highlight=False,
        )

    # === Human-mode printers ===

    def info(self, message: str) -> None:
        if self.json_mode:
            return
        self._console.print(f"[cyan]i[/cyan] {message}")

    def success(self, message: str) -> None:
        if self.json_mode:
            return
        self._console.print(f"[green]✓[/green] {message}")

    def warning(self, message: str) -> None:
        if self.json_mode:
            return
        self._console.print(f"[yellow]![/yellow] {message}")

    def error(self, message: str, *, code: str | None = None) -> None:
        """Print a human-friendly error to stderr.

        In JSON mode the structured envelope is emitted so ``jq``/pipes
        can still detect failure (exit code is the caller's job).
        """
        if self.json_mode:
            envelope: dict[str, Any] = {"error": {"message": message}}
            if code:
                envelope["error"]["code"] = code
            self._err.print_json(data=envelope)
            return
        prefix = f"[red]✗[/red] [{code}] " if code else "[red]✗[/red] "
        self._err.print(prefix + message)

    def json(self, data: Any) -> None:
        """Print a JSON payload.

        JSON mode: raw ``json.dumps`` (no pretty-print) so it's
        pipe-friendly. Human mode: pretty-printed for readability.
        """
        if self.json_mode:
            self._console.print(json.dumps(data, default=str, ensure_ascii=False))
        else:
            self._console.print_json(data=data)

    def table(
        self,
        rows: list[dict[str, Any]],
        columns: list[tuple[str, str]] | None = None,
    ) -> None:
        """Render a list of dicts as a Rich table.

        Args:
            rows: One dict per row.
            columns: List of ``(key, header)`` pairs. If omitted, columns
                are derived from the keys of ``rows[0]`` (insertion order).
        """
        if self.json_mode:
            self.json(rows)
            return
        if not rows:
            self._console.print("[dim](no results)[/dim]")
            return
        if columns is None:
            columns = [(k, k.replace("_", " ").title()) for k in rows[0]]
        table = Table(show_header=True, header_style="bold", box=None)
        for _key, header in columns:
            table.add_column(header)
        for row in rows:
            table.add_row(*[str(row.get(k, "")) for k, _ in columns])
        self._console.print(table)

    def panel(self, body: str, *, title: str | None = None) -> None:
        """Render a bordered block (used for the LLM answer body)."""
        if self.json_mode:
            return
        self._console.print(Panel(Text(body, overflow="fold"), title=title, border_style="cyan"))

    @contextlib.contextmanager
    def spinner(self, message: str) -> Iterator[None]:
        """Context manager that prints a spinner while a block runs.

        No-op in JSON mode (the caller should print a JSON payload after
        the block exits, or the user is fine with silence).
        """
        if self.json_mode:
            yield
            return
        with self._err.status(message, spinner="dots"):
            yield

    # === Prompts ===

    def prompt_text(self, message: str, *, default: str | None = None) -> str:
        if not self._console.is_interactive:
            # Non-interactive: read a single line from stdin
            line = sys.stdin.readline().rstrip("\n")
            return line or (default or "")
        return self._console.input(f"[bold]?[/bold] {message} ") or (default or "")

    def prompt_email(self, message: str) -> str:
        """Prompt for an email (basic validation; full validation happens server-side)."""
        while True:
            value = self.prompt_text(message)
            if "@" in value and "." in value.split("@")[-1]:
                return value
            self.warning("That doesn't look like an email address. Try again.")

    def prompt_password(self, message: str = "Password") -> str:
        """Prompt for a password (hidden input).

        Falls back to :func:`getpass.getpass` if Rich's ``input`` doesn't
        support the ``password=True`` kwarg on the current version.
        """
        if not self._console.is_interactive:
            # Non-interactive: read a line from stdin (still hidden is impossible)
            return sys.stdin.readline().rstrip("\n")
        try:
            return self._console.input(
                f"[bold]?[/bold] {message}: ",
                password=True,
            )
        except TypeError:
            # Older Rich without password=True — fallback to getpass
            import getpass

            return getpass.getpass(f"{message}: ")

    def confirm(self, message: str, *, default: bool = False) -> bool:
        if not self._console.is_interactive:
            return default
        suffix = " [Y/n]" if default else " [y/N]"
        ans = self._console.input(f"[bold]?[/bold] {message}{suffix} ").strip().lower()
        if not ans:
            return default
        return ans in ("y", "yes")


__all__ = ["Output"]


# Re-export ``Spinner`` only to silence the unused-import linter when
# callers import from this module; the class isn't part of the public
# surface but the import keeps ``Spinner`` discoverable for IDEs.
_ = Spinner
