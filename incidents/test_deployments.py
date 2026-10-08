from core.testing import StaffTestCase
from datetime import datetime, timedelta, timezone as tz
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import Incident, Deployment
from .deployment_forms import DeploymentForm


class DeploymentTests(StaffTestCase):
    def setUp(self):
        self.incident = Incident.objects.create(title="Failure", affected_service="api", description="Errors", occurred_at=datetime(2026, 1, 1, 10, tzinfo=tz.utc))
        self.url = reverse("incidents:deployment_create", args=[self.incident.pk])
        self.data = {"service": "api", "environment": "production", "deployed_at": "2026-01-01T09:50", "repository": "example/project", "commit_sha": "A" * 40, "previous_commit_sha": "b" * 40, "notes": "Release"}

    def test_save_and_refresh(self):
        response = self.client.post(self.url, self.data)
        saved = Deployment.objects.get()
        self.assertEqual(saved.commit_sha, "a" * 40)
        self.assertEqual(saved.previous_commit_sha, "b" * 40)
        self.assertEqual(saved.environment, "production")
        self.assertRedirects(response, reverse("incidents:deployment_detail", args=[self.incident.pk, saved.pk]))
        self.assertContains(self.client.get(response.url), "600 seconds before incident")
        self.assertEqual(Deployment.objects.count(), 1)
        self.assertContains(self.client.get(reverse("incidents:detail", args=[self.incident.pk])), response.url)

    def test_relative_time_and_chronological_order(self):
        for time in ("10:10", "09:50", "10:00"):
            self.client.post(self.url, {**self.data, "deployed_at": "2026-01-01T" + time})
        rows = list(self.incident.deployments.all())
        self.assertEqual([item.relative_time for item in rows], ["600 seconds before incident", "At the incident occurrence time", "600 seconds after incident"])

    def test_invalid_fields_no_records(self):
        for key, value in (("service", " "), ("environment", ""), ("repository", "https://github.com/a/b"), ("repository", "a/.."), ("commit_sha", "abc123"), ("previous_commit_sha", "x" * 40), ("deployed_at", "bad"), ("deployed_at", (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"))):
            with self.subTest(key=key):
                page = self.client.post(self.url, {**self.data, key: value})
                self.assertIn(key, page.context["form"].errors)
        self.assertEqual(Deployment.objects.count(), 0)

    def test_optional_previous_and_utc(self):
        with timezone.override("Asia/Kolkata"):
            form = DeploymentForm({**self.data, "previous_commit_sha": ""})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["deployed_at"].utcoffset(), timedelta(0))

    def test_scope_escape_and_csrf(self):
        response = self.client.post(self.url, {**self.data, "notes": "<script>alert(1)</script>"})
        page = self.client.get(response.url)
        self.assertContains(page, "&lt;script&gt;")
        self.assertNotContains(page, "<script>alert(1)</script>")
        saved = Deployment.objects.get()
        self.assertEqual(self.client.get(reverse("incidents:deployment_detail", args=[999, saved.pk])).status_code, 404)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, self.data).status_code, 403)
        self.assertEqual(self.client.post(response.url).status_code, 405)
