from core.testing import StaffTestCase
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from .models import Incident, Deployment, TraceEvidence, RCAReport
from .rca import build_rca_report
from .jobs import run_next_rca_job


class RCATests(StaffTestCase):
    def setUp(self):
        self.time = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
        self.incident = Incident.objects.create(title="Incident", affected_service="api", description="Error", occurred_at=self.time)
        self.url = reverse("incidents:rca_create", args=[self.incident.pk])

    def test_empty_evidence_is_insufficient(self):
        report = build_rca_report(self.incident)
        self.assertEqual(report["status"], "Insufficient evidence")
        self.assertEqual(report["hypotheses"], [])
        self.assertTrue(report["correlation"]["gaps"])

    def test_hypothesis_links_actual_evidence_with_low_confidence(self):
        Deployment.objects.create(incident=self.incident, service="api", environment="production", repository="example/repo", commit_sha="a" * 40, deployed_at=self.time - timedelta(seconds=60))
        TraceEvidence.objects.create(incident=self.incident, source_text="{}", analysis={"spans": [{"trace_id": "t", "span_id": "s", "service": "api", "operation": "request", "status": "ERROR", "duration_ms": 10, "started_at": self.time.isoformat()}]})
        report = build_rca_report(self.incident)
        self.assertEqual(len(report["hypotheses"]), 1)
        hypothesis = report["hypotheses"][0]
        self.assertIn("Low", hypothesis["confidence"])
        self.assertEqual(len(hypothesis["evidence"]), 2)
        self.assertIn("No confirmed root cause", report["summary"])

    def test_saved_snapshot_does_not_recompute_or_duplicate_on_get(self):
        response = self.client.post(self.url)
        run_next_rca_job()
        saved = RCAReport.objects.get()
        report_url = reverse('incidents:rca_detail', args=[self.incident.pk, saved.pk])
        before = saved.snapshot
        self.incident.title = "Changed later"
        self.incident.save()
        with patch("incidents.rca.correlate_incident", side_effect=AssertionError("Must not recompute")):
            self.assertContains(self.client.get(report_url), "Insufficient evidence")
            self.client.get(report_url)
        saved.refresh_from_db()
        self.assertEqual(saved.snapshot, before)
        self.assertEqual(RCAReport.objects.count(), 1)
        self.assertContains(self.client.get(reverse("incidents:detail", args=[self.incident.pk])), report_url)

    def test_scope_csrf_and_escaping(self):
        self.incident.title = "<script>alert(1)</script>"
        self.incident.save()
        response = self.client.post(self.url)
        run_next_rca_job()
        report_url = reverse('incidents:rca_detail', args=[self.incident.pk, RCAReport.objects.get().pk])
        page = self.client.get(report_url)
        self.assertContains(page, "&lt;script&gt;")
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url).status_code, 403)
        self.assertEqual(self.client.get(reverse("incidents:rca_detail", args=[999, RCAReport.objects.get().pk])).status_code, 404)
