from core.testing import StaffTestCase
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from code_review.github import GitHubError
from .models import Incident, Deployment, DeploymentDiff
from .deployment_diff import fetch_deployment_diff, save_deployment_diff


class DeploymentDiffTests(StaffTestCase):
    def setUp(self):
        self.incident = Incident.objects.create(title="Failure", affected_service="api", description="Errors", occurred_at=timezone.now())
        self.deployment = Deployment.objects.create(incident=self.incident, service="api", environment="production", deployed_at=timezone.now(), repository="example/project", commit_sha="b" * 40, previous_commit_sha="a" * 40)
        self.data = {"status": "ahead", "base_commit": {"sha": "a" * 40}, "merge_base_commit": {"sha": "a" * 40}, "files": [{"filename": "app.py", "status": "modified", "sha": "c" * 40, "additions": 1, "deletions": 1, "patch": "@@ -1 +1 @@\n-old\n+new"}]}
        self.url = reverse("incidents:deployment_fetch_diff", args=[self.incident.pk, self.deployment.pk])

    def test_save_redirect_refresh_and_repeated_post_reuse_snapshot(self):
        with patch("incidents.deployment_diff.github_json", side_effect=[{"sha": "b" * 40}, self.data]) as fetch:
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, 302)
            self.assertContains(self.client.get(response.url), "Show saved diff")
            self.client.post(self.url)
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(DeploymentDiff.objects.count(), 1)
        self.assertEqual(DeploymentDiff.objects.get().snapshot["base_sha"], "a" * 40)

    def test_missing_sha_and_unsafe_repo_no_network(self):
        with patch("incidents.deployment_diff.github_json") as fetch:
            self.deployment.previous_commit_sha = ""
            with self.assertRaises(GitHubError):
                fetch_deployment_diff(self.deployment)
            self.deployment.repository = "example/../other"
            with self.assertRaises(GitHubError):
                fetch_deployment_diff(self.deployment)
            fetch.assert_not_called()

    def test_reject_divergence_and_wrong_revision(self):
        for changes in ({"status": "behind"}, {"status": "diverged"}, {"merge_base_commit": {"sha": "d" * 40}}, {"base_commit": {"sha": "d" * 40}}):
            with patch("incidents.deployment_diff.github_json", side_effect=[{"sha": "b" * 40}, {**self.data, **changes}]):
                with self.assertRaises(GitHubError):
                    save_deployment_diff(self.deployment)
        self.assertEqual(DeploymentDiff.objects.count(), 0)

    def test_limits_and_missing_patch(self):
        row = self.data["files"][0]
        self.data["files"] = [{**row, "patch": "x" * 20001}, {**row, "patch": None}] + [row] * 99
        with patch("incidents.deployment_diff.github_json", side_effect=[{"sha": "b" * 40}, self.data]):
            result = fetch_deployment_diff(self.deployment)
        self.assertEqual(len(result["files"]), 100)
        self.assertTrue(result["file_list_limited"])
        self.assertTrue(result["files"][0]["patch_truncated"])
        self.assertTrue(result["files"][1]["patch_missing"])

    def test_error_page_no_record(self):
        with patch("incidents.deployment_diff.github_json", side_effect=GitHubError("Rate limit")):
            response = self.client.post(self.url)
        self.assertContains(response, "Rate limit")
        self.assertEqual(DeploymentDiff.objects.count(), 0)

    def test_escape_and_scope_and_csrf(self):
        self.data["files"][0]["patch"] = "<script>alert(1)</script>"
        with patch("incidents.deployment_diff.github_json", side_effect=[{"sha": "b" * 40}, self.data]):
            response = self.client.post(self.url, follow=True)
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertEqual(self.client.post(reverse("incidents:deployment_fetch_diff", args=[999, self.deployment.pk])).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url).status_code, 403)
