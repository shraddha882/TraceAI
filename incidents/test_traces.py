from core.testing import StaffTestCase
import json
from pathlib import Path
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .trace_analysis import analyze_trace_snapshot
from .models import Incident, TraceEvidence


def sample():
    return json.loads((Path(__file__).resolve().parent.parent / "examples/trace_snapshot.json").read_text())


class TraceAnalyzerTests(SimpleTestCase):
    def test_demo_and_service_counts(self):
        result = analyze_trace_snapshot(json.dumps(sample()))
        self.assertEqual((result["span_count"], result["trace_count"], result["failed_spans"], result["slow_spans"]), (3, 2, 2, 2))
        self.assertEqual(len(result["findings"]), 4)
        self.assertEqual(result["services"][0]["spans"], 2)

    def test_boundary_and_unset(self):
        span = sample()["spans"][0]
        span.update(status="UNSET", duration_ms=1000)
        self.assertEqual(len(analyze_trace_snapshot(json.dumps({"spans": [span]}))["findings"]), 1)
        span["duration_ms"] = 999
        self.assertEqual(analyze_trace_snapshot(json.dumps({"spans": [span]}))["findings"], [])

    def test_invalid_metrics_fields_and_time(self):
        for key, value in (("duration_ms", True), ("duration_ms", -1), ("duration_ms", float("inf")), ("status", "bad"), ("span_id", ""), ("started_at", "2026-01-01T10:00:00")):
            data = sample()
            data["spans"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analyze_trace_snapshot(json.dumps(data))
        for key in sample()["spans"][0]:
            data = sample()
            del data["spans"][0][key]
            with self.assertRaises(ValueError):
                analyze_trace_snapshot(json.dumps(data))

    def test_duplicate_and_limits(self):
        span = sample()["spans"][0]
        for source in ("bad", "[]", '{"spans":[]}', json.dumps({"spans": [span, span]}), json.dumps({"spans": [span] * 101}), "x" * (1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                analyze_trace_snapshot(source)


class TracePageTests(StaffTestCase):
    def setUp(self):
        self.incident = Incident.objects.create(title="Failure", affected_service="api", description="Errors", occurred_at=timezone.now())
        self.url = reverse("incidents:trace_create", args=[self.incident.pk])

    def test_save_reopen_refresh_and_link(self):
        source = json.dumps(sample())
        response = self.client.post(self.url, {"snapshot": source})
        saved = TraceEvidence.objects.get()
        self.assertEqual(saved.source_text, source)
        self.assertRedirects(response, reverse("incidents:trace_detail", args=[self.incident.pk, saved.pk]))
        self.assertContains(self.client.get(response.url), "Slow span")
        self.assertEqual(TraceEvidence.objects.count(), 1)
        self.assertContains(self.client.get(reverse("incidents:detail", args=[self.incident.pk])), response.url)

    def test_upload_and_invalid_input(self):
        source = json.dumps(sample())
        self.client.post(self.url, {"snapshot": "bad", "snapshot_file": SimpleUploadedFile("sample.JSON", source.encode("utf-8-sig"))})
        self.assertEqual(TraceEvidence.objects.get().source_text, source)
        for name, content in (("bad.txt", b"{}"), ("bad.json", b"\xff"), ("empty.json", b"")):
            page = self.client.post(self.url, {"snapshot_file": SimpleUploadedFile(name, content)})
            self.assertTrue(page.context["form"].errors)
        self.assertEqual(TraceEvidence.objects.count(), 1)

    def test_escaping_scope_and_csrf(self):
        data = sample()
        data["spans"][0]["service"] = "<script>alert(1)</script>"
        response = self.client.post(self.url, {"snapshot": json.dumps(data)})
        self.assertNotContains(self.client.get(response.url), "<script>alert(1)</script>")
        self.assertContains(self.client.get(response.url), "&lt;script&gt;")
        saved = TraceEvidence.objects.get()
        self.assertEqual(self.client.get(reverse("incidents:trace_detail", args=[999, saved.pk])).status_code, 404)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, {"snapshot": json.dumps(data)}).status_code, 403)
