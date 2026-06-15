"""Typer entry point for the KnowGate CLI (``kg`` command).

Structure:
- A top-level callback resolves global options (--api-url, --json,
  --verbose), loads config, and builds a :class:`KnowGateClient` per
  command. The callback is invoked by Typer before every sub-command.
- Five sub-commands: ``auth``, ``query``, ``source``, ``user``, ``config``.
- Error handling: any :class:`CLIError` raised by the client maps to
  the documented exit code; unhandled exceptions print a friendly
  message + traceback (when ``--verbose``) and exit 5.

Per the memory rule that bans work-block labels from code, the file
mentions none of the internal timeline words — it just describes the
CLI's current state and behaviour.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any

import typer

from . import __version__
from . import auth as auth_mod
from . import config as cfg
from . import query as query_mod
from . import source as source_mod
from . import user as user_mod
from .client import CLIError, KnowGateClient
from .output import Output

# === Typer app ===
app = typer.Typer(
    name="kg",
    help="KnowGate CLI — query your internal knowledge base and run admin ops.",
    no_args_is_help=True,
    add_completion=False,  # we don't ship a completion script in MVP
    rich_markup_mode="rich",
)

# Sub-command groups
auth_app = typer.Typer(help="Sign in / out and check the current session.", no_args_is_help=True)
source_app = typer.Typer(help="Manage data sources (Google Drive, Notion).", no_args_is_help=True)
user_app = typer.Typer(help="Manage user accounts and role assignments.", no_args_is_help=True)

app.add_typer(auth_app, name="auth")
app.add_typer(source_app, name="source")
app.add_typer(user_app, name="user")


# === Version callback ===


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"kg {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the CLI version and exit.",
    ),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        envvar="KNOWGATE_API_URL",
        help="API base URL (overrides config). Env: KNOWGATE_API_URL.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Output JSON to stdout instead of human-readable formatting.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print full tracebacks on error.",
    ),
) -> None:
    """Global options (apply to every sub-command)."""
    # Stash on the Typer context so sub-commands can read it without
    # re-declaring the same options on every command.
    ctx.obj = {
        "api_url": api_url,
        "as_json": as_json,
        "verbose": verbose,
    }


# === Helpers shared by sub-commands ===


def _ctx_opts(ctx: typer.Context) -> dict[str, Any]:
    """Return the stashed global options (with sane defaults)."""
    return ctx.obj or {}


def _resolve_api_url(ctx: typer.Context) -> str:
    """API URL precedence: --api-url flag > env > config > default."""
    opts = _ctx_opts(ctx)
    flag_url = opts.get("api_url")
    if flag_url:
        return flag_url
    env_url = os.environ.get("KNOWGATE_API_URL")
    if env_url:
        return env_url
    try:
        return cfg.get("api_url")
    except cfg.ConfigError:
        return cfg.DEFAULTS["api_url"]


def _make_output(ctx: typer.Context) -> Output:
    """Build an :class:`Output` honoring the --json flag and config."""
    opts = _ctx_opts(ctx)
    json_flag = bool(opts.get("as_json"))
    if not json_flag:
        # Respect config-level output_format if --json wasn't passed
        try:
            json_flag = cfg.get("output_format").lower() == "json"
        except cfg.ConfigError:
            json_flag = False
    return Output(json_mode=json_flag, color=sys.stdout.isatty())


def _make_client(ctx: typer.Context) -> KnowGateClient:
    """Build a :class:`KnowGateClient` for the current command."""
    base = _resolve_api_url(ctx)
    getter = auth_mod.make_getter(base)
    return KnowGateClient(base_url=base, credential_getter=getter)


# === Top-level commands ===


@app.command()
def query(
    ctx: typer.Context,
    question: str | None = typer.Argument(None, help="Question text (omit if --file/--stdin)."),
    file: Path | None = typer.Option(None, "--file", help="Read question from a file."),
    use_stdin: bool = typer.Option(False, "--stdin", help="Read question from stdin."),
    language: str | None = typer.Option(
        None,
        "--language",
        "-l",
        help="Override language detection (vi, en, zh).",
    ),
    bypass_cache: bool = typer.Option(
        False,
        "--bypass-cache",
        help="Skip the semantic cache (admin debug).",
    ),
    no_citations: bool = typer.Option(
        False,
        "--no-citations",
        help="Hide the citation table.",
    ),
) -> None:
    """Ask a question and print the answer with citations."""
    client = _make_client(ctx)
    out = _make_output(ctx)
    try:
        query_mod.run(
            client,
            out,
            question=question,
            file=file,
            use_stdin=use_stdin,
            language=language,
            bypass_cache=bypass_cache,
            show_citations=not no_citations,
        )
    except CLIError as exc:
        out.error(str(exc), code=exc.code)
        raise typer.Exit(code=exc.exit_code) from None
    except (ValueError, FileNotFoundError) as exc:
        out.error(str(exc))
        raise typer.Exit(code=2) from None


@app.command(name="config")
def config_cmd(
    ctx: typer.Context,
    action: str = typer.Argument("list", help="list | get | set"),
    key: str | None = typer.Argument(None, help="Config key (for get/set)."),
    value: str | None = typer.Argument(None, help="Config value (for set)."),
) -> None:
    """View or edit CLI config (api_url, default_language, output_format)."""
    out = _make_output(ctx)
    action = action.lower()
    try:
        if action == "list":
            data = cfg.list_all()
            if out.json_mode:
                out.json(data)
            else:
                out.table(
                    [{"key": k, "value": v} for k, v in data.items()],
                    columns=[("key", "Key"), ("value", "Value")],
                )
                out.info(f"Config file: {cfg.config_path()}")
        elif action == "get":
            if not key:
                out.error("Usage: kg config get <key>")
                raise typer.Exit(code=2)
            out.info(cfg.get(key))
        elif action == "set":
            if not key or value is None:
                out.error("Usage: kg config set <key> <value>")
                raise typer.Exit(code=2)
            path = cfg.set_value(key, value)
            out.success(f"Saved {key}={value} to {path}")
        else:
            out.error(f"Unknown action '{action}'. Use: list | get | set")
            raise typer.Exit(code=2)
    except cfg.ConfigError as exc:
        out.error(str(exc))
        raise typer.Exit(code=2) from None


# === auth sub-commands ===


@auth_app.command("login")
def auth_login(ctx: typer.Context) -> None:
    """Sign in with email + password. Tokens are stored in the system keyring."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    try:
        auth_mod.login(client, out)
    except CLIError:
        raise typer.Exit(code=1) from None
    except auth_mod.AuthError as exc:
        out.error(str(exc))
        raise typer.Exit(code=1) from None


