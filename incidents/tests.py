from core.testing import StaffTestCase
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import IncidentForm
from .models import Incident


class IncidentTests(StaffTestCase):
    def setUp(self):
        self.data = {
            "title": "Checkout errors", "affected_service": "checkout-api",
            "description": "HTTP 500 responses increased.\nPayments are failing.",
            "occurred_at": "2026-01-01T10:30",
        }
        self.create_url = reverse("incidents:create")

    def create_incident(self):
        self.client.post(self.create_url, self.data)
        return Incident.objects.latest("pk")

    def test_create_redirects_and_refresh_does_not_duplicate(self):
        response = self.client.post(self.create_url, self.data)
        incident = Incident.objects.get()
        self.assertRedirects(response, reverse("incidents:detail", args=[incident.pk]))
        self.assertEqual(incident.title, self.data["title"])
        self.assertEqual(incident.affected_service, self.data["affected_service"])
        self.assertEqual(incident.description, self.data["description"])
        self.assertEqual(incident.occurred_at, datetime(2026, 1, 1, 10, 30, tzinfo=dt_timezone.utc))
        self.client.get(response.url)
        self.assertEqual(Incident.objects.count(), 1)

    def test_blank_and_invalid_fields_do_not_save(self):
        for field, value in (("title", "  "), ("affected_service", ""),
                             ("description", "\n "), ("occurred_at", "invalid"),
                             ("title", "x" * 201), ("description", "x" * 10001),
                             ("occurred_at", (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"))):
            with self.subTest(field=field):
                response = self.client.post(self.create_url, {**self.data, field: value})
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertContains(response, "has not been saved")
        self.assertEqual(Incident.objects.count(), 0)

    def test_empty_post_shows_errors_and_get_does_not_save(self):
        self.assertFalse(self.client.get(self.create_url).context["form"].is_bound)
        self.assertTrue(self.client.post(self.create_url, {}).context["form"].errors)
        self.assertEqual(Incident.objects.count(), 0)

    def test_utc_input_is_independent_of_active_timezone(self):
        with timezone.override("Asia/Kolkata"):
            form = IncidentForm(self.data)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["occurred_at"].hour, 10)
            self.assertEqual(form.cleaned_data["occurred_at"].utcoffset(), timedelta(0))

    def test_list_detail_and_dashboard_navigation(self):
        incident = self.create_incident()
        url = reverse("incidents:detail", args=[incident.pk])
        self.assertContains(self.client.get(reverse("dashboard")), reverse("incidents:list"))
        self.assertContains(self.client.get(reverse("incidents:list")), url)
        page = self.client.get(url)
        for text in ("Checkout errors", "checkout-api", "01 Jan 2026, 10:30", "UTC", "not available yet"):
            self.assertContains(page, text)

    def test_empty_list_and_pagination(self):
        self.assertContains(self.client.get(reverse("incidents:list")), "No incidents recorded")
        Incident.objects.bulk_create([
            Incident(title=f"Incident {i}", affected_service="api", description="Errors",
                     occurred_at=timezone.now()) for i in range(21)
        ])
        first = self.client.get(reverse("incidents:list"))
        self.assertEqual(len(first.context["page"]), 20)
        self.assertEqual(first.context["page"][0].pk, Incident.objects.latest("pk").pk)
        second = self.client.get(reverse("incidents:list"), {"page": 2})
        self.assertEqual(len(second.context["page"]), 1)

    def test_content_is_escaped(self):
        self.data["title"] = "<script>alert(1)</script>"
        self.data["description"] = "<img src=x onerror=alert(1)>"
        incident = self.create_incident()
        for url in (reverse("incidents:list"), reverse("incidents:detail", args=[incident.pk])):
            response = self.client.get(url)
            self.assertNotContains(response, "<script>alert(1)</script>")
            self.assertContains(response, "&lt;script&gt;")

    def test_csrf_missing_incident_and_method_restrictions(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.create_url, self.data).status_code, 403)
        detail = reverse("incidents:detail", args=[999])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.post(detail).status_code, 405)
        self.assertEqual(self.client.post(reverse("incidents:list")).status_code, 405)
