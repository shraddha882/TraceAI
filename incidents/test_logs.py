from core.testing import StaffTestCase
from pathlib import Path
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .log_analysis import analyze_logs
from .models import Incident, LogEvidence


class LogAnalyzerTests(SimpleTestCase):
    def test_json_demo_and_diagnostic_line(self):
        source = (Path(__file__).resolve().parent.parent / "examples/incident_json_demo.jsonl").read_text()
        result = analyze_logs(source)
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["error_count"], 3)
        self.assertEqual(result["groups"][0]["lines"], [2, 3])
        self.assertEqual(result["timestamp_count"], 5)
        self.assertEqual(result["timestamps_without_timezone"], 1)
        self.assertEqual(result["json_lines"], 6)
        self.assertEqual(result["diagnostics"][0]["line"], 6)

    def test_mixed_formats_group_matching_messages(self):
        result = analyze_logs('ERROR failed\n\n{"level":"error","message":"failed"}\n[INFO] okay')
        self.assertEqual(result["groups"][0]["lines"], [1, 3])
        self.assertEqual(result["counts"], {"ERROR": 2, "INFO": 1})

    def test_invalid_fields_stay_unknown(self):
        rows = [{}, {"level": 50, "message": "failed"}, {"level": "ERROR", "message": {}},
                {"level": "ERROR", "message": "", "msg": "ignored"},
                {"level": None, "severity": "ERROR", "message": "failed"}, []]
        result = analyze_logs('\n'.join(json.dumps(row) for row in rows))
        self.assertEqual(result["counts"], {"UNKNOWN": len(rows)})
        self.assertEqual(result["diagnostic_count"], len(rows))

    def test_invalid_timestamp_preserves_error_classification(self):
        for value in (12345, "2026-99-99T10:00:00Z", "2026-09-24", {}):
            with self.subTest(value=value):
                result = analyze_logs(json.dumps({"level": "ERROR", "message": "failed", "timestamp": value}))
                self.assertEqual(result["error_count"], 1)
                self.assertEqual(result["timestamp_count"], 0)
                self.assertEqual(result["diagnostic_count"], 1)

    def test_offsets_and_message_newlines(self):
        result = analyze_logs(json.dumps({"level": "ERROR", "message": "first\nsecond", "timestamp": "2026-01-01T10:00:00+05:30"}))
        self.assertEqual(result["total_lines"], 1)
        self.assertEqual(result["evidence"][0]["message"], "first\nsecond")
        self.assertIn("+05:30", result["evidence"][0]["timestamp"])

    def test_deep_json_and_diagnostic_limit(self):
        result = analyze_logs('[' * 2000 + ']' * 2000)
        self.assertEqual(result["diagnostic_count"], 1)
        result = analyze_logs('{bad}\n' * 101)
        self.assertEqual(result["diagnostic_count"], 101)
        self.assertEqual(len(result["diagnostics"]), 100)
        self.assertTrue(result["diagnostics_truncated"])

    def test_demo_evidence_counts_and_exact_lines(self):
        source = (Path(__file__).resolve().parent.parent / "examples/incident_demo.log").read_text()
        result = analyze_logs(source)
        self.assertEqual(result["error_count"], 3)
        self.assertEqual(result["groups"][0]["count"], 2)
        self.assertEqual(result["groups"][0]["lines"], [2, 3])
        self.assertEqual(result["timestamp_count"], 6)
        self.assertEqual(result["timestamps_without_timezone"], 1)

    def test_unrecognized_text_and_blank_lines_keep_line_numbers(self):
        result = analyze_logs('INFO no ERROR happened\n\n[ERROR] failure\nTraceback: exception')
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["counts"]["UNKNOWN"], 1)
        self.assertEqual(result["evidence"][0]["line"], 3)

    def test_aliases_offsets_invalid_timestamps(self):
        result = analyze_logs('2026-01-01T10:30:00+05:30 FATAL failed\nWARN slow\n2026-99-99T10:00:00Z ERROR invalid')
        self.assertEqual(result["counts"], {"CRITICAL": 1, "WARNING": 1, "UNKNOWN": 1})
        self.assertIn("+05:30", result["evidence"][0]["timestamp"])

    def test_limits_and_truncation_are_explicit(self):
        for source in (' ', 'x' * (1024 * 1024 + 1), 'INFO ok\n' * 10001):
            with self.assertRaises(ValueError):
                analyze_logs(source)
        result = analyze_logs('\n'.join(f'ERROR failure {i}' for i in range(101)))
        self.assertEqual(result["error_count"], 101)
        self.assertTrue(result["evidence_truncated"])
        self.assertTrue(result["groups_truncated"])


