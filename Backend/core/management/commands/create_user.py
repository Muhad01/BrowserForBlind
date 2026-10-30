"""Management command to create a user account with prompted password (TBD-05)."""
import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Create a user account with prompted or specified password."

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Username to create")
        parser.add_argument(
            "--password",
            type=str,
            default=None,
            help="Password for user (if omitted, prompts interactively)",
        )

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]

        if User.objects.filter(username=username).exists():
            raise CommandError(f"User '{username}' already exists.")

        if not password:
            password = getpass.getpass("Enter password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match.")

        if not password:
            raise CommandError("Password cannot be blank.")

        user = User.objects.create_user(username=username, password=password)
        self.stdout.write(self.style.SUCCESS(f"User '{user.username}' created successfully (ID: {user.id})."))
