from core.testing import StaffTestCase
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from code_review.github import GitHubError
from .models import Incident, Deployment, DeploymentDiff
from .deployment_diff import review_deployment_diff


class DeploymentReviewTests(StaffTestCase):
    def setUp(self):
        self.incident = Incident.objects.create(title="Failure", affected_service="api", description="Errors", occurred_at=timezone.now())
        self.deployment = Deployment.objects.create(incident=self.incident, service="api", environment="production", deployed_at=timezone.now(), repository="example/project", commit_sha="b" * 40, previous_commit_sha="a" * 40)
        self.snapshot = {"repository": "example/project", "base_sha": "a" * 40, "head_sha": "b" * 40, "file_list_limited": False, "files": [{"filename": "app.py", "sha": "c" * 40, "status": "modified"}]}
        self.saved = DeploymentDiff.objects.create(deployment=self.deployment, snapshot=self.snapshot)
        self.url = reverse("incidents:deployment_review", args=[self.incident.pk, self.deployment.pk])

    def test_saved_review_uses_pinned_snapshot_and_does_not_refetch(self):
        with patch("code_review.pr_analysis.fetch_python_source", return_value="requests.get(url)") as fetch:
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, 302)
            self.assertContains(self.client.get(response.url), "HTTP request has no timeout")
            self.client.post(self.url)
            fetch.assert_called_once()
            self.assertEqual(fetch.call_args.args[0]["head_sha"], "b" * 40)
            self.assertEqual(fetch.call_args.args[1]["sha"], "c" * 40)
        self.saved.refresh_from_db()
        self.assertEqual(self.saved.snapshot, self.snapshot)
        self.assertEqual(self.saved.code_review["analysis_summary"]["counts"]["HIGH"], 1)

    def test_missing_diff_friendly_error(self):
        self.saved.delete()
        response = self.client.post(self.url)
        self.assertContains(response, "Fetch and save the Git diff")

    def test_failed_file_is_preserved_without_clean_claim(self):
        with patch("code_review.pr_analysis.fetch_python_source", side_effect=GitHubError("Unavailable")):
            response = self.client.post(self.url, follow=True)
        self.assertContains(response, "This is not a clean review")
        self.saved.refresh_from_db()
        self.assertEqual(self.saved.code_review["analysis_summary"]["failed"], 1)

    def test_skips_and_limits(self):
        files = [{"filename": f"file{i}.py", "sha": "c" * 40, "status": "modified"} for i in range(6)]
        files += [{"filename": "gone.py", "status": "removed"}, {"filename": "readme.md", "status": "modified"}]
        self.saved.snapshot["files"] = files
        self.saved.save()
        with patch("code_review.pr_analysis.fetch_python_source", return_value="pass") as fetch:
            result = review_deployment_diff(self.deployment)
        self.assertEqual(fetch.call_count, 5)
        self.assertEqual(result.code_review["analysis_summary"]["skipped"], 3)
        self.assertTrue(result.code_review["analysis_summary"]["partial"])

    def test_scope_method_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(reverse("incidents:deployment_review", args=[999, self.deployment.pk])).status_code, 404)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url).status_code, 403)
