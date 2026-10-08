"""Owner filtering; staff retain access to legacy unowned records."""
from django.db.models import Q


def owned_by(queryset, user, field='owner'):
    access = Q(**{field: user})
    if user.is_staff:
        access |= Q(**{field + '__isnull': True})
    return queryset.filter(access)
