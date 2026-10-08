from core.testing import StaffTestCase
from datetime import datetime, timedelta, timezone
from django.test import TestCase
from django.urls import reverse
from .models import Incident, Deployment, TraceEvidence, LogEvidence, DatabaseEvidence
from .correlation import correlate_incident


class CorrelationTests(StaffTestCase):
    def setUp(self):
        self.time = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
        self.incident = Incident.objects.create(title="Incident", affected_service="api", description="Error", occurred_at=self.time)

    def span(self, service="api", offset=0):
        return {"trace_id": "t", "span_id": "s", "service": service, "operation": "request", "status": "ERROR", "duration_ms": 10, "started_at": (self.time + timedelta(seconds=offset)).isoformat()}

    def deployment(self, offset=-60, service="api"):
        return Deployment.objects.create(incident=self.incident, service=service, environment="production", repository="example/repo", commit_sha="a" * 40, deployed_at=self.time + timedelta(seconds=offset))

    def test_same_service_relationship_and_source_links(self):
        self.deployment()
        TraceEvidence.objects.create(incident=self.incident, source_text="{}", analysis={"spans": [self.span()]})
        result = correlate_incident(self.incident)
        self.assertEqual(len(result["relationships"]), 1)
        self.assertEqual([e["kind"] for e in result["events"]], ["deployment", "trace"])
        for event in result["events"]:
            self.assertTrue(event["url"].startswith(f"/incidents/{self.incident.pk}/"))

    def test_post_incident_and_different_service_do_not_correlate(self):
        self.deployment(30)
        self.deployment(-30, "other")
        TraceEvidence.objects.create(incident=self.incident, source_text="{}", analysis={"spans": [self.span(offset=60)]})
        self.assertEqual(correlate_incident(self.incident)["relationships"], [])

    def test_boundaries_unknown_time_and_timezone_offset(self):
        LogEvidence.objects.create(incident=self.incident, source_name="logs", source_text="", analysis={"evidence": [
            {"line": 1, "message": "error", "timestamp": "2026-01-01T15:30:00+05:30"},
            {"line": 2, "message": "error", "timestamp": "2026-01-01T10:00:00"}]})
        self.deployment(-900)
        self.deployment(901)
        result = correlate_incident(self.incident)
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(len(result["excluded"]), 2)
        self.assertEqual(result["events"][1]["service_match"], "unknown")

    def test_other_incident_is_excluded_and_page_escapes(self):
        other = Incident.objects.create(title="other", affected_service="api", description="", occurred_at=self.time)
        TraceEvidence.objects.create(incident=other, source_text="", analysis={"spans": [self.span()]})
        self.assertEqual(correlate_incident(self.incident)["events"], [])
        self.incident.title = "<script>alert(1)</script>"
        self.incident.save()
        url = reverse("incidents:correlation", args=[self.incident.pk])
        page = self.client.get(url)
        self.assertContains(page, "&lt;script&gt;")
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.get(reverse("incidents:correlation", args=[999])).status_code, 404)
