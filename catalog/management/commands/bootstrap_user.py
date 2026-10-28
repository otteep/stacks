"""Create the first user from environment variables, if no users exist yet.

Used by the Docker entrypoint so a fresh install can be signed into without a
separate ``createsuperuser`` step. It never changes an existing account.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the initial admin user from STACKS_ADMIN_USER / STACKS_ADMIN_PASSWORD if no users exist."

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.exists():
            return
        username = os.environ.get("STACKS_ADMIN_USER", "").strip()
        password = os.environ.get("STACKS_ADMIN_PASSWORD", "")
        if not username or not password:
            self.stdout.write(
                "No users exist yet. Set STACKS_ADMIN_USER and STACKS_ADMIN_PASSWORD, "
                "or run: docker compose exec stacks python manage.py createsuperuser"
            )
            return
        if len(password) < 8:
            self.stderr.write("STACKS_ADMIN_PASSWORD must be at least 8 characters; no user created.")
            return
        User.objects.create_superuser(username=username, password=password)
        self.stdout.write(f"Created initial user '{username}'.")