class LogEvidenceTests(StaffTestCase):
    def test_json_upload_and_escaped_saved_output(self):
        source = '{"level":"ERROR","message":"<script>alert(1)</script>"}\n{bad}'
        for extension in ("JSONL", "ndjson"):
            response = self.client.post(self.url, {"log_file": SimpleUploadedFile("demo." + extension, source.encode())})
            self.assertEqual(response.status_code, 302)
            page = self.client.get(response.url)
            self.assertContains(page, "Parsing diagnostics")
            self.assertContains(page, "&lt;script&gt;")
            self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertEqual(LogEvidence.objects.latest("pk").source_text, source)

    def test_version_one_saved_report_remains_readable(self):
        old = LogEvidence.objects.create(incident=self.incident, source_name="old", source_text="ERROR failed", analysis={"version": 1, "error_count": 1, "counts": {"ERROR": 1}})
        before = old.analysis
        page = self.client.get(reverse("incidents:log_detail", args=[self.incident.pk, old.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "JSON candidate lines")
        old.refresh_from_db()
        self.assertEqual(old.analysis, before)

    def setUp(self):
        self.incident = Incident.objects.create(title="Failure", affected_service="api", description="Errors", occurred_at=timezone.now())
        self.url = reverse("incidents:logs_create", args=[self.incident.pk])

    def test_paste_saved_and_reopen_without_duplicate(self):
        response = self.client.post(self.url, {"logs": "ERROR database timeout\nERROR database timeout"})
        saved = LogEvidence.objects.get()
        self.assertEqual(saved.incident, self.incident)
        self.assertEqual(saved.analysis["groups"][0]["lines"], [1, 2])
        self.assertRedirects(response, reverse("incidents:log_detail", args=[self.incident.pk, saved.pk]))
        self.assertContains(self.client.get(response.url), "2 occurrence(s)")
        self.client.get(response.url)
        self.assertEqual(LogEvidence.objects.count(), 1)
        self.assertContains(self.client.get(reverse("incidents:detail", args=[self.incident.pk])), response.url)

    def test_upload_wins_and_decodes_bom(self):
        self.client.post(self.url, {"logs": "different", "log_file": SimpleUploadedFile("demo.LOG", b'\xef\xbb\xbfERROR failed')})
        self.assertEqual(LogEvidence.objects.get().source_text, "ERROR failed")

    def test_invalid_inputs_do_not_save(self):
        for name, content in (("bad.py", b"ERROR failed"), ("bad.txt", b"\xff"), ("empty.log", b""), ("big.log", b"x" * (1024 * 1024 + 1))):
            response = self.client.post(self.url, {"logs": "ERROR fallback", "log_file": SimpleUploadedFile(name, content)})
            self.assertTrue(response.context["form"].errors)
        for source in ("", " \n", "x" * (1024 * 1024 + 1), "INFO x\n" * 10001):
            response = self.client.post(self.url, {"logs": source})
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(LogEvidence.objects.count(), 0)

    def test_escape_scope_and_csrf(self):
        response = self.client.post(self.url, {"logs": "ERROR <script>alert(1)</script>"})
        page = self.client.get(response.url)
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertContains(page, "&lt;script&gt;")
        saved = LogEvidence.objects.get()
        other = Incident.objects.create(title="Other", affected_service="api", description="Errors", occurred_at=timezone.now())
        self.assertEqual(self.client.get(reverse("incidents:log_detail", args=[other.pk, saved.pk])).status_code, 404)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, {"logs": "ERROR x"}).status_code, 403)
