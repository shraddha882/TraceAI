"""Functional tests use approved accounts; access tests use anonymous clients."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase


class StaffClient(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user, _ = get_user_model().objects.get_or_create(username='test-staff', defaults={'is_staff': True})
        self.force_login(user)


class StaffTestCase(TestCase):
    client_class = StaffClient
