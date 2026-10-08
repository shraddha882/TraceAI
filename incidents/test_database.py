from core.testing import StaffTestCase
import json
from pathlib import Path
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .db_analysis import analyze_db_snapshot
from .models import Incident, DatabaseEvidence


def sample():
    return json.loads((Path(__file__).resolve().parent.parent / "examples/database_snapshot.json").read_text())


class DatabaseAnalyzerTests(SimpleTestCase):
    def test_demo(self):
        result = analyze_db_snapshot(json.dumps(sample()))
        self.assertEqual(len(result["findings"]), 3)
        self.assertEqual(result["connection_usage_percent"], 90)
        self.assertIn("queries[0]", result["findings"][1]["evidence"])

    def test_boundaries(self):
        data = sample()
        data.update(current_connections=80, oldest_lock_wait_ms=1000)
        data["queries"][0]["duration_ms"] = 1000
        self.assertEqual(len(analyze_db_snapshot(json.dumps(data))["findings"]), 3)
        data.update(current_connections=79, oldest_lock_wait_ms=999)
        data["queries"][0]["duration_ms"] = 999
        self.assertEqual(analyze_db_snapshot(json.dumps(data))["findings"], [])

    def test_invalid_values_and_missing_fields(self):
        for key, value in (("current_connections", True), ("max_connections", 0),
                           ("current_connections", 101), ("lock_wait_count", -1),
                           ("oldest_lock_wait_ms", float("nan")), ("queries", {}),
                           ("captured_at", "2026-01-01T10:00:00"), ("database", " ")):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    analyze_db_snapshot(json.dumps({**sample(), key: value}))
        for key in sample():
            data = sample()
            del data[key]
            with self.assertRaises(ValueError):
                analyze_db_snapshot(json.dumps(data))

    def test_malformed_and_oversized(self):
        for source in ("bad", "[]", "x" * (1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                analyze_db_snapshot(source)


class DatabaseEvidenceTests(StaffTestCase):
    def setUp(self):
        self.incident = Incident.objects.create(title="Failure", affected_service="api", description="Errors", occurred_at=timezone.now())
        self.url = reverse("incidents:database_create", args=[self.incident.pk])

    def test_save_reopen_and_refresh(self):
        source = json.dumps(sample())
        response = self.client.post(self.url, {"snapshot": source})
        saved = DatabaseEvidence.objects.get()
        self.assertEqual(saved.source_text, source)
        self.assertEqual(len(saved.analysis["findings"]), 3)
        self.assertRedirects(response, reverse("incidents:database_detail", args=[self.incident.pk, saved.pk]))
        self.assertContains(self.client.get(response.url), "High connection usage")
        self.assertEqual(DatabaseEvidence.objects.count(), 1)
        self.assertContains(self.client.get(reverse("incidents:detail", args=[self.incident.pk])), response.url)

    def test_upload_precedence_and_bom(self):
        source = json.dumps(sample())
        self.client.post(self.url, {"snapshot": "bad", "snapshot_file": SimpleUploadedFile("sample.JSON", source.encode("utf-8-sig"))})
        self.assertEqual(DatabaseEvidence.objects.get().source_text, source)

    def test_invalid_upload_and_input_do_not_save(self):
        for name, content in (("a.txt", b"{}"), ("a.json", b"\xff"), ("a.json", b"")):
            page = self.client.post(self.url, {"snapshot": json.dumps(sample()), "snapshot_file": SimpleUploadedFile(name, content)})
            self.assertTrue(page.context["form"].errors)
        page = self.client.post(self.url, {"snapshot": "{}"})
        self.assertTrue(page.context["form"].errors)
        self.assertEqual(DatabaseEvidence.objects.count(), 0)

    def test_escaping_scope_and_csrf(self):
        data = sample()
        data["database"] = "<script>alert(1)</script>"
        response = self.client.post(self.url, {"snapshot": json.dumps(data)})
        self.assertNotContains(self.client.get(response.url), "<script>alert(1)</script>")
        self.assertContains(self.client.get(response.url), "&lt;script&gt;")
        saved = DatabaseEvidence.objects.get()
        self.assertEqual(self.client.get(reverse("incidents:database_detail", args=[999, saved.pk])).status_code, 404)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, {"snapshot": json.dumps(data)}).status_code, 403)
