"""
Management command: setup_roles
================================
Idempotently creates the two application roles (Django Groups) used by the
role-based permission layer.  Safe to re-run — existing groups are left
unchanged; only missing ones are created.

Usage::

    python manage.py setup_roles
"""
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the Admin and BD Manager Django Groups if they do not already exist."

    def handle(self, *args, **options):
        role_names = [settings.ROLE_ADMIN, settings.ROLE_BD_MANAGER]

        for name in role_names:
            group, created = Group.objects.get_or_create(name=name)
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created group: {name}"))
            else:
                self.stdout.write(f"Group already exists: {name}")

        self.stdout.write(self.style.SUCCESS("setup_roles complete."))
