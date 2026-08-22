"""
Issue a signup invite from the shell.

The admin can do this too, but a command is the path that works before there's
a browser session, over SSH, or in a deploy script — and since SMTP is
optional, printing a link the operator sends by hand is the normal way people
get accounts on this instance.
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.accounts.services import invites


class Command(BaseCommand):
    help = "Create a registration invite and print its signup URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default="",
            help="Bind the invite to this address so only they can redeem it.",
        )
        parser.add_argument("--note", default="", help="Reminder of who this is for.")
        parser.add_argument(
            "--expires-days",
            type=int,
            default=None,
            help="Override INVITE_EXPIRY_DAYS. 0 means never expires.",
        )
        parser.add_argument(
            "--created-by",
            default=None,
            help="Email of the staff user to attribute this to.",
        )

    def handle(self, *args, **options):
        created_by = None
        if options["created_by"]:
            created_by = User.objects.filter(email__iexact=options["created_by"]).first()
            if created_by is None:
                self.stderr.write(self.style.ERROR(f"No user {options['created_by']}"))
                return

        invite = invites.create_invite(
            created_by=created_by,
            email=options["email"],
            note=options["note"],
            expires_days=options["expires_days"],
        )

        self.stdout.write(self.style.SUCCESS("Invite created."))
        if invite.email:
            self.stdout.write(f"  For:     {invite.email}")
        self.stdout.write(f"  Expires: {invite.expires_at or 'never'}")
        self.stdout.write(f"  Link:    {invite.signup_url}")