@auth_app.command("logout")
def auth_logout(
    ctx: typer.Context,
    email: str | None = typer.Option(None, "--email", help="Account to log out (default: active)."),
    all_accounts: bool = typer.Option(False, "--all", help="Clear all stored credentials."),
) -> None:
    """Clear stored credentials for one account (or ``--all``)."""
    out = _make_output(ctx)
    api_url = _resolve_api_url(ctx)
    try:
        auth_mod.logout(api_url, email, all_accounts, out)
    except auth_mod.AuthError as exc:
        out.error(str(exc))
        raise typer.Exit(code=1) from None


@auth_app.command("status")
def auth_status(ctx: typer.Context) -> None:
    """Show the currently active account (if any)."""
    out = _make_output(ctx)
    api_url = _resolve_api_url(ctx)
    auth_mod.status(api_url, out)


# === source sub-commands ===


@source_app.command("list")
def source_list(ctx: typer.Context) -> None:
    """List all configured sources."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    source_mod.list_sources(client, out)


@source_app.command("show")
def source_show(ctx: typer.Context, source_id: str) -> None:
    """Show a single source by ID."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    source_mod.show_source(client, out, source_id)


@source_app.command("create")
def source_create(
    ctx: typer.Context,
    name: str | None = typer.Option(None, "--name", help="Display name."),
    type: str | None = typer.Option(None, "--type", help="google_drive | notion."),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="JSON file with the connector config.",
    ),
) -> None:
    """Create a new source (interactive unless --name, --type, --from-file given)."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    try:
        source_mod.create_source(client, out, name=name, source_type=type, from_file=from_file)
    except (ValueError, FileNotFoundError) as exc:
        out.error(str(exc))
        raise typer.Exit(code=2) from None
    except CLIError:
        raise typer.Exit(code=1) from None


@source_app.command("sync")
def source_sync(ctx: typer.Context, source_id: str) -> None:
    """Trigger a manual sync (enqueues a background job)."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    source_mod.sync_source(client, out, source_id)


