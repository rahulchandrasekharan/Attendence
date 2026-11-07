"""Create demo trainers, their batches and a team lead:  python manage.py seed_demo"""
import datetime as dt

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from core.models import Batch
from core.roles import TEAM_LEAD_GROUP

# Demo accounts only - change these passwords after first login.
TRAINERS = {
    ("rahul", "Rahul", "mentor123"): [("Batch 1", "09:00", "11:00"), ("Batch 2", "11:00", "13:00"),
                                      ("Batch 3", "14:00", "16:00")],
    ("priya", "Priya", "mentor123"): [("Morning DS", "10:00", "12:00"), ("Evening DS", "16:00", "18:00")],
}
LEAD = ("lead", "Team Lead", "lead123")


def _user(username, first_name, password):
    user, created = User.objects.get_or_create(username=username, defaults={"first_name": first_name})
    if created:
        user.set_password(password)
        user.save()
    return user, created


class Command(BaseCommand):
    help = "Create demo trainers rahul/priya with batches, and team lead 'lead'."

    def handle(self, *args, **opts):
        for (username, first, password), batches in TRAINERS.items():
            user, created = _user(username, first, password)
            for name, s, e in batches:
                Batch.objects.get_or_create(mentor=user, name=name, defaults={
                    "start_time": dt.time.fromisoformat(s), "end_time": dt.time.fromisoformat(e)})
            self.stdout.write(self.style.SUCCESS(
                f"Trainer '{username}' ready with {user.batches.count()} batches"
                + (f" (password: {password})" if created else "")))

        lead, created = _user(*LEAD)
        lead.groups.add(Group.objects.get_or_create(name=TEAM_LEAD_GROUP)[0])
        self.stdout.write(self.style.SUCCESS(
            f"Team lead '{LEAD[0]}' ready" + (f" (password: {LEAD[2]})" if created else "")))
