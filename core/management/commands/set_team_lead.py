"""Give or take away team-lead access:  python manage.py set_team_lead <username> [--remove]"""
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError

from core.roles import TEAM_LEAD_GROUP


class Command(BaseCommand):
    help = "Add a user to (or remove from) the Team Lead group."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--remove", action="store_true")

    def handle(self, username, remove, **opts):
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"No user named '{username}'.")
        group, _ = Group.objects.get_or_create(name=TEAM_LEAD_GROUP)
        if remove:
            user.groups.remove(group)
            self.stdout.write(self.style.SUCCESS(f"{username} is no longer a team lead."))
        else:
            user.groups.add(group)
            self.stdout.write(self.style.SUCCESS(f"{username} is now a team lead."))
