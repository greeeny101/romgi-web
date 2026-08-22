"""
Print a password-reset link for a user.

This is what makes running romgi without a mail server a supported setup rather
than a broken one: with no SMTP configured, POST /auth/password/reset
deliberately does nothing, and the operator recovers the account by running
this and passing the link to the user out of band.

The link is a bearer credential for the account — anyone holding it can set the
password. Send it over something private and don't leave it in shell history.
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.accounts.services import reset


class Command(BaseCommand):
    help = "Print a single-use password reset URL for a user (for out-of-band delivery)."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **options):
        user = User.objects.filter(email__iexact=options["email"], is_active=True).first()
        if user is None:
            self.stderr.write(self.style.ERROR(f"No active user {options['email']}"))
            return

        self.stdout.write(self.style.WARNING("Treat this link as a password — it grants access."))
        self.stdout.write(reset.build_reset_url(user))
