"""Check the mail server settings used by the Send mail button.

    python manage.py check_mail                   shows the settings and tests the login
    python manage.py check_mail --to me@x.com     also sends one test mail to that address
"""
import smtplib

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError


def hint(exc):
    """A plain explanation for the usual SMTP problems."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return ("The server refused the user name or password. Gmail and Microsoft 365 need an app password "
                "(not the normal sign-in password), and the account needs two-step verification or SMTP sending turned on.")
    if isinstance(exc, (smtplib.SMTPConnectError, ConnectionRefusedError, TimeoutError, OSError)):
        return ("Could not reach the server. Check EMAIL_HOST and EMAIL_PORT, the internet connection, and that a firewall "
                "is not blocking the port (587 for STARTTLS, 465 for SSL).")
    if isinstance(exc, smtplib.SMTPException):
        return "The server rejected the request. For port 465 set EMAIL_USE_SSL=True and EMAIL_USE_TLS=False; for port 587 the reverse."
    return ""


class Command(BaseCommand):
    help = "Show the mail settings, test the login to the mail server and optionally send a test mail."

    def add_arguments(self, parser):
        parser.add_argument("--to", default="", help="Send one test mail to this address.")

    def handle(self, *args, **opts):
        out = self.stdout.write
        if not settings.EMAIL_HOST:
            out("Test mode: EMAIL_HOST is empty, so mails are only printed in the server window and nothing is delivered.")
            out("Set EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD and DEFAULT_FROM_EMAIL in .env, then run this again.")
            return
        security = "SSL" if settings.EMAIL_USE_SSL else ("STARTTLS" if settings.EMAIL_USE_TLS else "none (not recommended)")
        out(f"Server:   {settings.EMAIL_HOST}:{settings.EMAIL_PORT}  ({security})")
        out(f"Login:    {settings.EMAIL_HOST_USER or '(none)'}   password: {'set' if settings.EMAIL_HOST_PASSWORD else 'NOT SET'}")
        out(f"From:     {settings.DEFAULT_FROM_EMAIL}")
        out(f"Hidden copy (OUTREACH_BCC): {settings.OUTREACH_BCC or '(none)'}")
        out(f"Safe test (OUTREACH_TEST_RECIPIENT): {settings.OUTREACH_TEST_RECIPIENT or '(off: real companies will be mailed)'}")
        out(f"Sending:  {'on' if settings.OUTREACH_ENABLED else 'OFF (OUTREACH_ENABLED=False)'}")
        connection = get_connection(fail_silently=False)
        try:
            connection.open()
        except Exception as exc:  # noqa: BLE001 - any failure is reported in plain words
            raise CommandError(f"Login failed: {exc}\n{hint(exc)}")
        out(self.style.SUCCESS("Login to the mail server worked."))
        target = (opts["to"] or "").strip()
        if target:
            try:
                EmailMessage("Test mail from Vessel Intelligence",
                             "This is a test mail. If you can read it, the mail settings are correct.\n",
                             settings.DEFAULT_FROM_EMAIL, [target], connection=connection).send()
            except Exception as exc:  # noqa: BLE001
                raise CommandError(f"The test mail could not be sent: {exc}\n{hint(exc)}")
            finally:
                connection.close()
            out(self.style.SUCCESS(f"Test mail sent to {target}. Check the inbox (and the spam folder)."))
        else:
            connection.close()
            out("Add --to your@address.com to send a test mail as well.")