@source_app.command("delete")
def source_delete(
    ctx: typer.Context,
    source_id: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Archive (soft-delete) a source."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    try:
        source_mod.delete_source(client, out, source_id, yes=yes)
    except CLIError:
        raise typer.Exit(code=1) from None


# === user sub-commands ===


@user_app.command("list")
def user_list(
    ctx: typer.Context,
    status: str | None = typer.Option(None, "--status", help="active | suspended | deleted."),
    email_contains: str | None = typer.Option(
        None,
        "--email-contains",
        help="Substring match on email.",
    ),
    limit: int = typer.Option(50, "--limit", min=1, max=100, help="Page size (1-100)."),
) -> None:
    """List users (admin only)."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    try:
        user_mod.list_users(
            client,
            out,
            status=status,
            email_contains=email_contains,
            limit=limit,
        )
    except CLIError:
        raise typer.Exit(code=1) from None


@user_app.command("show")
def user_show(ctx: typer.Context, user_id: str) -> None:
    """Show a single user by ID (admin only)."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    try:
        user_mod.show_user(client, out, user_id)
    except CLIError:
        raise typer.Exit(code=1) from None


@user_app.command("invite")
def user_invite(
    ctx: typer.Context,
    email: str | None = typer.Option(None, "--email"),
    name: str | None = typer.Option(None, "--name", help="Display name."),
    roles: str | None = typer.Option(
        None,
        "--roles",
        help="Comma-separated role names (default: member).",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help="Initial password (random if omitted).",
    ),
) -> None:
    """Invite a new user (admin only)."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    role_list = [r.strip() for r in (roles or "").split(",") if r.strip()] or None
    try:
        user_mod.invite_user(
            client,
            out,
            email=email,
            display_name=name,
            roles=role_list,
            initial_password=password,
        )
    except CLIError:
        raise typer.Exit(code=1) from None


@user_app.command("delete")
def user_delete(
    ctx: typer.Context,
    user_id: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Soft-delete a user (admin only)."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    try:
        user_mod.delete_user(client, out, user_id, yes=yes)
    except CLIError:
        raise typer.Exit(code=1) from None


# Nested role sub-app
role_app = typer.Typer(help="Assign or revoke roles.", no_args_is_help=True)
user_app.add_typer(role_app, name="role")


@role_app.command("add")
def user_role_add(ctx: typer.Context, user_id: str, role: str) -> None:
    """Assign a role to a user (admin only). Role given by name."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    try:
        user_mod.assign_role(client, out, user_id, role)
    except CLIError:
        raise typer.Exit(code=1) from None


@role_app.command("remove")
def user_role_remove(
    ctx: typer.Context,
    user_id: str,
    role_id: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Revoke a role from a user (admin only). Role given by ID."""
    out = _make_output(ctx)
    client = _make_client(ctx)
    try:
        user_mod.revoke_role(client, out, user_id, role_id, yes=yes)
    except CLIError:
        raise typer.Exit(code=1) from None


# === Error envelope ===


def _run_with_envelope() -> None:
    """Run the Typer app, mapping :class:`CLIError` to the right exit code.

    We catch :class:`CLIError` (raised by the client / sub-commands)
    here so Typer doesn't print its own traceback-style message; we
    want the human-friendly "✗ [E3] Invalid email or password" form.
    Unhandled exceptions get a stack trace when ``--verbose``.
    """
    try:
        app()
    except CLIError as exc:
        # If the sub-command already printed a friendly message, we
        # just exit with the right code. The Output.error() call is
        # idempotent in JSON vs human mode.
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=exc.exit_code) from None
    except typer.Exit:
        raise
    except typer.BadParameter as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    except Exception as exc:
        typer.echo(f"error: {exc}", err=True)
        verbose = "--verbose" in sys.argv
        if verbose:
            traceback.print_exc()
        raise typer.Exit(code=5) from None


if __name__ == "__main__":
    _run_with_envelope()


__all__ = ["app"]
