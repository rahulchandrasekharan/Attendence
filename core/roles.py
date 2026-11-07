"""Roles: every logged-in user is a trainer (mentor) of their own batches.
Members of the "Team Lead" group (or superusers) can also see every trainer's students."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

TEAM_LEAD_GROUP = "Team Lead"


def is_team_lead(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if not hasattr(user, "_is_team_lead"):
        user._is_team_lead = user.groups.filter(name=TEAM_LEAD_GROUP).exists()
    return user._is_team_lead


def team_lead_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_team_lead(request.user):
            raise PermissionDenied("Only team leads can open this page.")
        return view(request, *args, **kwargs)
    return wrapper


def roles(request):
    """Template context processor: exposes `is_team_lead`."""
    return {"is_team_lead": is_team_lead(request.user)}
