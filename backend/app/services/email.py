"""SMTP email sender (aiosmtplib). Used for magic-link emails + invites + password resets."""

from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_email(
    *,
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> bool:
    """Send an email. Returns True on success, False on SMTP failure.

    Failures are logged to stderr but never raise (callers should treat
    email as best-effort for magic-link flow — but for transactional
    flows like password reset, callers may want to fail loud).
    """
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password.get_secret_value() or None,
            use_tls=settings.smtp_tls,
        )
        logger.info("email_sent", to=to, subject=subject)
        return True
    except Exception:
        logger.exception("email_send_failed", to=to, subject=subject)
        return False


# === Templated emails (HTML + text) ===

async def send_magic_link_email(*, to: str, link: str, expires_minutes: int = 15) -> bool:
    """Send a magic-link sign-in email.

    Args:
        to: recipient email
        link: full URL with the magic-link token
        expires_minutes: TTL shown in the email body
    """
    subject = "Your KnowGate sign-in link"
    body_text = (
        f"Sign in to KnowGate by clicking the link below (valid for {expires_minutes} minutes):\n\n"
        f"{link}\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    body_html = f"""
    <html>
      <body style="font-family: sans-serif; line-height: 1.5;">
        <h2>Sign in to KnowGate</h2>
        <p>Click the link below to sign in. The link is valid for {expires_minutes} minutes.</p>
        <p><a href="{link}" style="background: #2563eb; color: white; padding: 10px 16px; border-radius: 4px; text-decoration: none;">Sign in to KnowGate</a></p>
        <p style="color: #6b7280; font-size: 12px;">If you did not request this, you can safely ignore this email.</p>
      </body>
    </html>
    """
    return await send_email(to=to, subject=subject, body_text=body_text, body_html=body_html)


async def send_invite_email(*, to: str, invite_link: str, invited_by: str) -> bool:
    """Send a user-invitation email."""
    subject = f"{invited_by} invited you to KnowGate"
    body_text = (
        f"{invited_by} has invited you to join KnowGate.\n\n"
        f"Click the link below to accept the invite and set up your account:\n\n"
        f"{invite_link}\n\n"
        "The link is valid for 7 days."
    )
    body_html = f"""
    <html>
      <body style="font-family: sans-serif; line-height: 1.5;">
        <h2>You're invited to KnowGate</h2>
        <p><strong>{invited_by}</strong> has invited you to join KnowGate.</p>
        <p><a href="{invite_link}" style="background: #2563eb; color: white; padding: 10px 16px; border-radius: 4px; text-decoration: none;">Accept invite</a></p>
        <p style="color: #6b7280; font-size: 12px;">The link is valid for 7 days.</p>
      </body>
    </html>
    """
    return await send_email(to=to, subject=subject, body_text=body_text, body_html=body_html)
