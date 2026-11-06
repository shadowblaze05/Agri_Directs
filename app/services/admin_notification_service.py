import smtplib

from flask import current_app
from flask_mail import Message

from ..extensions import mail


def send_notification_email(recipients, subject, body):
    """Send a non-critical account notification without interrupting its workflow."""
    recipients = list(dict.fromkeys(
        recipient.strip() for recipient in recipients
        if isinstance(recipient, str) and recipient.strip()
    ))
    if not recipients:
        current_app.logger.error(
            "Notification email was not sent: no recipient email is configured."
        )
        return False
    if current_app.config.get("MAIL_SUPPRESS_SEND", True):
        current_app.logger.error(
            "Notification email was not sent because email delivery is suppressed."
        )
        return False

    sender = (
        current_app.config.get("MAIL_DEFAULT_SENDER")
        or current_app.config.get("AGRI_DIRECT_OFFICIAL_EMAIL")
    )
    message = Message(
        subject=subject,
        recipients=recipients,
        body=body,
        sender=sender,
    )
    try:
        mail.send(message)
    except (smtplib.SMTPException, OSError) as error:
        current_app.logger.error(
            "Notification email delivery failed (%s).",
            type(error).__name__,
        )
        return False
    return True


def notify_superadmin(subject, body):
    """Send administrator reports only to the configured official address."""
    official_email = str(
        current_app.config.get("AGRI_DIRECT_OFFICIAL_EMAIL") or ""
    ).strip()
    if not official_email:
        current_app.logger.error(
            "Super-admin notification was not sent: no official email is configured."
        )
        return False
    return send_notification_email([official_email], subject, body)
